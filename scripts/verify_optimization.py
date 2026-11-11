"""Generate auditable Phase 7 examples through FastAPI/JWT and the Phase 2 engine."""
from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from secrets import token_urlsafe
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr

from backend.config import Settings
from backend.db import utc_now
from backend.main import create_app
from backend.security import hash_password
from src.data.models import content_hash
from src.optimization.workspace import OptimizationWorkspace, default_options
from src.reports.figures import export_png
from src.reports.optimization_presentation import (
    contour_plot, distribution_plot, history_plot, importance_plot, parallel_plot, slice_plot, stability_plot,
    space_table, stability_table, trials_table, winners_table,
)
from src.inference.services import SocApi
from src.training.jobs import ExperimentManager
from src.training.runs import JobSpec
from src.utils.config import load_config


def production_fingerprints(root: Path) -> dict[str, str]:
    """Hash the operational policy/credentials without writing or printing their values."""
    names = (".env", "config/privacy.yaml", "integrations/reglas.json", "integrations/n8n/assign_report.json",
             "integrations/langflow/prompt.txt", "integrations/langflow/cloud_classifier_model.py",
             "integrations/langflow/cybersecurity_classifier.json", "compose.yaml")
    return {name: sha256((root / name).read_bytes()).hexdigest() for name in names}


def main() -> int:
    """Use synthetic text only; cloud requests and sealed-Test access are impossible here."""
    settings = load_config()
    directory = settings.path(Path(settings.runs_dir) / settings.optimization.directory / "verification" /
                              (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "_integration_" + uuid4().hex[:8]))
    directory.mkdir(parents=True, exist_ok=False)
    before = production_fingerprints(settings.root)
    result = {"phase": 7, "created_at_utc": datetime.now(timezone.utc).isoformat(), "status": "running",
              "source": "sintetico", "api": "FastAPI real en proceso con SQLite aislado y JWT", "cloud_calls": 0}
    app = create_app(Settings(sqlite_path=directory / "api.sqlite3", legacy_operator_enabled=False,
                              jwt_secret=token_urlsafe(48), operator_token=token_urlsafe(32)))
    try:
        with TestClient(app) as server:
            password = token_urlsafe(32)
            with app.state.db.session(write=True) as execute:
                execute("INSERT INTO users(id,username,password_hash,role,creado_at) VALUES(%s,%s,%s,%s,%s)",
                        (str(uuid4()), "phase7-validator", hash_password(password), "analista", utc_now()))

            def forward(request: httpx.Request) -> httpx.Response:
                response = server.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
                return httpx.Response(response.status_code, content=response.content, headers=response.headers)

            api = SocApi(settings.api, transport=httpx.MockTransport(forward))
            session = api.login("phase7-validator", SecretStr(password))
            manager = ExperimentManager(settings, api)
            try:
                workspace = OptimizationWorkspace(manager)
                options = default_options(settings).model_copy(update={"timeout_seconds": settings.optimization.max_timeout_seconds})
                spec = JobSpec(source="sintetico", target="tipo", seed=settings.seed, trials=settings.optimization.default_trials,
                               models=("tfidf_logreg",), local=settings.training.local, optimization=options)
                configuration = workspace.save_configuration(spec, session.token)
                preview = manager.preview(spec, session.token)
                identifier = manager.start(spec, session.token, preview["plan_sha256"])
                report = manager._running[identifier].result(timeout=settings.optimization.max_timeout_seconds)
                if not report:
                    raise RuntimeError("El trabajo sintético no completó el protocolo.")
                snapshot = workspace.inspect(identifier, session.token)
                candidate = workspace.candidate(identifier, session.token)
                recovered = workspace.load_candidate(candidate["version"], session.token)
                assert recovered == candidate
                family = report["families"]["tfidf_logreg"]
                # Pick by applicability for illustration, never by favorable outer performance.
                study = next((item for item in snapshot["studies"] if len({t["score"] for t in item["trials"] if t["state"] == "COMPLETE"}) > 1), snapshot["studies"][0])
                figures = []
                for function in (history_plot, importance_plot, parallel_plot, slice_plot, contour_plot, distribution_plot):
                    figure, guide = function(study, options, settings)
                    name = function.__name__ + ".png"
                    if figure is not None:
                        (directory / name).write_bytes(export_png(figure, settings.figures))
                    figures.append({"name": name if figure else None, "applies": figure is not None, "guide": guide.__dict__})
                figure, guide = stability_plot(family, options, settings, source=spec.source)
                (directory / "stability.png").write_bytes(export_png(figure, settings.figures))
                figures.append({"name": "stability.png", "applies": True, "guide": guide.__dict__})
                tables = [{"rows": rows, "guide": guide.__dict__} for rows, guide in
                          (space_table(options), trials_table(study, options.metric), winners_table(family), stability_table(family, options))]
                (directory / "search.yaml").write_bytes(workspace.serialize(spec))
                (directory / "candidate.json").write_text(json.dumps(candidate, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                (directory / "trials.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
                with app.state.db.session() as execute:
                    actions = {row["action"] for row in execute("SELECT action FROM audit_log WHERE module IN ('analitica/optimizacion','analitica/experimentos')")}
                total = sum(len(fold["trials"]) for fold in family["folds"])
                assert total >= 10 and report["test_evaluations"] == report["flow_calls"] == 0
                assert len(family["folds"]) == 5 and all(fold["outer_evaluations"] == 1 and len(fold["inner"]) == 3 for fold in family["folds"])
                assert {"autorizar_experimento", "guardar_configuracion_optuna", "exportar_candidato_optuna"} <= actions
                result.update(status="passed", phase2_run=identifier, configuration_version=configuration["version"],
                    candidate_version=candidate["version"], partition_sha256=report["partition_sha256"], dataset_sha256=report["partition"]["source_sha256"],
                    trials=total, folds=5, trials_per_fold=spec.trials, test_evaluations=0,
                    states={name: sum(t["state"] == name for s in snapshot["studies"] for t in s["trials"]) for name in ("COMPLETE", "PRUNED", "FAIL")},
                    seconds=report["elapsed_seconds"], external_f1=family["summary"],
                    inner_objectives=sorted({t["score"] for s in snapshot["studies"] for t in s["trials"] if t["state"] == "COMPLETE"}),
                    selected_parameters=family["validation_selection"]["winner"]["configuration"],
                    figures=figures, tables=tables, actions=sorted(actions), production_before=before,
                    limitations="Prueba técnica sintética. Los resultados no acreditan calidad real, significancia ni causalidad. La candidata no se despliega.")
            finally:
                manager.close()
                api.logout(session.token)
        result["production_unchanged"] = production_fingerprints(settings.root) == before
        if not result["production_unchanged"]:
            raise RuntimeError("Cambió una fuente operacional durante la comprobación.")
        return 0
    except Exception as error:
        result.update(status="failed", safe_error_type=type(error).__name__)
        return 1
    finally:
        result["content_sha256"] = content_hash(result)
        target = directory / "verification.json"
        target.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        print(str(target))
        print(json.dumps({k: result.get(k) for k in ("status", "phase2_run", "trials", "seconds", "production_unchanged")}))


if __name__ == "__main__":
    raise SystemExit(main())
