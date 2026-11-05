"""Run the existing API and n8n workflow against an isolated database."""
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
from secrets import compare_digest, token_urlsafe
import socket
import subprocess
from threading import Thread
from time import monotonic, sleep
from urllib.parse import urlsplit

from dotenv import dotenv_values
import httpx
import uvicorn
from starlette.responses import JSONResponse

from backend.config import ROOT, Settings
from backend.main import create_app


WORKFLOW = ROOT / "integrations/n8n/assign_report.json"
COMPOSE = ROOT / "integrations/compose.dataset.yaml"
WORKFLOW_ID = "socEvaluation001"


def flow_metadata(config):
    base = config.get("LANGFLOW_URL", "")
    flow_id = config.get("LANGFLOW_FLOW_ID", "")
    if urlsplit(base).hostname not in {"127.0.0.1", "localhost", "::1"} or not flow_id or not config.get("LANGFLOW_API_KEY"):
        raise ValueError("Configura el flujo y la credencial de Langflow local en .env.")
    with httpx.Client(base_url=base, timeout=10, trust_env=False) as client:
        login = client.get("/api/v1/auto_login").raise_for_status().json()
        graph = client.get(f"/api/v1/flows/{flow_id}", headers={
            "Authorization": "Bearer " + login["access_token"],
        }).raise_for_status().json()["data"]
    template = next(node["data"]["node"]["template"] for node in graph["nodes"]
                    if node["data"]["type"] == "SocCloudModel")
    return {"flow_id": flow_id, "graph_sha256": sha256(json.dumps(graph, sort_keys=True).encode()).hexdigest(),
            "models": {name: template[name]["value"] for name in ("groq_model", "gemini_model")}}


@contextmanager
def workflow_files(staging, api_port, callback_host, internal, webhook):
    staging.mkdir(exist_ok=True)
    graph = json.loads(WORKFLOW.read_text(encoding="utf-8"))
    graph.update(id=WORKFLOW_ID, name="SOC VCDB · Evaluación aislada")
    for node in graph["nodes"]:
        kind = node["type"].rsplit(".", 1)[1]
        if kind in {"webhook", "httpRequest"}:
            credential_id = "socEvalWebhook01" if kind == "webhook" else "socEvalInternal1"
            node["credentials"] = {"httpHeaderAuth": {"id": credential_id, "name": credential_id}}
            if kind == "httpRequest":
                node["parameters"]["url"] = node["parameters"]["url"].replace(
                    "http://host.docker.internal:8000/", f"http://{callback_host}:{api_port}/",
                )
    (staging / "workflow.json").write_text(json.dumps(graph), encoding="utf-8")
    credentials = staging / "credentials.json"
    credentials.write_text(json.dumps([
        {"id": identifier, "name": identifier, "type": "httpHeaderAuth", "data": {"name": name, "value": value}}
        for identifier, name, value in (("socEvalWebhook01", "X-Webhook-Token", webhook),
                                        ("socEvalInternal1", "X-Internal-Token", internal))
    ]), encoding="utf-8")
    try:
        yield
    finally:
        credentials.unlink(missing_ok=True)


class DockerStack:
    def __init__(self, directory, project):
        self.directory = directory
        self.project = project
        self.environment = directory / "compose.env"
        if not self.environment.exists():
            self.environment.write_text(f"DATASET_PG_PASSWORD={token_urlsafe(32)}\n"
                                        f"DATASET_N8N_KEY={token_urlsafe(32)}\n"
                                        f"DATASET_IMPORT_DIR='{(directory / 'import').as_posix()}'\n", encoding="utf-8")
        self.password = dotenv_values(self.environment)["DATASET_PG_PASSWORD"]

    def command(self, *args):
        try:
            result = subprocess.run([
                "docker", "compose", "--project-name", self.project, "--env-file", str(self.environment),
                "--file", str(COMPOSE), *args,
            ], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=240, check=False)
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError(f"Docker no pudo ejecutar {args[0]}.") from None
        if result.returncode:
            if "unable to start" in result.stderr.lower() or "500 internal server error" in result.stderr.lower():
                raise RuntimeError("Docker Desktop devolvió HTTP 500 o no pudo iniciar su motor Linux.")
            raise RuntimeError(f"Docker falló en {' '.join(args[:2])} (código {result.returncode}). "
                               f"Revisa el proyecto aislado {self.project}.")
        return result.stdout.strip()

    def url_port(self, service, internal_port):
        address = self.command("port", service, str(internal_port))
        return int(address.rsplit(":", 1)[1])

    def stop_router(self):
        self.command("stop", "n8n")

    def start_router(self):
        self.command("up", "-d", "--wait", "--wait-timeout", "120", "n8n")

    def close(self):
        self.command("down")

    def start(self, api_port, internal, webhook):
        self.stop_router()
        self.command("up", "-d", "--wait", "--wait-timeout", "120", "postgres")
        prefix = ("run", "--rm", "-T", "--no-deps", "n8n")
        with workflow_files(self.directory / "import", api_port, "host.docker.internal", internal, webhook):
            self.command(*prefix, "import:credentials", "--input=/soc-import/credentials.json")
            self.command(*prefix, "import:workflow", "--input=/soc-import/workflow.json")
            self.command(*prefix, "update:workflow", f"--id={WORKFLOW_ID}", "--active=true")
        self.start_router()
        return self.url_port("postgres", 5432), self.url_port("n8n", 5678)


