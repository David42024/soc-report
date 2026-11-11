"""Privacy regression fixtures are synthetic and never sent to cloud services."""
import asyncio
from hashlib import sha256
from copy import deepcopy
from datetime import datetime, timedelta
import json
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from fastapi import HTTPException
from fastapi.testclient import TestClient
import httpx
from pydantic import SecretStr
import pytest
import yaml

from backend.chat import ChatInput, answer, gemini_reply, groq_reply
from backend.config import ROOT, Settings
from backend.db import utc_now
from backend.main import create_app
from backend.routing import routing_policy
from backend.security import hash_password
from src.utils.privacy import DEFAULT_POLICY, PrivacyError, RedactionSession, protect_text
from scripts.soc_dataset import lifecycle
from test_cloud_model import load_cloud_component


DESCRIPTION = """María Pérez recibió un phishing con exfiltración confirmada.
Nombre: ana torres
Correo: maria.perez@example.test
Teléfono: +51 987 654 321
DNI: 12345678
Domicilio: Calle Los Olivos 123
usuario: m.perez
password="Synthetic Secret 2026!"
Activo: FS-01
IP origen 8.8.8.8 hacia 10.0.0.7:443; IPv6 2001:db8::1234
CVE-2026-12345; SHA256: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa
URL https://evil.example.test/login?email=maria.perez%40example.test&token=SecretToken123
""".strip()
PRIVATE_VALUES = ("María Pérez", "ana torres", "maria.perez@example.test", "+51 987 654 321", "12345678",
                  "Los Olivos 123", "m.perez", "Synthetic Secret 2026!", "8.8.8.8", "10.0.0.7",
                  "2001:db8::1234", "SecretToken123", "maria.perez%40example.test")
CLASSIFICATION = {"tipo": "phishing", "severidad": "alta", "activo_afectado": "FS-01", "confianza": 0.91}


def assert_protected(body):
    """Check actual serialized HTTP bodies, including escaped JSON characters."""
    text = json.dumps(body, ensure_ascii=False)
    for value in PRIVATE_VALUES:
        assert value not in text
    for technical in ("phishing", "exfiltración confirmada", "FS-01", "443", "CVE-2026-12345", "a" * 64,
                      "evil.example.test/login", "SOC_EMAIL", "SOC_IPV4_PUBLICA", "SOC_IPV4_PRIVADA"):
        assert technical in text


