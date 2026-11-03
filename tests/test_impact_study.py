from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from fastapi.testclient import TestClient

from backend.config import Settings
from backend.db import utc_now
from backend.insights import LIMA
from backend.main import create_app
from backend.security import hash_password


class OperationalImpactTests(unittest.TestCase):
    def settings(self, path):
        return Settings(sqlite_path=path)

    def setUp(self):
        directory = TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        app = create_app(self.settings(Path(directory.name) / 'impact.sqlite3'))
        self.api = self.enterContext(TestClient(app))
        self.db = app.state.db
        self.password = 'test-credential-impact-01'
        hashed = hash_password(self.password)
        with self.db.session(write=True) as execute:
            for role in ('gestor', 'analista', 'auditor'):
                execute("INSERT INTO users (id,username,password_hash,role,creado_at) VALUES (%s,%s,%s,%s,%s)",
                        (str(uuid4()), role, hashed, role, utc_now()))
        self.root = '/api/estudios-impacto'

    def headers(self, role):
        result = self.api.post('/api/auth/login', json={'username':role,'password':self.password}).raise_for_status().json()
        return {'Authorization':'Bearer ' + result['access_token']}

    def fixture_report(self, title):
        rid = str(uuid4())
        received = datetime(2020, 9, 10, 14, tzinfo=timezone.utc)
        with self.db.session(write=True) as execute:
            execute("""INSERT INTO reports (id,titulo,descripcion,tipo,severidad,confianza,origen,recibido_at,clasificado_at)
                VALUES (%s,%s,'Caso sintético exclusivo de la prueba','phishing','media',0.9,'langflow',%s,%s)""",
                (rid, title, received.isoformat(), received.isoformat()))
            execute("""INSERT INTO assignments (report_id,responsable,asignado_at,vence_respuesta_at,vence_resolucion_at,respondido_at,resuelto_at)
                VALUES (%s,'Seguridad de correo',%s,%s,%s,%s,%s)""", (rid, received.isoformat(), *( (received + timedelta(minutes=minutes)).isoformat()
                    for minutes in (10,60,5,30) )))
        return rid

    def test_study_requires_real_attestation_and_comparable_cohorts(self):
        manager, analyst, auditor = (self.headers(role) for role in ('gestor','analista','auditor'))
        plan = {'nombre':'Validación de periodos', 'muestreo':'Incluir todos los casos comparables de phishing en los intervalos fijados.',
                'tipo':'phishing','severidad':'media','manual_desde':'2020-08-01','manual_hasta':'2020-08-31',
                'asistido_desde':'2020-09-01','asistido_hasta':'2020-09-30','minimo_por_grupo':3,
                'respuesta_min':10,'resolucion_min':60,'meta_mejora_pp':50}
        self.assertEqual(self.api.get(self.root, headers=auditor).status_code, 403)
        self.assertEqual(self.api.post(self.root, headers=analyst, json=plan).status_code, 403)
        self.assertEqual(self.api.post(self.root, headers=manager, json={**plan,'asistido_desde':'2020-08-31'}).status_code, 422)
        study_id = self.api.post(self.root, headers=manager, json=plan).raise_for_status().json()['id']
        study = self.root + '/' + study_id
        initial = self.api.get(study, headers=manager).raise_for_status().json()
        self.assertIsNone(initial['mejora_sla_pp'])
        self.assertIsNone(initial['ahorro_estimado_horas_muestras_reales'])
        record = study + '/observaciones'
        manual = {'modalidad':'manual','referencia':'ticket-1','recibido_at':'2020-08-03T09:00:00-05:00',
                  'respondido_at':'2020-08-03T09:05:00-05:00','resuelto_at':'2020-08-03T09:30:00-05:00',
                  'segundos_activos':300,'caso_real':True}
        self.assertEqual(self.api.post(record, headers=analyst, json={**manual,'caso_real':False}).status_code, 422)
        self.assertEqual(self.api.post(record, headers=analyst, json={**manual,'referencia':'DEMO-1'}).status_code, 422)
        self.assertEqual(self.api.post(record, headers=analyst, json={**manual,'recibido_at':'2020-07-03T09:00:00-05:00'}).status_code, 422)
        self.assertEqual(self.api.post(record, headers=analyst, json=manual).status_code, 201)
        self.assertEqual(self.api.post(record, headers=analyst, json=manual).status_code, 409)
        for index in (2,3):
            late = {**manual, 'referencia': f'ticket-{index}', 'respondido_at':'2020-08-03T09:20:00-05:00','resuelto_at':None}
            self.assertEqual(self.api.post(record, headers=analyst, json=late).status_code, 201)
        assisted = {'modalidad':'asistido','segundos_activos':100,'caso_real':True}
        demo = self.fixture_report('[DEMO] Prueba local')
        self.assertEqual(self.api.post(record, headers=analyst, json={**assisted,'reporte_id':demo}).status_code, 422)
        for index in range(3):
            case = self.fixture_report(f'Caso local {index}')
            self.assertEqual(self.api.post(record, headers=analyst, json={**assisted,'reporte_id':case}).status_code, 201)
        result = self.api.get(study, headers=manager).raise_for_status().json()
        self.assertEqual(result['grupos']['manual']['respuesta']['a_tiempo'], 1)
        self.assertEqual(result['grupos']['asistido']['resolucion']['a_tiempo'], 3)
        self.assertAlmostEqual(result['mejora_sla_pp']['respuesta'], 200/3)
        self.assertTrue(result['meta_sla_cumplida'])
        self.assertAlmostEqual(result['ahorro_estimado_horas_muestras_reales'], 1/6)

    def test_manual_case_requires_known_or_expired_sla(self):
        manager = self.headers('gestor')
        now = datetime.now(timezone.utc)
        received = now - timedelta(seconds=30)
        day = received.astimezone(LIMA).date()
        next_day = day + timedelta(days=1)
        payload = {'nombre':'Observaciones operativas', 'muestreo':'Todos los incidentes que coinciden con el criterio.',
                   'tipo':'phishing','severidad':'media','manual_desde':day.isoformat(),'manual_hasta':day.isoformat(),
                   'asistido_desde':next_day.isoformat(),'asistido_hasta':next_day.isoformat(),'minimo_por_grupo':3,
                   'respuesta_min':10,'resolucion_min':60,'meta_mejora_pp':5}
        sid = self.api.post(self.root, headers=manager, json=payload).raise_for_status().json()['id']
        path = f'{self.root}/{sid}/observaciones'
        sample = {'modalidad':'manual','referencia':'ticket-actual','recibido_at':received.isoformat(),
                  'segundos_activos':15,'caso_real':True}
        self.assertEqual(self.api.post(path, headers=manager, json=sample).status_code, 409)
        completed = (received + timedelta(seconds=20)).isoformat()
        sample.update(respondido_at=completed, resuelto_at=completed)
        self.assertEqual(self.api.post(path, headers=manager, json=sample).status_code, 201)
