"""Opt-in Phase 6 verification using the authorized pilot case and an isolated Case 06 stack."""
from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from html import escape
import json
import re
from pathlib import Path
from secrets import token_urlsafe
from traceback import extract_tb
from uuid import UUID, uuid4

import httpx
from pydantic import SecretStr
from sqlalchemy.exc import SQLAlchemyError

from backend.classifier import Classification
from backend.config import Settings
from backend.db import utc_now
from backend.security import hash_password
from scripts.soc_dataset import lifecycle
from scripts.soc_dataset_stack import stack
from scripts.vcdb import SENSITIVE
from src.data.catalog import DatasetCatalog
from src.data.models import content_hash
from src.inference.services import SocApi
from src.inference.telemetry import valid_trace
from src.inference.workspace import InferenceWorkspace
from src.utils.config import AnalyticsSettings, load_config
from src.utils.errors import AnalyticsError
from src.utils.langflow import LangflowConformance, cloud_node, graph_contract, graph_digest
from src.utils.privacy import protect_text


def component_sync(connection: LangflowConformance, settings: AnalyticsSettings) -> dict:
    """Change source only, verify all other graph fields, and keep existing key references."""
    before = connection.fetch()
    template = cloud_node(before)["data"]["node"]["template"]
    for field, variable in (("groq_api_key", settings.flow_validation.groq_variable),
                            ("gemini_api_key", settings.flow_validation.gemini_variable)):
        if template[field].get("value") != variable or template[field].get("load_from_db") is not True:
            raise AnalyticsError("La actualización requiere las referencias existentes a credenciales, sin copiar valores.")
    changed = deepcopy(before)
    code = settings.path(settings.flow_validation.component_file).read_text(encoding="utf-8").strip()
    cloud_node(changed)["data"]["node"]["template"]["code"]["value"] = code
    graph_contract(changed, settings)
    path = connection._path(settings.flow_validation.flow_path)
    mutated = graph_digest(changed) != graph_digest(before)
    if mutated:
        connection._request("PATCH", path, json={"data": changed})
    try:
        current = connection.fetch()
        if graph_digest(current) != graph_digest(changed):
            raise AnalyticsError("La comprobación posterior detectó cambios adicionales en el grafo.")
        graph_contract(current, settings)
        serialized = json.dumps({"name": "SOC Report Router | Groq + Gemini", "is_component": False, "data": current},
                                ensure_ascii=False, indent=2) + "\n"
        if any(len(value) >= 8 and value in serialized for value in connection.operational.privacy_secrets()):
            raise AnalyticsError("El export contiene un valor reservado. Se canceló su publicación.")
        destination = settings.path(settings.flow_validation.export_file)
        staged = destination.with_suffix(".json.tmp")
        staged.write_text(serialized, encoding="utf-8")
        staged.replace(destination)
    except Exception:
        if mutated:
            connection._request("PATCH", path, json={"data": before})
        raise
    return {"changed_source_only": mutated, "graph_before_sha256": graph_digest(before),
            "graph_after_sha256": graph_digest(current), "source_sha256": sha256(code.encode()).hexdigest(),
            "models_prompt_and_bindings_preserved": True, **connection.check()}