@pytest.mark.parametrize("text,private,kind", [
    ("Correo alice.smith+soc@example.test", "alice.smith+soc@example.test", "EMAIL"),
    ("Correo ＡＬＩＣＥ＠example.test", "ALICE@example.test", "EMAIL"),
    ("alice&#64;example.test", "alice@example.test", "EMAIL"),
    ("alice%2540example.test", "alice@example.test", "EMAIL"),
    ("ali\u200bce@example.test", "alice@example.test", "EMAIL"),
    ("María Pérez reportó phishing", "María Pérez", "PERSONA"),
    ("José de la Cruz recibió phishing", "José de la Cruz", "PERSONA"),
    ("Nombre completo: ana torres", "ana torres", "PERSONA"),
    ("John Smith reported malware", "John Smith", "PERSONA"),
    ("Juan recibió un correo falso", "Juan", "PERSONA"),
    ("DNI 12345678", "12345678", "DOCUMENTO"),
    ("Pasaporte PA1234567", "PA1234567", "DOCUMENTO"),
    ("Documento: 12 345 678", "12 345 678", "DOCUMENTO"),
    ("SSN 123-45-6789", "123-45-6789", "DOCUMENTO"),
    ("Tarjeta 4111 1111 1111 1111", "4111 1111 1111 1111", "CUENTA"),
    ("IBAN ES9121000418450200051332", "ES9121000418450200051332", "CUENTA"),
    ("Contactar al +51 987 654 321", "+51 987 654 321", "TELEFONO"),
    ("Teléfono: 987654321", "987654321", "TELEFONO"),
    ("Llamar 987 654 321", "987 654 321", "TELEFONO"),
    ("Fecha de nacimiento: 1990-05-14", "1990-05-14", "FECHA_PERSONAL"),
    ("Domicilio: Calle Los Olivos 123", "Los Olivos 123", "DIRECCION"),
    ("Diagnóstico: condición confidencial", "condición confidencial", "DATO_SENSIBLE"),
    ("usuario: alice.smith", "alice.smith", "USUARIO"),
    (r"Archivo C:\Users\alice.smith\Desktop\evidence.txt", "alice.smith", "USUARIO"),
    ("Archivo /home/alice.smith/evidence.txt", "alice.smith", "USUARIO"),
    (r"Inicio de sesión CORP\alice.smith", "alice.smith", "USUARIO"),
    ("password: test-only-synthetic-secret", "test-only-synthetic-secret", "SECRETO"),
    ("Mi contraseña es test-only-synthetic-secret", "test-only-synthetic-secret", "SECRETO"),
    ('{"api_key":"test-only-synthetic-secret"}', "test-only-synthetic-secret", "SECRETO"),
    ("Authorization: Bearer test-only-synthetic-secret", "test-only-synthetic-secret", "SECRETO"),
    ("Cookie: session=test-only-synthetic-secret", "test-only-synthetic-secret", "SECRETO"),
    ("gsk_abcdefghijklmnopqrstuvwxyz1234567890", "gsk_abcdefghijklmnopqrstuvwxyz1234567890", "SECRETO"),
    ("-----BEGIN PRIVATE KEY-----\nsynthetic-private-key\n-----END PRIVATE KEY-----", "synthetic-private-key", "SECRETO"),
    ("https://alice:synthetic-password@example.test/login", "alice:synthetic-password", "CREDENCIAL_URL"),
    ("https://example.test/login?person=alice&session=opaque", "alice", "PARAMETRO_URL"),
    ("data:text/plain;base64,YWxpY2VAZXhhbXBsZS50ZXN0", "YWxpY2VAZXhhbXBsZS50ZXN0", "CONTENIDO_CODIFICADO"),
    ("Origen 8.8.8.8", "8.8.8.8", "IPV4_PUBLICA"),
    ("Servidor 10.0.0.7:443", "10.0.0.7", "IPV4_PRIVADA"),
    ("Origen 2001:4860:4860::8888", "2001:4860:4860::8888", "IPV6_PUBLICA"),
    ("MAC aa:bb:cc:dd:ee:ff", "aa:bb:cc:dd:ee:ff", "MAC"),
])
def test_detects_supported_personal_and_sensitive_values(text, private, kind):
    result = protect_text(text)
    assert private not in result.text
    assert f"SOC_{kind}_" in result.text
    assert result.evidence["counts"][kind] >= 1
    assert private not in json.dumps(result.evidence, ensure_ascii=False)
    assert private not in repr(result)


def test_minimizes_report_without_destroying_technical_classification_evidence():
    result = protect_text(DESCRIPTION)
    assert_protected(result.text)
    assert ":443" in result.text
    assert "[SOC_IPV6_PRIVADA_" in result.text
    assert protect_text(result.text).text == result.text
    prompt = (ROOT / "integrations/langflow/prompt.txt").read_text(encoding="utf-8")
    assert protect_text(prompt).text == prompt  # No change to taxonomy or instructions.
    for technical in ("Active Directory", "Microsoft Windows", "Windows Server", "FS-01",
                      "CVE-2026-12345", "10.0.19045.4046", "2026-11-10", "SHA256: " + "1" * 64,
                      "Acceso No Autorizado", "Fuga de Datos", "Denegación de Servicio", "Correo Falso"):
        assert protect_text(technical).text == technical
    mixed = protect_text("Active Directory de María Pérez").text
    assert "Active Directory" in mixed and "María Pérez" not in mixed
    assert "Active Directory" not in protect_text("Nombre: Active Directory").text
    assert protect_text(r"C:\Users\alice.smith\Desktop\evidence.txt").text.endswith(r"\Desktop\evidence.txt")


def test_aliases_are_consistent_in_one_request_and_not_a_persistent_identity():
    session = RedactionSession()
    a = session.protect("alice@example.test alice@example.test bob@example.test")
    assert a.split()[0] == a.split()[1] != a.split()[2]
    assert session.protect("alice@example.test") == a.split()[0]
    # A new request assigns the first alias independently of the previous user.
    assert protect_text("bob@example.test").text == protect_text("alice@example.test").text
    evidence = session.evidence()
    assert evidence["counts"] == {"EMAIL": 4}
    assert "alice" not in json.dumps(evidence)
    assert protect_text("opaque-secret-without-prefix", known_secrets=("opaque-secret-without-prefix",)).text.startswith("[SOC_SECRETO_")


