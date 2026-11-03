"""Verify TOTP against PostgreSQL with a disposable analyst account."""
import json
import time
import unittest
from uuid import uuid4

import httpx
import pyotp
from dotenv import dotenv_values

from backend.config import ROOT


class LiveTotpTests(unittest.TestCase):
    def test_real_enrollment_and_single_use_recovery(self):
        config = dotenv_values(ROOT / '.env')
        self.assertTrue(bool(config.get('TOTP_ENCRYPTION_KEY')), 'Ejecuta el bootstrap para generar la clave TOTP.')
        accounts = json.loads((ROOT / '.venv/soc-runtime/access.json').read_text(encoding='utf-8'))
        admin = next(account for account in accounts if account['role'] == 'administrador')
        username = 'test_totp_' + uuid4().hex[:12]
        password = uuid4().hex + uuid4().hex
        with httpx.Client(base_url='http://127.0.0.1:8000', timeout=30, trust_env=False) as api:
            def login(user, credential, otp=None):
                payload = {'username':user,'password':credential,'otp':otp}
                result = api.post('/api/auth/login', json=payload)
                if result.status_code == 429:
                    time.sleep(61 - int(time.time()) % 60)
                    result = api.post('/api/auth/login', json=payload)
                return result

            def headers(response):
                return {'Authorization':'Bearer ' + response.raise_for_status().json()['access_token']}

            supervisor = headers(login(admin['username'], admin['password']))
            user = api.post('/api/users', headers=supervisor, json={'username':username,'password':password,'role':'analista'}).raise_for_status().json()
            try:
                initial = headers(login(username, password))
                secret = api.post('/api/auth/totp/preparar', headers=initial, json={'password':password}).raise_for_status().json()['secret']
                enrolled = api.post('/api/auth/totp/activar', headers=initial, json={'code':pyotp.TOTP(secret).now()}).raise_for_status().json()
                codes = enrolled['codigos_recuperacion']
                self.assertEqual(api.get('/api/auth/me', headers=initial).status_code, 401)
                self.assertEqual(login(username, password).status_code, 428)
                recovered = headers(login(username, password, codes[0]))
                self.assertEqual(login(username, password, codes[0]).status_code, 401)
                self.assertEqual(api.post('/api/auth/totp/desactivar', headers=recovered,
                                          json={'password':password,'code':codes[1]}).status_code, 204)
                self.assertEqual(api.get('/api/auth/me', headers=recovered).status_code, 401)
                authenticated = headers(login(username, password))
                api.post('/api/auth/logout', headers=authenticated).raise_for_status()
            finally:
                api.put('/api/users/' + user['id'], headers=supervisor, json={'role':'analista','active':False}).raise_for_status()
                api.post('/api/auth/logout', headers=supervisor).raise_for_status()
