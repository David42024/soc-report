"""Isolated analytical fixtures; never write to original dataset files."""
import csv
import json
from pathlib import Path
from shutil import copyfile, copytree
from uuid import UUID

import httpx
from pydantic import SecretStr
import pytest
import yaml

from src.data.catalog import DatasetCatalog
from src.data.workspace import DataWorkspace
from src.inference.services import SocApi
from src.utils.config import PROJECT_ROOT, load_config


@pytest.fixture
def settings(tmp_path):
    (tmp_path / "config").mkdir()
    for name in ("analytics.yaml", "datasets.yaml"):
        copyfile(PROJECT_ROOT / "config" / name, tmp_path / "config" / name)
    copytree(PROJECT_ROOT / "config/prompts", tmp_path / "config/prompts")
    (tmp_path / "integrations/langflow").mkdir(parents=True)
    for name in ("cloud_classifier_model.py", "prompt.txt"):
        copyfile(PROJECT_ROOT / "integrations/langflow" / name, tmp_path / "integrations/langflow" / name)
    return load_config(tmp_path, environment={})


@pytest.fixture
def api(settings):
    def respond(request):
        if request.url.path.endswith("/analitica/eventos"):
            return httpx.Response(204 if request.headers.get("Authorization") == "Bearer private-test-token" else 401)
        if request.url.path.endswith("/me"):
            if request.headers.get("Authorization") != "Bearer private-test-token":
                return httpx.Response(401, json={"detail": "secret upstream message"})
            return httpx.Response(200, json={"id": "analyst", "username": "analista", "role": "analista", "active": 1})
        if request.url.path.endswith("/reportes"):
            return httpx.Response(200, json=[{"id": "case-1", "tipo": "phishing", "severidad": "media", "confianza": 0.7,
                                             "activo_afectado": None, "origen": "langflow", "descripcion": "private report text"}])
        if request.url.path.endswith("/health"):
            return httpx.Response(200, json={"estado": "ok", "servicios": {"fastapi": "ok", "postgresql": "ok"}, "proveedores": {}})
        return httpx.Response(404)
    return SocApi(settings.api, transport=httpx.MockTransport(respond))


@pytest.fixture
def data_workspace(settings):
    """Use temporary copies of the contracts with fixture-only texts."""
    configured = yaml.safe_load((settings.root / "config/datasets.yaml").read_text(encoding="utf-8"))
    kinds = {"eurepoc", "article_simulation", "operational_reports"}
    configured["datasets"] = [entry for entry in configured["datasets"] if entry["id"] in kinds]
    paths = {}
    for entry in configured["datasets"]:
        if entry.get("path"):
            entry["path"] = Path(entry["path"]).name
            paths[entry["id"]] = settings.path(entry["path"])
    settings.path(settings.registry_file).write_text(yaml.safe_dump(configured), encoding="utf-8")
    with paths["eurepoc"].open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["incident_id", "name", "description", "incident_type", "weighted_intensity",
                         "initiator_country", "initiator_country", "source_url"])
        writer.writerow(["pub-1", "Interrupción de correo", "El servidor perdió acceso después de un correo a privado@example.test.",
                         "Phishing;Phishing;Malware", "3.5", "A", "B", "https://example.test/a;https://example.test/b"])
        for index in range(2, 14):
            writer.writerow([f"pub-{index}", "Caso de prueba", "Reporte de revisión del servicio y la red afectada.",
                             "Malware", index, "A", "B", "https://example.test/b" if index == 2 else ""])
        writer.writerow(["pub-2", "Fila repetida e incompleta"])
    paths["article_simulation"].write_text("synthetic_id,type_truth,severity_index,confidence_assumed\nsim-1,0,1,0.7\n", encoding="utf-8")
    real_id, demo_id = str(UUID(int=1)), str(UUID(int=2))
    report = {"id": real_id, "origen": "langflow", "titulo": "Acceso al servidor",
              "descripcion": "Una cuenta inició sesión en un servidor después de un correo.",
              "tipo": "phishing", "severidad": "media", "activo_afectado": "servidor", "confianza": .8}
    demo = {**report, "id": demo_id, "titulo": "[DEMO] Acceso al servidor", "severidad": "inventada"}
    state = {"role": "analista", "audit": [], "audit_ok": True}

    def respond(request):
        if request.headers.get("Authorization") != "Bearer private-test-token":
            return httpx.Response(401)
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"id": "actor-1", "username": "analista", "role": state["role"], "active": 1})
        if request.url.path.endswith("/analitica/eventos"):
            if not state["audit_ok"]:
                return httpx.Response(503)
            state["audit"].append(json.loads(request.content))
            return httpx.Response(204)
        if request.url.path.endswith("/reportes"):
            return httpx.Response(200, json=[report, demo])
        if request.url.path.endswith("/colaboracion"):
            review = ({"report_id": real_id, "tipo": "acceso_no_autorizado", "severidad": "alta",
                       "activo_afectado": "servidor", "reviewed_by": "revisor-operativo",
                       "reviewed_at": "2026-01-01T09:00:00-05:00"} if real_id in request.url.path else None)
            return httpx.Response(200, json={"revision": review})
        if request.url.path.endswith("/health"):
            return httpx.Response(200, json={"estado": "ok", "servicios": {"fastapi": "ok", "postgresql": "ok"}})
        return httpx.Response(404)

    client = SocApi(settings.api, transport=httpx.MockTransport(respond))
    return DataWorkspace(DatasetCatalog(settings, client)), SecretStr("private-test-token"), paths, state
