"""Conformance checks for export bindings and auditable analytical actions."""
from copy import deepcopy
from hashlib import sha256
import json
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr
import pytest

from backend.config import Settings
from backend.db import utc_now
from backend.main import create_app
from backend.security import hash_password
from src.data.catalog import DatasetCatalog
from src.inference.services import SocApi, User
from src.training.experiments import RunRegistry
from src.utils.errors import AnalyticsError, ServiceError
from src.utils.langflow import LangflowConformance, graph_contract, graph_digest
from src.utils.config import load_config


def graph_fixture(settings):
    params = settings.flow_validation
    template = {"code": {"value": settings.path(params.component_file).read_text(encoding="utf-8")},
                "groq_model": {"value": params.expected_groq_model}, "gemini_model": {"value": params.expected_gemini_model},
                "groq_api_key": {"value": "", "load_from_db": False}, "gemini_api_key": {"value": "", "load_from_db": False}}
    nodes = [{"id": kind, "data": {"type": kind, "node": {"template": {}}}}
             for kind in ("ChatInput", "Prompt", "SocCloudModel", "ChatOutput")]
    nodes[1]["data"]["node"]["template"] = {"template": {"value": settings.path(params.prompt_file).read_text(encoding="utf-8")}}
    nodes[2]["data"]["node"]["template"] = template
    return {"nodes": nodes, "edges": [{"source": a, "target": b} for a, b in
            (("ChatInput", "SocCloudModel"), ("Prompt", "SocCloudModel"), ("SocCloudModel", "ChatOutput"))]}


def test_versioned_export_conforms_to_cloud_component_and_prompt_without_local_providers():
    settings = load_config()
    text = settings.path(settings.flow_validation.export_file).read_text(encoding="utf-8-sig")
    details = graph_contract(json.loads(text)["data"], settings)
    assert details["credential_references_valid"]
    assert "ollama" not in text.lower() and "qwen" not in text.lower()


def test_sync_corrects_references_and_exports_identical_graph_without_changing_models(settings):
    graph = graph_fixture(settings)
    original = deepcopy(graph)
    original.pop("id", None)
    def respond(request):
        nonlocal graph
        assert request.headers["x-api-key"] == "test-langflow-key"
        if request.url.path.endswith("/variables/"):
            return httpx.Response(200, json=[{"name": name, "type": "Credential"} for name in ("GROQ_API_KEY", "GEMINI_API_KEY")])
        if request.method == "PATCH":
            graph = json.loads(request.content)["data"]
        return httpx.Response(200, json={"data": graph})
    operational = Settings(classifier_mode="langflow", langflow_flow_id="test-flow", langflow_api_key="test-langflow-key", operator_token="test-operator")
    connection = LangflowConformance(settings, operational, transport=httpx.MockTransport(respond))
    assert not connection.check()["credential_references_valid"]
    result = connection.synchronize()
    assert result["credential_references_valid"] and result["export_matches_runtime"]
    exported = settings.path(settings.flow_validation.export_file).read_text(encoding="utf-8")
    assert "test-langflow-key" not in exported and "ollama" not in exported.lower()
    assert graph_digest(json.loads(exported)["data"]) == graph_digest(graph)
    assert not connection.synchronize()["credential_bindings_corrected"]
    modified = deepcopy(graph)
    modified["nodes"][2]["data"]["node"]["template"]["groq_model"]["value"] = "different-model"
    with pytest.raises(AnalyticsError):
        graph_contract(modified, settings)


def test_backend_audit_enforces_roles_and_preserves_actor_identity(settings, tmp_path):
    app = create_app(Settings(sqlite_path=tmp_path / "audit.sqlite3", operator_token="test-operator",
                              legacy_operator_enabled=False, jwt_secret="test-jwt-independent-secret-longer-than-32-characters"))
    with TestClient(app) as server:
        encoded = hash_password("test-password")
        users = {}
        with app.state.db.session(write=True) as execute:
            for role in ("administrador", "analista", "gestor", "auditor", "solicitante"):
                users[role] = str(uuid4())
                execute("INSERT INTO users (id,username,password_hash,role,creado_at) VALUES (%s,%s,%s,%s,%s)",
                        (users[role], role, encoded, role, utc_now()))
        for role in users:
            token = server.post("/api/auth/login", json={"username": role, "password": "test-password"}).json()["access_token"]
            headers = {"Authorization": "Bearer " + token}
            response = server.post("/api/analitica/eventos", headers=headers, json={"action": "consultar_catalogo"})
            assert response.status_code == (204 if role in ("administrador", "analista", "gestor") else 403)
            response = server.post("/api/analitica/eventos", headers=headers,
                json={"action": "registrar_verificacion", "source_id": "vcdb_pilot", "outcome": "iniciado"})
            assert response.status_code == (204 if role in ("administrador", "analista") else 403)
            response = server.post("/api/analitica/eventos", headers=headers,
                json={"action": "consultar_catalogo", "user_id": "spoofed-user"})
            assert response.status_code == 422
        with app.state.db.session() as execute:
            rows = [dict(row) for row in execute("SELECT user_id,role,action FROM audit_log WHERE module LIKE 'analitica/%'")]
        assert len(rows) == 5
        assert all(row["user_id"] == users[row["role"]] for row in rows)


def test_failed_completion_audit_leaves_record_pending(settings, api, monkeypatch):
    catalog = DatasetCatalog(settings, api)
    snapshot = {"source_id": "vcdb_pilot", "sha256": sha256(b"fixture").hexdigest(), "hash_scope": "fixture", "rows": []}
    def fail_completion(token, action, **kwargs):
        if kwargs.get("outcome", "completado") == "completado":
            raise ServiceError("Auditoría no disponible")
    monkeypatch.setattr(api, "audit_event", fail_completion)
    registry = RunRegistry(settings)
    with pytest.raises(ServiceError):
        registry.record_source_validation(catalog, snapshot, SecretStr("private-test-token"))
    assert registry.records()[0]["audit_state"] == "pendiente"


def test_manager_cannot_create_a_validation_even_with_a_readable_catalog(settings, api, monkeypatch):
    monkeypatch.setattr(api, "me", lambda token: User(id="manager", username="gestor", role="gestor", active=1))
    catalog = DatasetCatalog(settings, api)
    with pytest.raises(AnalyticsError, match="rol"):
        RunRegistry(settings).record_source_validation(catalog, {}, SecretStr("private-test-token"))


def test_dataset_preview_is_not_returned_if_backend_audit_fails(settings, api, monkeypatch):
    monkeypatch.setattr(api, "audit_event", lambda *args, **kwargs: (_ for _ in ()).throw(ServiceError("Auditoría no disponible")))
    with pytest.raises(ServiceError):
        DatasetCatalog(settings, api).preview("operational_reports", token=SecretStr("private-test-token"))
