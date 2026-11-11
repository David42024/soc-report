"""Populate Streamlit using actual local synthetic runs, never invented activity."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from uuid import NAMESPACE_URL, uuid5

# Native exporters initialize during import, so configure their local fonts first.
_project_root = Path(__file__).resolve().parents[1]
os.environ.setdefault("WEASYPRINT_DLL_DIRECTORIES", "C:/Program Files/Tesseract-OCR")
_font_file = _project_root / ".venv/soc-runtime/fonts.conf"
if _font_file.is_file():
    os.environ["FONTCONFIG_FILE"] = _font_file.as_posix()

from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr

from backend.config import Settings
from backend.main import create_app
from backend.manage import seed_history, seed_lock
from src.data.catalog import DatasetCatalog
from src.data.demo import generated_cases
from src.data.workspace import DataWorkspace
from src.evaluation.workspace import EvaluationWorkspace
from src.explainability.workspace import ExplanationWorkspace
from src.inference.services import SocApi
from src.inference.workspace import InferenceWorkspace
from src.optimization.contracts import SearchOptions
from src.optimization.workspace import OptimizationWorkspace, default_options
from src.reports.scientific import ReportRequest, TEMPLATES
from src.reports.workspace import ReportingWorkspace
from src.training.experiments import RunRegistry
from src.training.jobs import ExperimentManager
from src.training.runs import JobSpec
from src.utils.config import load_config
from src.utils.logging import configure_logging


def now():
    return datetime.now(timezone.utc).isoformat()


class Seeder:
    def __init__(self, args):
        self.args = args
        self.settings = load_config()
        configure_logging(self.settings)
        self.directory = self.settings.path(Path(self.settings.runs_dir) / "demo_activity" / args.batch)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.path = self.directory / "progress.json"
        self.state = json.loads(self.path.read_bytes()) if self.path.is_file() else {
            "batch": args.batch, "synthetic": True, "started_at_utc": now(), "cloud_calls": 0,
            "cases": [], "inferences": [], "operational_explanations": [], "manifests": [],
            "validations": [], "trainings": [], "optimizations": [], "evaluations": [],
            "explanations": [], "reports": [], "comparisons": [], "original_fingerprints": self.originals(),
        }
        accounts = json.loads(self.settings.path(".venv/soc-runtime/access.json").read_bytes())
        self.account = next(item for item in accounts if item["username"] == "administrador")
        self.state.setdefault("comparisons", [])

    def originals(self):
        registry = DatasetCatalog(self.settings, SocApi(self.settings.api))
        paths = [self.settings.path(source.path) for source in registry.sources.values() if source.path]
        paths += [self.settings.path(self.settings.data.sealed_holdout_file), self.settings.root / ".env"]
        return {path.relative_to(self.settings.root).as_posix(): sha256(path.read_bytes()).hexdigest()
                if path.is_file() else None for path in paths}

    def save(self, message):
        self.state["updated_at_utc"] = now()
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.path)
        print(message, flush=True)

    def operational(self):
        # This in-process API uses the existing database, users, routing and audit.
        # Only this private seeding client selects demo/local; production configuration stays intact.
        config = Settings.from_env().model_copy(update={"classifier_mode": "demo", "router_mode": "local",
            "redis_url": "", "report_limit": max(200, self.args.cases + 10)})
        app = create_app(config)
        with TestClient(app) as server:
            def forward(request):
                response = server.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
                return httpx.Response(response.status_code, content=response.content, headers=response.headers)

            api = SocApi(self.settings.api, transport=httpx.MockTransport(forward))
            session = api.login(self.account["username"], SecretStr(self.account["password"]))
            token = session.token
            headers = {"Authorization": "Bearer " + token.get_secret_value()}
            inference = InferenceWorkspace(self.settings, api)
            explanations = ExplanationWorkspace(self.settings, api)
            cases = generated_cases(self.settings.seed)
            # Take all type/severity combinations rather than the first contiguous type.
            ordered = sorted(cases, key=lambda item: sha256((self.args.batch + item["id"]).encode()).hexdigest())
            try:
                for index in range(len(self.state["cases"]), self.args.cases):
                    case = ordered[index % len(ordered)]
                    identifier = str(uuid5(NAMESPACE_URL, f"soc-streamlit-demo/{self.args.batch}/{index}"))
                    kind = case["tipo"].replace("_", " ")
                    title = f"[DEMO] Actividad {index + 1:03d}: {kind}"
                    description = f"Activo: {case['activo_afectado']}\n{case['descripcion']}\nCategoría del ejercicio: {kind}."
                    if index < min(30, self.args.cases):
                        result = inference.submit(title, description, identifier, token)
                        self.state["inferences"].append(result["run_id"])
                    else:
                        api.submit_report({"titulo": title, "descripcion": description}, identifier, token,
                                          self.settings.inference.request_timeout_seconds)
                    current = server.get(f"/api/reportes/{identifier}", headers=headers).raise_for_status().json()
                    if index % 3 and not current["respondido_at"]:
                        server.post(f"/api/reportes/{identifier}/responder", headers=headers).raise_for_status()
                    if index % 3 == 2 and not current["resuelto_at"]:
                        server.post(f"/api/reportes/{identifier}/resolver", headers=headers).raise_for_status()
                    collaboration = server.get(f"/api/reportes/{identifier}/colaboracion", headers=headers).raise_for_status().json()
                    note = "Actividad sintética del seeder de Streamlit; atención simulada, sin revisión humana de referencia."
                    if not any(item["contenido"] == note for item in collaboration["comentarios"]):
                        server.post(f"/api/reportes/{identifier}/comentarios", headers=headers,
                                    json={"contenido": note}).raise_for_status()
                    if index < min(15, self.args.cases):
                        self.state["operational_explanations"].append(explanations.operational(identifier, token)["run_id"])
                    self.state["cases"].append(identifier)
                    self.save(f"Reportes DEMO: {index + 1}/{self.args.cases}")
            finally:
                api.logout(token)
        if not self.state.get("history_seeded"):
            seed_history()
            self.state["history_seeded"] = True
            self.save("Histórico DEMO separado preparado.")

    def data(self, api, token):
        for index in range(len(self.state["manifests"]), self.args.manifests):
            settings = self.settings.model_copy(update={"seed": self.settings.seed + index})
            workspace = DataWorkspace(DatasetCatalog(settings, api))
            view = workspace.open_demo(token)
            if index == 0:
                for record in view.inventory.records()[:20]:
                    if record.notes and record.notes.startswith("Preparación automática de caso sintético"):
                        continue
                    workspace.save_revision(view, record.key,
                        {"observaciones": "Preparación automática de caso sintético para demostración; etiquetas generadas, sin referencia humana."},
                        record.version, True, token)
                view = workspace.refresh_revisions(view.original, token)
            saved = workspace.save_manifest(view, token)
            self.state["manifests"].append(saved["run_id"])
            self.save(f"Manifiestos sintéticos: {index + 1}/{self.args.manifests}")
        catalog = DatasetCatalog(self.settings, api)
        registry = RunRegistry(self.settings)
        sources = list(catalog.sources)
        for index in range(len(self.state["validations"]), self.args.validations):
            source = sources[index % len(sources)]
            result = registry.record_source_validation(catalog, catalog.preview(source, token=token), token)
            self.state["validations"].append(result["run_id"])
            self.save(f"Verificaciones auténticas: {index + 1}/{self.args.validations} · {source}")

    def experiments(self, api, token):
        manager = ExperimentManager(self.settings, api)
        optimizer = OptimizationWorkspace(manager)
        evaluator = EvaluationWorkspace(self.settings, api, manager.store)
        explainer = ExplanationWorkspace(self.settings, api, manager.store)
        try:
            for advanced, total in ((False, self.args.trainings), (True, self.args.optimizations)):
                key = "optimizations" if advanced else "trainings"
                for index in range(len(self.state[key]), total):
                    seed = 1000 + index + (100 if advanced else 0)
                    local = self.settings.training.local.model_copy(update={"c": (0.1, 1.0, 10.0)[index % 3],
                        "ngram_max": 1 + index % 2, "balanced": index % 2 == 0})
                    options = None
                    if advanced:
                        raw = default_options(self.settings).model_dump(mode="json")
                        raw.update(sampler="tpe" if index % 2 == 0 else "random", timeout_seconds=600,
                                   space={"c": {"kind": "float", "low": 0.0001, "high": 10.0, "log": True},
                                          "max_df": {"kind": "categorical", "choices": [0.5, 1.0]},
                                          "max_features": {"kind": "categorical", "choices": [40, 200, 1000]},
                                          "ngram_max": {"kind": "categorical", "choices": [1, 2]}})
                        options = SearchOptions.model_validate(raw)
                    spec = JobSpec(source="sintetico", target="tipo", seed=seed,
                        trials=self.args.opt_trials if advanced else self.args.trials,
                        models=("tfidf_logreg",) if advanced else ("tfidf_logreg", "tfidf_svm"), local=local,
                        optimization=options)
                    configuration = optimizer.save_configuration(spec, token)["version"] if advanced else None
                    preview = manager.preview(spec, token)
                    run_id = manager.start(spec, token, preview["plan_sha256"])
                    self.save(f"Ejecutando {key} {index + 1}/{total}: {run_id}")
                    result = manager._running[run_id].result(timeout=1800)
                    if not result:
                        raise RuntimeError(f"La corrida {run_id} terminó con error; consulta state.json.")
                    if result["flow_calls"] != 0:
                        raise RuntimeError("Una corrida sintética registró llamadas externas inesperadas.")
                    entry = {"run_id": run_id, "seed": seed, "families": list(result["families"]),
                             "actual_trials": sum(len(fold["trials"]) for family in result["families"].values() for fold in family["folds"])}
                    if advanced:
                        entry.update(configuration=configuration, candidate=optimizer.candidate(run_id, token)["version"])
                    self.state[key].append(entry)
                    self.save(f"Completado {key}: {index + 1}/{total} · {entry['actual_trials']} trials medidos")
            all_runs = self.state["trainings"] + self.state["optimizations"]
            done_evaluations = {(row["run"], row["family"]) for row in self.state["evaluations"]}
            done_explanations = {(row["run"], row["family"]) for row in self.state["explanations"]}
            for entry in all_runs:
                for family in entry["families"]:
                    key = entry["run_id"], family
                    if key not in done_evaluations:
                        report = evaluator.evaluate(*key, token)
                        self.state["evaluations"].append({"run": key[0], "family": family, "run_id": report["run_id"]})
                        self.save(f"Evaluaciones reales sobre casos sintéticos: {len(self.state['evaluations'])}")
                    if key not in done_explanations:
                        report = explainer.local(*key, "validation", token)
                        self.state["explanations"].append({"run": key[0], "family": family, "run_id": report["run_id"]})
                        self.save(f"Análisis de explicabilidad: {len(self.state['explanations'])}")
                if len(entry["families"]) > 1 and not any(row["run"] == entry["run_id"] for row in self.state["comparisons"]):
                    evaluated = next(row["run_id"] for row in self.state["evaluations"] if row["run"] == entry["run_id"])
                    comparison = evaluator.comparison(evaluated, token)
                    self.state["comparisons"].append({"run": entry["run_id"], "run_id": comparison["run_id"]})
                    self.save(f"Comparaciones estadísticas: {len(self.state['comparisons'])}")
        finally:
            manager.close()

    def reports(self, api, token):
        workspace = ReportingWorkspace(self.settings, api)
        templates = tuple(TEMPLATES)
        runs = self.state["trainings"] + self.state["optimizations"]
        for index in range(len(self.state["reports"]), self.args.reports):
            template = templates[index % len(templates)]
            request = ReportRequest(template=template, sections=TEMPLATES[template].sections,
                manifest=self.state["manifests"][index % len(self.state["manifests"])],
                experiments=tuple(row["run_id"] for row in runs[index % len(runs):index % len(runs) + 2]),
                evaluations=tuple(row["run_id"] for row in self.state["evaluations"][index:index + 2]),
                explanations=tuple(row["run_id"] for row in self.state["explanations"][index:index + 2]))
            snapshot = workspace.compose(request, token)
            result = workspace.publish(snapshot, token)
            self.state["reports"].append({"run_id": result["run_id"], "template": template,
                                          "outputs": [output.filename for output in result["outputs"]]})
            self.save(f"Informes publicados: {index + 1}/{self.args.reports} · {template}")

    def run(self):
        if self.originals() != self.state["original_fingerprints"]:
            raise RuntimeError("Cambió un dataset original o la configuración desde el inicio del lote. Revisa antes de continuar.")
        self.operational()
        api = SocApi(self.settings.api)
        session = api.login(self.account["username"], SecretStr(self.account["password"]))
        try:
            self.data(api, session.token)
            self.experiments(api, session.token)
            self.reports(api, session.token)
        finally:
            api.logout(session.token)
        if self.originals() != self.state["original_fingerprints"]:
            raise RuntimeError("La huella final de un original cambió.")
        self.state["completed_at_utc"] = now()
        self.state["originals_unchanged"] = True
        self.state["counts"] = {key: len(self.state[key]) for key in ("cases", "inferences", "manifests", "validations",
            "trainings", "optimizations", "evaluations", "explanations", "comparisons", "operational_explanations", "reports")}
        for key in ("evaluations", "explanations", "comparisons"):
            self.state["counts"][key] = len({row["run_id"] for row in self.state[key]})
        self.state["counts"]["actual_trials"] = sum(row["actual_trials"] for row in self.state["trainings"] + self.state["optimizations"])
        self.save(json.dumps(self.state["counts"], ensure_ascii=False))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", default="streamlit-demo-v1")
    for name, default in (("cases", 120), ("trainings", 12), ("optimizations", 8), ("manifests", 6),
                          ("validations", 24), ("reports", 9), ("trials", 5), ("opt-trials", 12)):
        parser.add_argument("--" + name, type=int, default=default)
    args = parser.parse_args()
    if not re.fullmatch(r"[a-z0-9_-]{1,60}", args.batch) or any(value < 1 for key, value in vars(args).items() if key != "batch"):
        parser.error("Usa un nombre de lote simple y cantidades positivas.")
    os.environ.setdefault("WEASYPRINT_DLL_DIRECTORIES", "C:/Program Files/Tesseract-OCR")
    fonts = load_config().root / ".venv/soc-runtime/fonts.conf"
    if fonts.is_file():
        os.environ["FONTCONFIG_FILE"] = fonts.as_posix()
    with seed_lock():
        Seeder(args).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