@contextmanager
def stack(directory: Path, project: str, mode: str):
    local = mode == "local"
    native = mode == "native"
    operator, internal, webhook, gate = (token_urlsafe(32) for _ in range(4))
    services = None
    server = None
    thread = None
    with socket.socket() as listener:
        listener.bind(("0.0.0.0" if mode == "docker" else "127.0.0.1", 0))
        api_port = listener.getsockname()[1]
        options = {"operator_token": operator, "internal_token": internal, "report_limit": 30}
        metadata = {"mode": "sqlite/demo/local"}
        try:
            if not local:
                cfg = dotenv_values(ROOT / ".env")
                print("[Langflow] Verificando el flujo local y sus modelos.", flush=True)
                try:
                    metadata = {"mode": "postgresql/langflow/n8n", "langflow": flow_metadata(cfg),
                                "workflow_sha256": sha256(WORKFLOW.read_bytes()).hexdigest()}
                except (httpx.HTTPError, KeyError, StopIteration):
                    raise RuntimeError("Langflow local no está disponible o el flujo no contiene SocCloudModel.") from None
                if native:
                    from scripts.soc_dataset_native import NativeStack

                    services = NativeStack(directory)
                    print("[Windows] Preparando PostgreSQL y n8n nativos en carpetas de evaluación.", flush=True)
                else:
                    services = DockerStack(directory, project)
                    print(f"[Docker] Preparando PostgreSQL 16 y n8n en {project}.", flush=True)
                pg_port, n8n_port = services.start(api_port, internal, webhook)
                options.update(database_url=f"postgresql://soc_evaluation:{services.password}@127.0.0.1:{pg_port}/soc_evaluation",
                               classifier_mode="langflow", router_mode="n8n", langflow_url=cfg["LANGFLOW_URL"],
                               langflow_api_key=cfg["LANGFLOW_API_KEY"], langflow_flow_id=cfg["LANGFLOW_FLOW_ID"],
                               n8n_webhook_url=f"http://127.0.0.1:{n8n_port}/webhook/soc-assign-report",
                               n8n_webhook_token=webhook)
            settings = Settings(sqlite_path=directory / "evaluation.sqlite3", **options)
            app = create_app(settings)

            @app.middleware("http")
            async def evaluation_only(request, call_next):
                if not (request.url.path.startswith("/internal/") and compare_digest(
                        request.headers.get("X-Internal-Token", "").encode(), internal.encode())):
                    if not compare_digest(request.headers.get("X-Soc-Evaluation", "").encode(), gate.encode()):
                        return JSONResponse({"detail": "Entorno privado de evaluación."}, status_code=403)
                return await call_next(request)

            server = uvicorn.Server(uvicorn.Config(app, log_level="critical", access_log=False))
            thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
            thread.start()
            limit = monotonic() + 45
            while not server.started and thread.is_alive() and monotonic() < limit:
                sleep(0.1)
            if not server.started:
                raise RuntimeError("FastAPI de evaluación no pudo inicializarse.")
            with httpx.Client(base_url=f"http://127.0.0.1:{api_port}", timeout=115, trust_env=False, headers={
                "X-Soc-Evaluation": gate, "X-Operator-Token": operator,
            }) as client:
                expected = ("sqlite", "demo", "local") if local else ("postgresql", "langflow", "n8n")
                limit = monotonic() + 30
                while True:
                    health = client.get("/health?detalle=true").raise_for_status().json()
                    actual = tuple(health[key] for key in ("base", "clasificador", "enrutador"))
                    if health["estado"] == "ok" and actual == expected:
                        break
                    if actual != expected or monotonic() >= limit:
                        services_state = ", ".join(f"{key}={value}" for key, value in health["servicios"].items())
                        raise RuntimeError(f"La salud no coincide con el entorno solicitado ({services_state}).")
                    sleep(1)
                metadata["runtime"] = mode
                if not local:
                    with app.state.db.session() as execute:
                        metadata["postgresql_version"] = execute(
                            "SELECT current_setting('server_version') AS version"
                        ).fetchone()["version"]
                    metadata["n8n_version"] = services.n8n_version if native else "1.109.2"
                yield client, app.state.db, services, metadata
        finally:
            if server and thread:
                server.should_exit = True
                thread.join(15)
            if services:
                try:
                    services.close()
                except RuntimeError as error:
                    print(f"[Cierre de evaluación] {error}", flush=True)
