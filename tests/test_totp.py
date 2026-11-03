import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch
from uuid import uuid4

import pyotp
from fastapi.testclient import TestClient

from backend.config import Settings
from backend.db import utc_now
from backend.main import create_app
from backend.security import hash_password


class TotpTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        settings = Settings(sqlite_path=Path(temp.name) / 'auth.sqlite3', login_limit=35,
                            totp_encryption_key=base64.urlsafe_b64encode(b'T' * 32).decode())
        self.app = create_app(settings)
        self.api = self.enterContext(TestClient(self.app))
        self.db = self.app.state.db
        self.uid = str(uuid4())
        self.password = 'credencial-de-prueba-totp-91'
        with self.db.session(write=True) as execute:
            execute("INSERT INTO users (id,username,password_hash,role,creado_at) VALUES (%s,%s,%s,%s,%s)",
                    (self.uid, 'operador', hash_password(self.password), 'analista', utc_now()))

    def login(self, otp=None, password=None):
        return self.api.post('/api/auth/login', json={'username': 'operador', 'password': password or self.password, 'otp': otp})

    def headers(self, response):
        self.assertEqual(response.status_code, 200, response.text)
        return {'Authorization': 'Bearer ' + response.json()['access_token']}

    def test_enrollment_replay_recovery_revocation_and_disable(self):
        root = '/api/auth/totp'
        original = self.headers(self.login())
        other = self.headers(self.login())
        self.assertEqual(self.api.get(root, headers=original).json(), {'activo': False, 'disponible': True})
        self.assertEqual(self.api.post(root + '/preparar', headers=original, json={'password':'wrong'}).status_code, 403)
        secret = self.api.post(root + '/preparar', headers=original, json={'password':self.password}).raise_for_status().json()['secret']
        now = int(time.time())
        code = pyotp.TOTP(secret).at(now)
        allowed = {pyotp.TOTP(secret).at(now + shift) for shift in (-30, 0, 30)}
        wrong = next(f'{value:06d}' for value in range(4) if f'{value:06d}' not in allowed)
        self.assertEqual(self.api.post(root + '/activar', headers=other, json={'code':code}).status_code, 409)
        self.assertEqual(self.api.post(root + '/activar', headers=original, json={'code':wrong}).status_code, 401)
        with patch('backend.totp.time.time', return_value=now):
            activated = self.api.post(root + '/activar', headers=original, json={'code':code})
            self.assertEqual(activated.status_code, 200, activated.text)
            recovery = activated.json()['codigos_recuperacion']
            self.assertEqual(len(set(recovery)), 8)
            self.assertEqual(self.api.get('/api/auth/me', headers=original).status_code, 401)
            self.assertEqual(self.api.get('/api/auth/me', headers=other).status_code, 401)
            self.assertEqual(self.login().status_code, 428)
            self.assertEqual(self.login(password='wrong').status_code, 401)
            self.assertEqual(self.login(otp=code).status_code, 401)
        with self.db.session() as execute:
            stored = execute('SELECT secret,pending_secret FROM user_totp WHERE user_id=%s', (self.uid,)).fetchone()
            self.assertNotEqual(stored['secret'], secret)
            self.assertIsNone(stored['pending_secret'])
            audit = json.dumps(self.db.audit_records())
            self.assertNotIn(secret, audit)
            self.assertNotIn(recovery[0], audit)
        with patch('backend.totp.time.time', return_value=now + 30):
            current_code = pyotp.TOTP(secret).at(now + 30)
            self.headers(self.login(otp=current_code))
            self.assertEqual(self.login(otp=current_code).status_code, 401)
            recovered = self.headers(self.login(otp=recovery[0]))
            self.assertEqual(self.login(otp=recovery[0]).status_code, 401)
            self.assertEqual(self.api.post(root + '/desactivar', headers=recovered,
                                          json={'password':self.password, 'code':recovery[1]}).status_code, 204)
            self.assertEqual(self.api.get('/api/auth/me', headers=recovered).status_code, 401)
            self.headers(self.login())
