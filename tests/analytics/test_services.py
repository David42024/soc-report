import json

import httpx
from pydantic import SecretStr
import pytest

from src.inference.services import SocApi
from src.utils.errors import ServiceError


@pytest.mark.parametrize("status", [401, 403, 428, 429, 500])
def test_service_errors_never_expose_upstream_payloads(settings, status):
    def respond(request):
        return httpx.Response(status, text="gsk_upstream_secret_that_must_not_escape")
    client = SocApi(settings.api, transport=httpx.MockTransport(respond))
    with pytest.raises(ServiceError) as caught:
        client.me(SecretStr("private-test-token"))
    assert caught.value.status_code == status
    assert "gsk_" not in str(caught.value)


def test_token_is_supplied_per_request_and_never_retained(settings):
    seen = []
    def respond(request):
        seen.append(request.headers.get("Authorization"))
        return httpx.Response(200, json={"id": "one", "username": "one", "role": "analista", "active": 1})
    client = SocApi(settings.api, transport=httpx.MockTransport(respond))
    client.me(SecretStr("token-user-a-private-value"))
    client.me(SecretStr("token-user-b-private-value"))
    assert seen == ["Bearer token-user-a-private-value", "Bearer token-user-b-private-value"]
    assert not any("token-user-a-private-value" in str(value) or "token-user-b-private-value" in str(value)
                   for value in vars(client).values())


def test_login_uses_existing_credentials_and_totp_contract(settings):
    def respond(request):
        assert request.url.path == "/api/auth/login"
        assert json.loads(request.content) == {"username": "analista", "password": "password", "otp": "123456"}
        return httpx.Response(200, json={"access_token": "hidden-token", "expires_in": 3600,
            "user": {"id": "one", "username": "analista", "role": "analista", "active": 1}})
    session = SocApi(settings.api, transport=httpx.MockTransport(respond)).login("analista", SecretStr("password"), SecretStr("123456"))
    assert "hidden-token" not in repr(session)
    assert session.user.can("read") and not session.user.can("manage")


def test_network_invalid_json_redirect_and_response_limits(settings):
    def offline(request):
        raise httpx.ConnectError("transport secret", request=request)
    for responder in (offline, lambda request: httpx.Response(200, text="invalid JSON"),
                      lambda request: httpx.Response(302, headers={"Location": "https://other.test"})):
        with pytest.raises(ServiceError) as caught:
            SocApi(settings.api, transport=httpx.MockTransport(responder)).health()
        assert "transport secret" not in str(caught.value)
    limits = settings.api.model_copy(update={"max_response_bytes": 4})
    with pytest.raises(ServiceError, match="límite"):
        SocApi(limits, transport=httpx.MockTransport(lambda request: httpx.Response(200, text="012345"))).health()
