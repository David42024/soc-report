"""Password authentication, signed access tokens, sessions and role permissions."""
import base64
import hashlib
import hmac
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Literal, get_args
from uuid import uuid4

import jwt
from fastapi import HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from redis import Redis
from redis.exceptions import RedisError
from starlette.concurrency import run_in_threadpool

from .context import identity
from .db import utc_now
from .totp import Totp

Role = Literal["administrador", "analista", "gestor", "auditor", "solicitante"]
ROLES = get_args(Role)
PERMISSIONS = {
    "read": ("administrador", "analista", "gestor"),
    "case_audit": ("administrador", "analista", "gestor", "auditor"),
    "write": ("administrador", "analista"),
    "report_export": ("administrador", "gestor"),
    "audit": ("administrador", "auditor"),
    "manage": ("administrador",),
    "baseline": ("administrador", "gestor"),
    "review": ("administrador", "analista"),
    "assets_edit": ("administrador", "analista"),
    "teams_edit": ("administrador",),
    "rules_edit": ("administrador",),
    "comment": ("administrador", "analista"),
}


def hash_password(password):
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 600_000)
    return "pbkdf2_sha256$600000$" + base64.b64encode(salt).decode() + "$" + base64.b64encode(digest).decode()


def verify_password(password, encoded):
    try:
        algorithm, iterations, salt, expected = encoded.split("$")
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), base64.b64decode(salt), int(iterations))
        return hmac.compare_digest(actual, base64.b64decode(expected))
    except (ValueError, TypeError):
        return False


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.-]+$")
    password: str = Field(min_length=1, max_length=128)


class LoginChallenge(LoginInput):
    otp: str | None = Field(default=None, min_length=1, max_length=48)