def test_policy_reload_fails_closed_after_a_valid_cached_configuration(tmp_path):
    path = tmp_path / "privacy.yaml"
    path.write_bytes(DEFAULT_POLICY.read_bytes())
    assert "alice@example.test" not in protect_text("alice@example.test", policy_path=path).text
    path.write_text("rules: []\n", encoding="utf-8")
    with pytest.raises(PrivacyError):
        protect_text("alice@example.test", policy_path=path)
    path.unlink()
    with pytest.raises(PrivacyError):
        protect_text("alice@example.test", policy_path=path)


def test_known_server_secrets_are_masked_even_without_a_label():
    settings = Settings(operator_token="unlabelled-operator-credential", internal_token="unlabelled-internal-credential",
        jwt_secret="unlabelled-jwt-credential", database_url="postgresql://user:UnlabelledDatabasePassword@localhost/db",
        redis_url="redis://:UnlabelledRedisPassword@localhost/0")
    values = ("unlabelled-operator-credential", "unlabelled-internal-credential", "unlabelled-jwt-credential",
              "UnlabelledDatabasePassword", "UnlabelledRedisPassword")
    result = protect_text("\n".join(values), known_secrets=settings.privacy_secrets())
    for value in values:
        assert value not in result.text and value not in json.dumps(result.evidence)


@pytest.mark.parametrize("change", ["missing", "invalid-yaml", "empty-rules", "bad-regex", "too-long", "too-many"])
def test_policy_or_input_errors_fail_closed_and_never_log_originals(tmp_path, caplog, change):
    path = tmp_path / "privacy.yaml"
    policy = yaml.safe_load(DEFAULT_POLICY.read_text(encoding="utf-8"))
    text = "alice@example.test"
    if change == "invalid-yaml":
        path.write_text("[invalid yaml", encoding="utf-8")
    elif change != "missing":
        if change == "empty-rules":
            policy["rules"] = []
        if change == "bad-regex":
            policy["rules"][0]["pattern"] = "("
        if change == "too-many":
            policy["max_matches"] = 1
            text += " bob@example.test"
        if change == "too-long":
            text += "x" * (policy["max_text_characters"] + 1)
        path.write_text(yaml.safe_dump(policy, allow_unicode=True), encoding="utf-8")
    with pytest.raises(PrivacyError) as error:
        protect_text(text, policy_path=path)
    assert "alice@example.test" not in str(error.value) + caplog.text


def cloud_model(text=DESCRIPTION):
    return load_cloud_component()(system_message=SimpleNamespace(text=(ROOT / "integrations/langflow/prompt.txt").read_text(encoding="utf-8")),
        input_value=SimpleNamespace(text=text), groq_model="openai/gpt-oss-20b", gemini_model="gemini-3-flash-preview",
        groq_api_key=SecretStr("test-only-groq-key"), gemini_api_key=SecretStr("test-only-gemini-key"))


def provider_handler(calls, mode):
    """Capture the exact external request with an in-process HTTP transport."""
    def handle(request):
        body = json.loads(request.content)
        calls.append((request.url.host, body))
        assert_protected(body)
        if request.url.host == "api.groq.com":
            if mode == "timeout":
                raise httpx.ReadTimeout("synthetic upstream body must not be logged", request=request)
            if mode in ("429", "500", "gemini-retry", "both-fail"):
                if mode in ("gemini-retry", "both-fail"):
                    return httpx.Response(503)
                return httpx.Response(int(mode))
            if mode == "malformed":
                return httpx.Response(200, json={})
            if mode == "safety":
                return httpx.Response(400, json={"error": {"code": "content_policy_violation"}})
            value = {**CLASSIFICATION, "confianza": 0.3} if mode == "low-confidence" else CLASSIFICATION
            return httpx.Response(200, json={"choices": [{"message": {"content": json.dumps(value)}}]})
        assert request.url.host == "generativelanguage.googleapis.com"
        if mode == "both-fail" or (mode == "gemini-retry" and len(calls) == 2):
            return httpx.Response(503, text="synthetic upstream error body")
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": json.dumps(CLASSIFICATION)}]}}]})
    return handle


