"""Encrypted TOTP enrollment and single-use factor verification."""
import base64
import hmac
import secrets
import time

import pyotp
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException

from .db import utc_now


class Totp:
    def __init__(self, key):
        self.key = base64.urlsafe_b64decode(key) if key else None

    def cipher(self):
        if not self.key:
            raise HTTPException(503, "El cifrado de segundo factor no está disponible.")
        return AESGCM(self.key)

    def encrypt(self, user_id, secret):
        nonce = secrets.token_bytes(12)
        encrypted = self.cipher().encrypt(nonce, secret.encode(), user_id.encode())
        return base64.urlsafe_b64encode(nonce + encrypted).decode()

    def decrypt(self, user_id, stored):
        try:
            data = base64.urlsafe_b64decode(stored)
            return self.cipher().decrypt(data[:12], data[12:], user_id.encode()).decode()
        except (InvalidTag, ValueError):
            raise HTTPException(503, "No se pudo verificar el segundo factor de la cuenta.") from None

    def match(self, user_id, stored, value, now, last_step=None):
        if len(value) != 6 or not value.isascii() or not value.isdigit():
            return None
        factor = pyotp.TOTP(self.decrypt(user_id, stored))
        current = now // factor.interval
        for step in (current, current - 1, current + 1):
            if (last_step is None or step > last_step) and hmac.compare_digest(factor.at(step * factor.interval), value):
                return step
        return None

    def digest(self, user_id, code):
        self.cipher()
        normalized = code.upper().replace("-", "")
        return hmac.digest(self.key, f"recovery:{user_id}:{normalized}".encode(), "sha256").hex()

    def consume(self, execute, user_id, record, code, now):
        step = self.match(user_id, record["secret"], code, now, record["last_step"])
        if step is not None:
            execute("UPDATE user_totp SET last_step=%s WHERE user_id=%s", (step, user_id))
            return True
        if len(code.replace("-", "")) != 24:
            return False
        return bool(execute("DELETE FROM totp_recovery_codes WHERE user_id=%s AND digest=%s RETURNING digest",
                            (user_id, self.digest(user_id, code))).fetchone())

    @staticmethod
    def state(execute, user_id):
        return execute("SELECT * FROM user_totp WHERE user_id=%s", (user_id,)).fetchone()

    @staticmethod
    def account(execute, principal, postgres):
        lock = " FOR UPDATE" if postgres else ""
        user = execute("SELECT active,token_version,password_hash FROM users WHERE id=%s" + lock, (principal["id"],)).fetchone()
        session = execute("SELECT jti FROM auth_sessions WHERE user_id=%s AND jti=%s AND expires_at>%s",
                          (principal["id"], principal.get("jti"), utc_now())).fetchone()
        if not user or not user["active"] or not session or user["token_version"] != principal.get("version"):
            raise HTTPException(401, "Sesión inválida o vencida.")
        return user

    def prepare(self, execute, principal):
        user_id = principal["id"]
        secret = pyotp.random_base32()
        ttl = 600
        execute("""INSERT INTO user_totp (user_id,pending_secret,pending_until,pending_session) VALUES (%s,%s,%s,%s)
            ON CONFLICT (user_id) DO UPDATE SET pending_secret=excluded.pending_secret,
            pending_until=excluded.pending_until,pending_session=excluded.pending_session""",
            (user_id, self.encrypt(user_id, secret), int(time.time()) + ttl, principal["jti"]))
        return {"secret": secret, "expires_in": ttl}

    def activate(self, execute, principal, code):
        user_id = principal["id"]
        record = self.state(execute, user_id)
        now = int(time.time())
        if not record or not record["pending_secret"] or record["pending_session"] != principal["jti"] or record["pending_until"] <= now:
            raise HTTPException(409, "La configuración venció. Inicia una nueva.")
        step = self.match(user_id, record["pending_secret"], code, now)
        if step is None:
            raise HTTPException(401, "Código de verificación inválido.")
        execute("""UPDATE user_totp SET secret=pending_secret,last_step=%s,pending_secret=NULL,
            pending_until=NULL,pending_session=NULL WHERE user_id=%s""", (step, user_id))
        codes = []
        for _ in range(8):
            raw = base64.b32encode(secrets.token_bytes(15)).decode()
            code = "-".join(raw[index:index + 6] for index in range(0, len(raw), 6))
            execute("INSERT INTO totp_recovery_codes (user_id,digest) VALUES (%s,%s)", (user_id, self.digest(user_id, code)))
            codes.append(code)
        return codes