def live_check(settings: AnalyticsSettings, connection: LangflowConformance, directory: Path,
               approved_hash: str, runtime: str, result: dict, resume: dict | None = None) -> dict:
    """Run two cloud requests on the same approved case, without a production report or test-set access."""
    source = DatasetCatalog(settings, SocApi(settings.api)).source(settings.flow_validation.probe_source_id)
    path = settings.path(source.path)
    original_bytes = path.read_bytes()
    case = json.loads(original_bytes)["cases"][settings.flow_validation.probe_case_index]
    text = f"Título: {case['titulo']}\n{case['descripcion']}"
    digest = sha256(text.encode()).hexdigest()
    if approved_hash != digest or case.get("redaction_reviewed") is not True or SENSITIVE.search(text):
        raise AnalyticsError("Esta prueba requiere autorización para la huella exacta del caso público revisado.")
    graph_before = graph_digest(connection.fetch())
    result.update({"case_input_sha256": digest, "source_id": source.id, "source_case_id": case["source_id"],
              "pilot_sha256": sha256(original_bytes).hexdigest(), "not_predictive_accuracy": True,
              "status": "running", "stage": "starting_isolated_stack", "max_flow_requests": 2})
    isolated = resume["directory"] if resume else directory / "isolated-stack"
    project = resume["project"] if resume else "soc-phase6-" + uuid4().hex[:12]
    if not resume:
        isolated.mkdir(parents=True, exist_ok=False)
    result.update(isolated_project=project, isolated_directory=str(isolated.relative_to(settings.root)),
                  max_flow_requests=1 if resume else 2, primary_reused=bool(resume))
    with stack(isolated, project, runtime) as (client, db, _services, metadata):
        result["stage"] = "isolated_stack_ready"
        with db.session(write=True) as execute:
            database = execute("SELECT current_database() AS name").fetchone()["name"]
            if database != "soc_evaluation":
                raise AnalyticsError("La comprobación exige una base aislada soc_evaluation.")
            password, actor = token_urlsafe(32), str(uuid4())
            username = "phase6-" + actor[:8]
            execute("INSERT INTO users(id,username,password_hash,role,creado_at) VALUES(%s,%s,%s,%s,%s)",
                    (actor, username, hash_password(password), "analista", utc_now()))
        login = client.post("/api/auth/login", json={"username": username, "password": password}).raise_for_status().json()
        token = SecretStr(login["access_token"])

        def forward(request: httpx.Request) -> httpx.Response:
            response = client.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        configured = settings.model_copy(update={"api": settings.api.model_copy(update={"base_url": str(client.base_url).rstrip("/")})})
        adapter = SocApi(configured.api, transport=httpx.MockTransport(forward))
        workspace = InferenceWorkspace(configured, adapter)
        if resume:
            prior = db.report(resume["report"])
            if not prior or any(prior[field] != case[field] for field in ("titulo", "descripcion")):
                raise AnalyticsError("El reporte de reanudación no corresponde al mismo caso autorizado.")
            snapshot = workspace.observe(resume["report"], token)
        else:
            result["stage"] = "primary_submission_started"
            snapshot = workspace.submit(case["titulo"], case["descripcion"], str(uuid4()), token)
        result["stage"] = "primary_observation_saved"
        report = snapshot["report"]
        result.update(report_id=report["id"], observation_run=snapshot["run_id"],
            primary={"provider": report["input"]["provider"], "model": report["input"]["model"],
                     "model_scope": report["input"]["model_scope"], "trace": report["input"]["trace"],
                     "classification": report["classification"], "review": report["review_reason"], "timing": report["timing"]})
        persisted = db.report(report["id"])
        policy = report["routing"]["configuration"]
        receipt = client.get(f"/api/reportes/{report['id']}").raise_for_status().json()
        lifecycle_result = lifecycle(client, db, receipt, policy, "n8n")
        if lifecycle_result["status"] != "routed" or report["origin"] != "langflow":
            raise AnalyticsError("El flujo aislado no confirmó una clasificación cloud y los cuatro hitos del Caso 06.")
        if report["input"]["provider"] != "groq" or not report["routing"]["verified"]:
            raise AnalyticsError("La respuesta primaria o los SLA no coinciden con la comprobación solicitada.")
        payload = {field: case[field] for field in ("titulo", "descripcion")}
        if any(persisted[field] != value for field, value in payload.items()):
            raise AnalyticsError("Cambió la entrada original del caso aislado.")
        if resume:
            conflict = client.post(settings.api.endpoints.reports, json=payload,
                                   headers={"Authorization": "Bearer " + token.get_secret_value(), "Idempotency-Key": report["id"]})
            if conflict.status_code != 409:
                raise AnalyticsError("La idempotencia permitió reutilizar el identificador de otro actor.")
            result["idempotency_evidence"] = "409 al reutilizar el identificador desde otro actor JWT; mismo actor cubierto por pruebas automatizadas"
        else:
            duplicate = adapter.submit_report(payload, report["id"], token, settings.inference.request_timeout_seconds)
            if duplicate["id"] != report["id"]:
                raise AnalyticsError("La comprobación de idempotencia falló.")
            result["idempotency_evidence"] = "Repetición por el mismo actor con un solo registro"
        blocked = {}
        for operation, sql in (("UPDATE", "UPDATE audit_log SET action='probe' WHERE 1=0"),
                               ("DELETE", "DELETE FROM audit_log WHERE 1=0"), ("TRUNCATE", "TRUNCATE audit_log")):
            try:
                with db.session(write=True) as execute:
                    execute(sql)
            except SQLAlchemyError as error:
                blocked[operation] = "audit_log es inmutable" in str(error)
            else:
                blocked[operation] = False
        if not all(blocked.values()):
            raise AnalyticsError("La auditoría aislada no bloqueó todas las mutaciones ensayadas.")
        aggregates = workspace.metrics(token)
        result.update(primary={"provider": report["input"]["provider"], "model": report["input"]["model"],
                               "model_scope": report["input"]["model_scope"], "trace": report["input"]["trace"],
                               "classification": report["classification"], "review": report["review_reason"],
                               "timing": report["timing"]},
            runtime=metadata["mode"], postgres_version=metadata["postgresql_version"],
            n8n_version=metadata["n8n_version"], report_id=report["id"], observation_run=snapshot["run_id"],
            counts=lifecycle_result["db_counts"], events=report["events"], sla_valid=report["routing"]["verified"],
            idempotency_valid=True, immutable_audit=blocked, original_preserved=True, aggregates=aggregates)
    protected = protect_text(text, known_secrets=connection.operational.privacy_secrets())
    result["stage"] = "fallback_probe_started"
    graph = connection.fetch()
    payload = {"input_value": f"<reporte>\n{escape(protected.text, quote=False)}\n</reporte>",
               "input_type": "chat", "output_type": "chat", "session_id": str(uuid4()),
               "tweaks": {cloud_node(graph)["id"]: {"groq_model": settings.flow_validation.invalid_primary_model}}}
    reply = connection.run_once(payload)["outputs"][0]["outputs"][0]["results"]["message"]
    classification = Classification.model_validate_json(reply["text"])
    observed = reply.get("session_metadata", {})
    trace = valid_trace(observed)
    if (observed.get("soc_provider") != "gemini" or not trace or not trace["technical_fallback"] or
            trace["outcome"] != "classified"):
        raise AnalyticsError("La prueba de fallback técnico no confirmó una respuesta válida de Gemini.")
    result["fallback"] = {"provider": observed["soc_provider"], "model": observed.get("soc_model"),
                          "model_scope": observed.get("soc_model_scope"), "trace": trace,
                          "classification": classification.model_dump(), "request_only_invalid_groq_model": True}
    result["graph_unchanged_by_probes"] = graph_digest(connection.fetch()) == graph_before
    result["pilot_unchanged"] = path.read_bytes() == original_bytes
    if not result["graph_unchanged_by_probes"] or not result["pilot_unchanged"]:
        raise AnalyticsError("Cambió un original durante las comprobaciones.")
    result.update(status="passed", stage="complete", limitations="Dos solicitudes del mismo caso autorizado. No estima exactitud, calibración "
                  "ni un p95 poblacional. El p95 del SPEC conserva pendiente su campaña representativa.")
    return result