@pytest.mark.parametrize("mode", ["success", "429", "500", "timeout", "malformed", "safety", "low-confidence", "gemini-retry", "both-fail"])
def test_cloud_component_protects_both_providers_without_changing_fallback_policy(mode):
    calls, real_client = [], httpx.AsyncClient
    model = cloud_model()
    with patch("httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(provider_handler(calls, mode)), **kw)):
        result = asyncio.run(model.classify())
        assert result.session_metadata["soc_privacy"]["status"] == "protected"
        assert result.session_metadata["soc_privacy"]["counts"]
        metadata = result.session_metadata
        assert metadata["soc_input_text"] == calls[0][1]["messages"][1]["content"]
        assert metadata["soc_input_sha256"] == sha256(metadata["soc_input_text"].encode()).hexdigest()
        assert metadata["soc_prompt_sha256"] == sha256(calls[0][1]["messages"][0]["content"].encode()).hexdigest()
        if mode in ("safety", "both-fail"):
            assert metadata["soc_provider"] is None and metadata["soc_model"] is None
            assert metadata["soc_trace"]["outcome"] == "protective"
            assert json.loads(result.text)["confianza"] == 0.0
        else:
            assert metadata["soc_model"] == (model.groq_model if metadata["soc_provider"] == "groq" else model.gemini_model)
    hosts = [host for host, _ in calls]
    assert hosts == (["api.groq.com"] if mode in ("success", "safety", "low-confidence") else
                     ["api.groq.com"] + ["generativelanguage.googleapis.com"] * (2 if mode in ("gemini-retry", "both-fail") else 1))
    for _, body in calls[1:]:
        assert calls[0][1]["messages"][1]["content"] == body["contents"][0]["parts"][0]["text"]
    assert model.input_value.text == DESCRIPTION  # No mutation of the original.


def test_direct_cloud_component_never_opens_a_client_if_privacy_fails(monkeypatch, tmp_path):
    monkeypatch.setenv("SOC_PRIVACY_POLICY", str(tmp_path / "missing.yaml"))
    with patch("httpx.AsyncClient") as external, pytest.raises(PrivacyError):
        asyncio.run(cloud_model().classify())
    external.assert_not_called()


@pytest.mark.parametrize("mode", ["success", "429"])
def test_fastapi_langflow_provider_pipeline_preserves_original_and_authorized_access(tmp_path, mode):
    settings = Settings(sqlite_path=tmp_path / "privacy.sqlite3", classifier_mode="langflow", langflow_flow_id="test-flow",
        langflow_api_key="test-only-langflow-key", operator_token="test-operator", internal_token="test-internal",
        legacy_operator_enabled=False, jwt_secret="test-only-private-jwt-key-longer-than-32-characters")
    app = create_app(settings)
    calls, langflow_inputs = [], []
    real_async, real_sync = httpx.AsyncClient, httpx.Client
    with TestClient(app) as api:
        roles = ["administrador", "analista", "gestor", "auditor", "solicitante"]
        digest = hash_password("test-only-password")
        with app.state.db.session(write=True) as execute:
            for role in [*roles, "other-requester"]:
                execute("INSERT INTO users (id,username,password_hash,role,creado_at) VALUES (%s,%s,%s,%s,%s)",
                        (str(uuid4()), role, digest, "solicitante" if role == "other-requester" else role, utc_now()))
        tokens = {role: {"Authorization": "Bearer " + api.post("/api/auth/login",
            json={"username": role, "password": "test-only-password"}).json()["access_token"]} for role in [*roles, "other-requester"]}

        def langflow(request):
            assert request.url.host == "langflow.test"
            body = json.loads(request.content)
            assert_protected(body)
            langflow_inputs.append(body)
            model = cloud_model(body["input_value"])
            message = asyncio.run(model.classify())
            return httpx.Response(200, json={"outputs": [{"outputs": [{"results": {
                "message": {"text": message.text, "session_metadata": message.session_metadata}}}]}]})

        settings.langflow_url = "http://langflow.test"
        report_id = str(uuid4())
        payload = {"titulo": "Phishing en FS-01", "descripcion": DESCRIPTION}
        with patch("httpx.Client", side_effect=lambda **kw: real_sync(transport=httpx.MockTransport(langflow), **kw)), \
             patch("httpx.AsyncClient", side_effect=lambda **kw: real_async(transport=httpx.MockTransport(provider_handler(calls, mode)), **kw)):
            submitted = api.request("POST", "/api/reportes", json=payload,
                                    headers={**tokens["solicitante"], "Idempotency-Key": report_id})
            assert submitted.status_code == 201
            assert api.request("POST", "/api/reportes", json=payload,
                headers={**tokens["solicitante"], "Idempotency-Key": report_id}).status_code == 200
        receipt = submitted.json()
        assert (receipt["tipo"], receipt["severidad"], receipt["activo_afectado"], receipt["origen"]) == ("phishing", "alta", "FS-01", "langflow")
        assert receipt["notificado_at"] and not receipt["motivo_revision"]
        assert "titulo" not in receipt and "descripcion" not in receipt
        rules = routing_policy(app.state.db)["configuration"]
        assert receipt["responsable"] == rules["equipos"][receipt["tipo"]]
        api.headers.update(tokens["analista"])
        try:
            evaluated = lifecycle(api, app.state.db, receipt, rules, "local")
        finally:
            api.headers.pop("Authorization", None)
        assert evaluated["status"] == "routed"
        assert evaluated["provider"] == ("groq" if mode == "success" else "gemini")
        for column, field in (("vence_respuesta_at", "respuesta_min"), ("vence_resolucion_at", "resolucion_min")):
            assert datetime.fromisoformat(receipt[column]) == datetime.fromisoformat(receipt["recibido_at"]) + timedelta(minutes=rules["sla"]["alta"][field])
        path = f"/api/reportes/{report_id}"
        for role in roles:
            detail = api.get(path, headers=tokens[role])
            assert detail.status_code == (200 if role in ("administrador", "analista", "gestor") else 403)
            if detail.status_code == 200:
                assert {key: detail.json()[key] for key in payload} == payload
        assert api.get(path).status_code == 401
        assert api.get(path, headers={"Authorization": "Bearer invalid"}).status_code == 401
        assert api.get(f"/api/mis-solicitudes/{report_id}", headers=tokens["solicitante"]).json()["descripcion"] == DESCRIPTION
        assert api.get(f"/api/mis-solicitudes/{report_id}", headers=tokens["other-requester"]).status_code == 404
        context = api.get(f"/internal/reportes/{report_id}/contexto", headers={"X-Internal-Token": "test-internal"}).json()
        assert "descripcion" not in context and "titulo" not in context
        events = api.get(path + "/bitacora", headers=tokens["auditor"]).json()
        assert [e["accion"] for e in events] == ["recibido", "clasificado", "asignado", "notificacion"]
        classified = next(e for e in events if e["accion"] == "clasificado")
        assert "soc-privacy-1" in classified["detalle"] and '"status": "protected"' in classified["detalle"]
        for value in PRIVATE_VALUES:
            assert value not in json.dumps(events, ensure_ascii=False)
        assert app.state.db.report(report_id)["descripcion"] == DESCRIPTION
        xai = api.get(path + "/explicabilidad", headers=tokens["analista"]).json()
        assert xai["input_status"] == "capturada" and xai["input"]["scope"] == "entrada_proveedor"
        assert xai["input"]["provider"] == evaluated["provider"]
        assert xai["input"]["text"] == calls[0][1]["messages"][1]["content"]
        assert xai["input"]["model"] == ("openai/gpt-oss-20b" if mode == "success" else "gemini-3-flash-preview")
        assert xai["input"]["prompt_sha256"] == sha256(calls[0][1]["messages"][0]["content"].encode()).hexdigest()
        for value in PRIVATE_VALUES:
            assert value not in json.dumps(xai, ensure_ascii=False)
        assert len(langflow_inputs) == 1
        assert len(calls) == (1 if mode == "success" else 2)


def test_privacy_failure_saves_original_in_triage_without_calling_langflow(tmp_path, monkeypatch):
    monkeypatch.setenv("SOC_PRIVACY_POLICY", str(tmp_path / "missing.yaml"))
    app = create_app(Settings(sqlite_path=tmp_path / "blocked.sqlite3", classifier_mode="langflow",
        langflow_flow_id="test", langflow_api_key="test-only-langflow-key", operator_token="test-operator"))
    with TestClient(app) as api, patch("httpx.Client.post") as external:
        response = api.request("POST", "/api/reportes", json={"titulo": "Phishing en FS-01", "descripcion": DESCRIPTION})
        assert response.status_code == 201
        report = response.json()
        assert (report["origen"], report["motivo_revision"], report["responsable"]) == ("fallback", "privacidad_no_disponible", "Triaje SOC")
        assert app.state.db.report(report["id"])["descripcion"] == DESCRIPTION
        assert '"status": "blocked"' in next(e for e in app.state.db.audit(report["id"]) if e["accion"] == "clasificado")["detalle"]
    external.assert_not_called()


@pytest.mark.parametrize("mode", ["success", "429"])
def test_chat_protects_the_whole_history_and_reuses_it_on_fallback(mode):
    data = {"messages": [{"role": "user", "content": DESCRIPTION},
                         {"role": "assistant", "content": "Contactar a maria.perez@example.test"},
                         {"role": "user", "content": "Phishing de María Pérez en FS-01"}]}
    original = deepcopy(data)
    settings = Settings(groq_api_key="test-only-groq-key", gemini_api_key="test-only-gemini-key")
    calls, real_client = [], httpx.AsyncClient
    with patch("httpx.AsyncClient", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(provider_handler(calls, mode)), **kw)):
        result = asyncio.run(answer(ChatInput.model_validate(data), settings))
    assert result.provider == ("Groq" if mode == "success" else "Gemini")
    assert data == original
    if mode == "429":
        assert [m["content"] for m in calls[0][1]["messages"][1:]] == [m["parts"][0]["text"] for m in calls[1][1]["contents"]]


