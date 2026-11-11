"""Exercise the actual API contracts on an isolated operational backend."""
from uuid import uuid4

from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr
import pytest

from backend.config import Settings
from backend.db import utc_now
from backend.main import create_app
from backend.security import hash_password
from src.inference.services import SocApi
from src.utils.errors import ServiceError


def test_adapter_reuses_backend_login_rbac_and_revocation(settings, tmp_path):
    app = create_app(Settings(sqlite_path=tmp_path / "operational-test.sqlite3", operator_token="test-operator",
                              legacy_operator_enabled=False, jwt_secret="independent-test-jwt-secret-at-least-32-characters"))
    with TestClient(app) as server:
        with app.state.db.session(write=True) as execute:
            execute("INSERT INTO users (id,username,password_hash,role,creado_at) VALUES (%s,%s,%s,%s,%s)",
                    (str(uuid4()), "analyst", hash_password("test-password"), "analista", utc_now()))
        def dispatch(request):
            response = server.request(request.method, str(request.url), headers=dict(request.headers), content=request.content)
            return httpx.Response(response.status_code, content=response.content, headers=response.headers)
        api = SocApi(settings.api, transport=httpx.MockTransport(dispatch))
        assert api.health()["servicios"]["sqlite"] == "ok"
        session = api.login("analyst", SecretStr("test-password"))
        assert api.me(session.token).can("read")
        assert api.reports(session.token) == []
        api.logout(session.token)
        with pytest.raises(ServiceError) as caught:
            api.me(session.token)
        assert caught.value.status_code == 401


def test_evaluation_audit_enforces_jwt_and_role(tmp_path):
    app = create_app(Settings(sqlite_path=tmp_path / "evaluation-test.sqlite3", operator_token="test-operator",
                              legacy_operator_enabled=True, jwt_secret="independent-test-jwt-secret-at-least-32-characters"))
    endpoint = "/api/analitica/eventos"
    run_id = "20261110T220000000000Z_000000000000"
    read = {"action": "consultar_evaluaciones", "run_id": run_id}
    reserve = {"action": "autorizar_evaluacion", "run_id": run_id, "outcome": "iniciado"}
    inspect = {"action": "inspeccionar_evaluacion", "run_id": run_id}
    with TestClient(app) as server:
        with app.state.db.session(write=True) as execute:
            for role in ("analista", "gestor"):
                execute("INSERT INTO users (id,username,password_hash,role,creado_at) VALUES (%s,%s,%s,%s,%s)",
                        (str(uuid4()), role, hash_password("test-password"), role, utc_now()))

        def authorization(role):
            response = server.post("/api/auth/login", json={"username": role, "password": "test-password"})
            assert response.status_code == 200
            return {"Authorization": "Bearer " + response.json()["access_token"]}

        analyst, manager = authorization("analista"), authorization("gestor")
        assert server.post(endpoint, json=read, headers={"Authorization": "Bearer test-operator"}).status_code == 401
        assert server.post(endpoint, json=read, headers=manager).status_code == 204
        assert server.post(endpoint, json=reserve, headers=manager).status_code == 403
        assert server.post(endpoint, json=inspect, headers=manager).status_code == 403
        assert server.post(endpoint, json=reserve, headers=analyst).status_code == 204
        assert server.post(endpoint, json=inspect, headers=analyst).status_code == 204
        assert server.post(endpoint, json={**inspect, "raw_text": "dato restringido"}, headers=analyst).status_code == 422
        with app.state.db.session() as execute:
            rows = execute("SELECT action FROM audit_log WHERE entity_id=%s", (run_id,)).fetchall()
        assert {row["action"] for row in rows} == {read["action"], reserve["action"], inspect["action"]}