class PlatformSecurity:
    def __init__(self, settings, db):
        self.settings = settings
        self.db = db
        self.redis = Redis.from_url(settings.redis_url, decode_responses=True, socket_timeout=3) if settings.redis_url else None
        self.key = settings.jwt_secret or hashlib.sha256(settings.operator_token.encode()).hexdigest()
        self.totp = Totp(settings.totp_encryption_key.get_secret_value())
        self.dummy_hash = hash_password(secrets.token_urlsafe(24))

    def user(self, *, username=None, user_id=None):
        field, value = ("username", username.lower()) if username else ("id", user_id)
        with self.db.session() as execute:
            row = execute(f"SELECT * FROM users WHERE {field}=%s", (value,)).fetchone()
            return dict(row) if row else None

    @staticmethod
    def public_user(user):
        return {key: user[key] for key in ("id", "username", "role", "active")}

    def rate_limit(self, category, client, limit):
        window = int(time.time()) // 60
        bucket = f"soc:rate:{category}:{client}:{window}"
        if self.redis:
            try:
                count = self.redis.eval("""
                    local count = redis.call('INCR', KEYS[1])
                    if count == 1 then redis.call('EXPIRE', KEYS[1], 65) end
                    return count
                """, 1, bucket)
            except RedisError:
                raise HTTPException(503, "Redis no está disponible.") from None
        else:
            with self.db.session(write=True) as execute:
                execute("DELETE FROM rate_limits WHERE expires_at < %s", (int(time.time()),))
                count = execute("""INSERT INTO rate_limits (bucket,attempts,expires_at)
                    VALUES (%s,1,%s) ON CONFLICT (bucket) DO UPDATE
                    SET attempts=rate_limits.attempts+1 RETURNING attempts""",
                    (bucket, (window + 2) * 60)).fetchone()["attempts"]
        if count > limit:
            raise HTTPException(429, "Demasiadas solicitudes. Intenta de nuevo en un minuto.", headers={"Retry-After": "60"})

    def check_password(self, payload):
        user = self.user(username=payload.username)
        if not user or not user["active"]:
            verify_password(payload.password, self.dummy_hash)
            raise HTTPException(401, "Credenciales inválidas.")
        valid = verify_password(payload.password, user["password_hash"])
        now = int(time.time())
        with self.db.session(write=True) as execute:
            lock = " FOR UPDATE" if self.db.url else ""
            current = execute("SELECT active,password_hash,token_version FROM users WHERE id=%s" + lock,
                              (user["id"],)).fetchone()
            if not current or not current["active"] or current["password_hash"] != user["password_hash"] or current["token_version"] != user["token_version"]:
                raise HTTPException(401, "Credenciales inválidas.")
            failure = execute("SELECT attempts,until_at FROM login_failures WHERE user_id=%s", (user["id"],)).fetchone()
            attempts = failure["attempts"] if failure and failure["until_at"] > now else 0
            if attempts >= 5:
                raise HTTPException(401, "Credenciales inválidas.")
            if valid:
                factor = self.totp.state(execute, user["id"])
                if factor and factor["secret"]:
                    if not payload.otp:
                        raise HTTPException(428, "Introduce tu código de segundo factor o un código de recuperación.")
                    valid = self.totp.consume(execute, user["id"], factor, payload.otp.strip(), now)
            if valid:
                execute("DELETE FROM login_failures WHERE user_id=%s", (user["id"],))
            else:
                until = failure["until_at"] if 0 < attempts < 4 else now + 900
                execute("""INSERT INTO login_failures (user_id,attempts,until_at) VALUES (%s,%s,%s)
                    ON CONFLICT (user_id) DO UPDATE SET attempts=excluded.attempts,until_at=excluded.until_at""",
                    (user["id"], attempts + 1, until))
        if not valid:
            raise HTTPException(401, "Credenciales inválidas.")
        return user

    def login(self, payload, request):
        self.rate_limit("login", request.client.host, self.settings.login_limit)
        user = self.check_password(payload)
        principal = {**self.public_user(user), "ip": request.client.host,
                     "request_id": getattr(request.state, "request_id", None)}
        identity.set(principal)
        request.state.principal = principal
        now = datetime.now(timezone.utc)
        expires = now + timedelta(minutes=self.settings.jwt_minutes)
        jti = str(uuid4())
        token = jwt.encode({
            "sub": user["id"], "jti": jti, "ver": user["token_version"], "iat": now, "exp": expires,
            "iss": "soc-report-router", "aud": "soc-web",
        }, self.key, algorithm="HS256")
        if self.redis:
            try:
                self.redis.set(f"soc:session:{jti}", user["id"], ex=self.settings.jwt_minutes * 60)
            except RedisError:
                raise HTTPException(503, "Redis no está disponible.") from None
        with self.db.session(write=True) as execute:
            execute("INSERT INTO auth_sessions (jti,user_id,expires_at) VALUES (%s,%s,%s)",
                    (jti, user["id"], expires.isoformat()))
            execute("DELETE FROM auth_sessions WHERE expires_at < %s", (utc_now(),))
            self.db.access_event(execute, principal, "login", "auth", "operation", 200)
        return {"access_token": token, "token_type": "bearer", "expires_in": self.settings.jwt_minutes * 60,
                "user": self.public_user(user)}

    def authenticate(self, request: Request):
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            try:
                claims = jwt.decode(header[7:], self.key, algorithms=["HS256"],
                    issuer="soc-report-router", audience="soc-web", options={"require": ["exp", "iat", "sub", "jti", "ver"]})
                user = self.user(user_id=claims["sub"])
                if not user or not user["active"] or claims["ver"] != user["token_version"]:
                    raise ValueError
                with self.db.session() as execute:
                    session = execute("SELECT jti FROM auth_sessions WHERE jti=%s AND user_id=%s AND expires_at>%s",
                                      (claims["jti"], user["id"], utc_now())).fetchone()
                if not session:
                    raise ValueError
                if self.redis and self.redis.get(f"soc:session:{claims['jti']}") != user["id"]:
                    raise ValueError
            except RedisError:
                raise HTTPException(503, "Redis no está disponible.") from None
            except (jwt.PyJWTError, ValueError, KeyError):
                raise HTTPException(401, "Sesión inválida o vencida.") from None
            principal = {**self.public_user(user), "jti": claims["jti"], "version": user["token_version"]}
        elif self.settings.legacy_operator_enabled and hmac.compare_digest(
            request.headers.get("X-Operator-Token", "").encode(), self.settings.operator_token.encode()
        ):
            principal = {"id": "operador-compatibilidad", "username": "operador", "role": "analista", "active": 1}
        else:
            raise HTTPException(401, "Inicia sesión para continuar.")
        principal["ip"] = request.client.host
        principal["request_id"] = getattr(request.state, "request_id", None)
        identity.set(principal)
        request.state.principal = principal
        return principal

    def require(self, permission):
        async def dependency(request: Request):
            principal = await run_in_threadpool(self.authenticate, request)
            if principal["role"] not in PERMISSIONS[permission]:
                raise HTTPException(403, "Tu rol no permite esta acción.")
            identity.set(principal)
            return principal
        return dependency

    def logout(self, principal):
        jti = principal.get("jti")
        if jti:
            if self.redis:
                try:
                    self.redis.delete(f"soc:session:{jti}")
                except RedisError:
                    raise HTTPException(503, "Redis no está disponible.") from None
            with self.db.session(write=True) as execute:
                execute("DELETE FROM auth_sessions WHERE jti=%s", (jti,))
                self.db.access_event(execute, principal, "logout", "auth", "operation", 204)