def main() -> int:
    """Keep cloud execution explicitly opt-in and record failures without upstream bodies."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sync-component", action="store_true")
    parser.add_argument("--live", action="store_true")
    parser.add_argument("--approved-input-sha256", default="")
    parser.add_argument("--runtime", choices=("docker", "native"), default="docker")
    parser.add_argument("--resume-stack")
    parser.add_argument("--resume-project")
    parser.add_argument("--resume-report")
    args = parser.parse_args()
    settings = load_config()
    directory = settings.path(Path(settings.runs_dir) / settings.inference.directory / "verification" /
                              (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_live_" + uuid4().hex[:8]))
    directory.mkdir(parents=True, exist_ok=False)
    result = {"phase": 6, "generated_at_utc": datetime.now(timezone.utc).isoformat(), "status": "running"}
    try:
        connection = LangflowConformance(settings, Settings.from_env())
        result["graph"] = component_sync(connection, settings) if args.sync_component else connection.check()
        if args.live:
            resume = None
            if any((args.resume_stack, args.resume_project, args.resume_report)):
                if not all((args.resume_stack, args.resume_project, args.resume_report)):
                    raise AnalyticsError("La reanudación requiere directorio, proyecto aislado e identificador del reporte.")
                candidate = settings.path(args.resume_stack)
                allowed = settings.path(Path(settings.runs_dir) / settings.inference.directory / "verification")
                if (args.runtime != "docker" or not candidate.is_relative_to(allowed) or candidate.name != "isolated-stack" or
                        not (candidate / "compose.env").is_file() or not re.fullmatch(r"soc-phase6-[a-f0-9]{12}", args.resume_project)):
                    raise AnalyticsError("La reanudación solo admite un proyecto Docker de verificación de Fase 6.")
                resume = {"directory": candidate, "project": args.resume_project, "report": str(UUID(args.resume_report))}
            result["live"] = {}
            live_check(settings, connection, directory, args.approved_input_sha256, args.runtime, result["live"], resume)
        result["status"] = "passed"
        return 0
    except Exception as error:
        result.update(status="failed", error_type=type(error).__name__)
        result["error_locations"] = [{"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                                     for frame in extract_tb(error.__traceback__)[-5:]]
        if isinstance(error, AnalyticsError):
            result["safe_reason"] = str(error)
        if result.get("live", {}).get("status") == "running":
            result["live"]["status"] = "incomplete"
        print("La verificación quedó incompleta. Revisa el entorno y la evidencia técnica local, sin repetir solicitudes cloud automáticamente.")
        return 1
    finally:
        result["content_sha256"] = content_hash(result)
        target = directory / "verification.json"
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(str(target))


if __name__ == "__main__":
    raise SystemExit(main())
