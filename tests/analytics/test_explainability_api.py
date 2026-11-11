"""Verify actual JWT/RBAC, protected request snapshots and unchanged predictions."""
import json
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr
import pytest

from backend.config import Settings
from backend.classifier import Classification
from backend.db import utc_now
from backend.main import create_app
from backend.report_input import ReportInput
from backend.security import hash_password
from src.explainability.workspace import ExplanationWorkspace
from src.inference.services import SocApi


@pytest.mark.parametrize("provider,confidence", [("groq", .91), ("gemini", .62)])
def test_capture_is_protected_authorized_and_separate_from_human_review(settings, tmp_path, provider, confidence):
    operational = Settings(sqlite_path=tmp_path / "xai-operational.sqlite3", classifier_mode="langflow",
        langflow_flow_id="fixture-flow", langflow_api_key="fixture-local-key", operator_token="fixture-operator",
        legacy_operator_enabled=False, jwt_secret="independent-xai-jwt-secret-longer-than-32-characters")
    app = create_app(operational)
    seen = []
    actual_client = httpx.Client
    model = "configured-groq-model" if provider == "groq" else "configured-gemini-model"

    def cloud(request):
        body = json.loads(request.content)
        seen.append(body)
        assert "alice@example.test" not in body["input_value"]
        answer = {"tipo": "phishing", "severidad": "media", "activo_afectado": "servidor", "confianza": confidence}
        message = {"text": json.dumps(answer), "session_metadata": {"soc_provider": provider, "soc_model": model,
                                                                    "soc_prompt_sha256": "a" * 64}}
        return httpx.Response(200, json={"outputs": [{"outputs": [{"results": {"message": message}}]}]})

    with TestClient(app) as server:
        password = hash_password("test-password")
        with app.state.db.session(write=True) as execute:
            for role in ("analista", "gestor", "auditor", "solicitante"):
                execute("INSERT INTO users (id,username,password_hash,role,creado_at) VALUES (%s,%s,%s,%s,%s)",
                        (str(uuid4()), role, password, role, utc_now()))
        tokens = {role: server.post("/api/auth/login", json={"username": role, "password": "test-password"}).json()["access_token"]
                  for role in ("analista", "gestor", "auditor", "solicitante")}
        headers = {"Authorization": "Bearer " + tokens["analista"], "Idempotency-Key": str(uuid4())}
        body = {"titulo": "Correo falso en un servidor", "descripcion": "Un correo falso dirigido a alice@example.test afectó al servidor con impacto limitado."}
        with patch("httpx.Client", side_effect=lambda **kw: actual_client(transport=httpx.MockTransport(cloud), **kw)):
            first = server.post("/api/reportes", headers=headers, json=body)
            assert first.status_code == 201
            assert server.post("/api/reportes", headers=headers, json=body).status_code == 200
        identifier = first.json()["id"]
        path = f"/api/reportes/{identifier}/explicabilidad"
        assert len(seen) == 1
        assert server.get(path).status_code == 401
        for role in ("gestor", "auditor", "solicitante"):
            assert server.get(path, headers={"Authorization": "Bearer " + tokens[role]}).status_code == 403
        protected = server.get(path, headers=headers).json()
        assert protected["input_status"] == "capturada"
        assert protected["input"]["provider"] == provider and protected["input"]["model"] == model
        assert "original" not in protected and "alice@example.test" not in json.dumps(protected)
        original = server.get(path + "?original=true", headers=headers).json()
        assert original["original"]["description"] == body["descripcion"]
        reviewed = {"tipo": "malware", "severidad": "alta", "activo_afectado": "servidor"}
        assert server.put(f"/api/reportes/{identifier}/revision", json=reviewed, headers=headers).status_code == 200
        detail = server.get(path, headers=headers).json()
        assert detail["classification"]["tipo"] == "phishing" and detail["human_review"]["tipo"] == "malware"

        def dispatch(request):
            response = server.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)

        api = SocApi(settings.api, transport=httpx.MockTransport(dispatch))
        workspace = ExplanationWorkspace(settings, api)
        token = SecretStr(tokens["analista"])
        result = workspace.operational(identifier, token)
        report = workspace.detail(result["run_id"], token)
        assert report["cases"][0]["correct"] is False
        assert all(item["exists"] for item in report["cases"][0]["evidence"]["original_quotes"])
        assert "alice@example.test" not in json.dumps(report)
        assert workspace.original(identifier, token)["description"] == body["descripcion"]
        with app.state.db.session() as execute:
            assert execute("SELECT count(*) AS n FROM report_ai_inputs WHERE report_id=%s", (identifier,)).fetchone()["n"] == 1
            assert execute("SELECT descripcion FROM reports WHERE id=%s", (identifier,)).fetchone()["descripcion"] == body["descripcion"]
            actions = {row["action"] for row in execute("SELECT action FROM audit_log WHERE entity_id=%s", (identifier,))}
        assert {"consultar_original", "consultar_entrada_ia"} <= actions
        legacy = Classification(tipo="otro", severidad="media", activo_afectado=None, confianza=0.0)
        for origin, expected_provider in (("langflow", "gemini"), ("fallback", None)):
            legacy_id = str(uuid4())
            legacy._provider = expected_provider
            app.state.db.save_report(legacy_id, ReportInput(**body), legacy, origin, "langflow_no_disponible", utc_now())
            old = server.get(f"/api/reportes/{legacy_id}/explicabilidad", headers=headers).json()
            assert old["input_status"] == "reconstruida" and old["input"]["provider"] == expected_provider
            assert old["input"]["model"] is None and old["input"]["prompt_sha256"] is None