@pytest.mark.parametrize("complete", [groq_reply, gemini_reply])
def test_low_level_chat_egress_also_protects_direct_calls(complete):
    calls, real_client = [], httpx.AsyncClient
    settings = Settings(groq_api_key="test-only-groq-key", gemini_api_key="test-only-gemini-key")
    async def run():
        async with real_client(transport=httpx.MockTransport(provider_handler(calls, "success"))) as client:
            await complete(client, settings, "Instrucciones sin información personal.", [{"role": "user", "content": DESCRIPTION}])
    asyncio.run(run())
    assert len(calls) == 1


def test_chat_privacy_failure_does_not_attempt_either_provider(tmp_path, monkeypatch):
    monkeypatch.setenv("SOC_PRIVACY_POLICY", str(tmp_path / "missing.yaml"))
    with patch("httpx.AsyncClient") as client, pytest.raises(HTTPException) as error:
        asyncio.run(answer(ChatInput(messages=[{"role": "user", "content": "maria.perez@example.test"}]), Settings()))
    assert error.value.status_code == 503 and "maria.perez" not in error.value.detail
    client.assert_not_called()


def test_component_update_reuses_credentials_and_changes_only_source_code(monkeypatch, capsys):
    from scripts import update_langflow_component as updater
    graph = json.loads((ROOT / "integrations/langflow/cybersecurity_classifier.json").read_text(encoding="utf-8-sig"))["data"]
    template = next(n for n in graph["nodes"] if n["data"]["type"] == "SocCloudModel")["data"]["node"]["template"]
    template["code"]["value"] = "# synthetic previous source"
    original = deepcopy(graph)
    requests = []
    real_client = httpx.Client
    def handle(request):
        nonlocal graph
        requests.append((request.method, request.url.path))
        assert request.headers["x-api-key"] == "test-only-langflow-key"
        assert request.url.path == "/api/v1/flows/test-flow"
        if request.method == "PATCH":
            graph = json.loads(request.content)["data"]
        return httpx.Response(200, json={"data": graph})
    monkeypatch.setattr(updater, "dotenv_values", lambda _: {"LANGFLOW_URL": "http://127.0.0.1:7861",
        "LANGFLOW_FLOW_ID": "test-flow", "LANGFLOW_API_KEY": "test-only-langflow-key"})
    with patch("httpx.Client", side_effect=lambda **kw: real_client(transport=httpx.MockTransport(handle), **kw)):
        updater.update()
        updater.update()  # A repeat must be idempotent.
    changed = next(n for n in graph["nodes"] if n["data"]["type"] == "SocCloudModel")["data"]["node"]["template"]
    assert changed["code"]["value"] == (ROOT / "integrations/langflow/cloud_classifier_model.py").read_text(encoding="utf-8")
    changed["code"]["value"] = "# synthetic previous source"
    assert graph == original
    assert requests.count(("PATCH", "/api/v1/flows/test-flow")) == 1
    assert "test-only-langflow-key" not in capsys.readouterr().out
