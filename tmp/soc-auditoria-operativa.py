"""Revalidation of the existing SOC stack. Only a labeled report is created."""
import json
import math
import subprocess
import sys
import time
from io import BytesIO
from pathlib import Path
from uuid import uuid4

import httpx
import psycopg
from docx import Document
from dotenv import dotenv_values
from openpyxl import load_workbook
from redis import Redis

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.venv/soc-runtime'
CFG = dotenv_values(ROOT / '.env')
EVIDENCE_ID = '4e07fb29-af74-4bdc-9e97-89e90b36531f'
COMPOSE = ['docker', 'compose', '--env-file', str(RUNTIME / 'compose.env')]


def compose(*args):
    result = subprocess.run(COMPOSE + list(args), cwd=ROOT, capture_output=True, timeout=60)
    assert result.returncode == 0, ('Docker Compose', args, result.returncode)


def retry(fn, timeout=120):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            if fn():
                return
        except (httpx.RequestError, OSError):
            pass
        time.sleep(1)
    raise AssertionError('La condición de recuperación no se completó en plazo')


def routing_check(api, db, redis):
    rid = str(uuid4())
    print('ID de persistencia/reintentos:', rid, flush=True)
    key = {'Idempotency-Key': rid}
    body = {'titulo': '[DEMO] Correo falso de soporte - validación de reinicio',
            'descripcion': 'Recibí un enlace sospechoso para renovar la clave.\nActivo: correo corporativo'}
    compose('stop', 'n8n')
    try:
        result = api.post('/api/reportes', json=body, headers=key)
        assert result.status_code == 201, result.status_code
        report = result.json()
        assert report['id'] == rid and report['notificado_at'] is None
        persisted = db.execute('SELECT tipo,severidad,activo_afectado,confianza,origen FROM reports WHERE id=%s', (rid,)).fetchone()
        assert persisted and db.execute('SELECT count(*) FROM assignments WHERE report_id=%s', (rid,)).fetchone()[0] == 0
        assert db.execute("SELECT count(*) FROM bitacora WHERE report_id=%s AND accion='enrutamiento_pendiente'", (rid,)).fetchone()[0] >= 1
        assert redis.zscore('soc:routing', rid) is not None
        before = redis.info('server')['run_id']
        compose('restart', 'redis')
        retry(lambda: api.get('/health?detalle=true').json()['servicios']['redis'] == 'ok', 50)
        assert redis.info('server')['run_id'] != before
        assert db.execute('SELECT count(*) FROM reports WHERE id=%s', (rid,)).fetchone()[0] == 1
        print('PostgreSQL guardó el caso con n8n apagado. Redis reiniciado con cambio de run_id.', flush=True)
        print('Clasificación de la prueba:', persisted, flush=True)
    finally:
        compose('start', 'n8n')
    retry(lambda: api.get('http://127.0.0.1:5680/healthz/readiness').is_success, 100)
    retry(lambda: db.execute("SELECT count(*) FROM bitacora WHERE report_id=%s AND accion='notificacion'", (rid,)).fetchone()[0] == 1, 150)
    for _ in range(10):
        replay = api.post('/api/reportes', headers=key, json=body)
        assert replay.status_code == 200 and replay.json()['id'] == rid
    assert api.post('/api/reportes', headers=key, json={**body, 'titulo': 'Contenido distinto'}).status_code == 409
    assert db.execute('SELECT count(*) FROM reports WHERE id=%s', (rid,)).fetchone()[0] == 1
    assert db.execute('SELECT count(*) FROM assignments WHERE report_id=%s', (rid,)).fetchone()[0] == 1
    events = db.execute('SELECT accion,actor FROM bitacora WHERE report_id=%s ORDER BY ocurrido_at', (rid,)).fetchall()
    assert events.count(('asignado', 'n8n')) == events.count(('notificacion', 'n8n')) == 1
    print('Recuperación automática sin reintento manual. 10/10 reenvíos HTTP 200, cambio HTTP 409.', flush=True)
    print('Bitácora:', events, flush=True)
    return rid


def dashboard_check(api, db, manager):
    for filters in ({}, {'desde': '2026-01-01', 'hasta': '2026-12-31', 'tipo': 'phishing',
                         'severidad': 'media', 'equipo': 'Seguridad de correo'}):
        stats = api.get('/api/dashboard', params=filters, headers=manager).raise_for_status().json()
        where = "WHERE (r.recibido_at AT TIME ZONE 'America/Lima')::date BETWEEN %s AND %s AND r.tipo=%s AND r.severidad=%s AND a.responsable=%s" if filters else ''
        sql = """SELECT r.id,r.tipo,r.severidad,r.origen,r.titulo,r.activo_afectado,r.motivo_revision,r.recibido_at,r.clasificado_at,
                 a.responsable,a.respondido_at,a.resuelto_at,a.vence_respuesta_at,a.vence_resolucion_at,
                 CASE WHEN a.responsable IS NULL THEN 'sin_asignar' WHEN a.resuelto_at IS NOT NULL THEN 'resuelto'
                      WHEN a.respondido_at IS NOT NULL THEN 'en_atencion' ELSE 'por_atender' END estado
                 FROM reports r LEFT JOIN assignments a ON a.report_id=r.id """ + where
        args = tuple(filters.values())
        vals = db.execute(f"""WITH data AS ({sql}) SELECT count(*), count(*) FILTER (WHERE origen='demo' OR titulo LIKE '[DEMO]%%'),
            count(*) FILTER (WHERE vence_respuesta_at IS NOT NULL AND (respondido_at IS NOT NULL OR vence_respuesta_at < now())),
            count(*) FILTER (WHERE respondido_at <= vence_respuesta_at),
            count(*) FILTER (WHERE vence_resolucion_at IS NOT NULL AND (resuelto_at IS NOT NULL OR vence_resolucion_at < now())),
            count(*) FILTER (WHERE resuelto_at <= vence_resolucion_at),
            avg(EXTRACT(epoch FROM clasificado_at-recibido_at)), avg(EXTRACT(epoch FROM respondido_at-recibido_at)),
            avg(EXTRACT(epoch FROM resuelto_at-recibido_at)) FROM data""", args).fetchone()
        assert (stats['total'], stats['demo']) == vals[:2]
        keys = ('respuesta_evaluable', 'respuesta_a_tiempo', 'resolucion_evaluable', 'resolucion_a_tiempo')
        assert tuple(stats['sla'].get(k, 0) for k in keys) == vals[2:6]
        for key, avg in zip(('clasificacion', 'respuesta', 'resolucion'), vals[6:]):
            if avg is not None:
                assert math.isclose(stats['tiempos'][key]['segundos'], float(avg), rel_tol=1e-8)
        for column, key in (('tipo', 'tipos'), ('severidad', 'severidades'), ('estado', 'estados')):
            rows = db.execute(f'SELECT {column},count(*) FROM ({sql}) AS data GROUP BY {column}', args).fetchall()
            assert dict(rows) == stats[key]
        teams = db.execute(f"""SELECT responsable,count(*),count(*) FILTER (WHERE resuelto_at IS NULL)
            FROM ({sql}) AS data WHERE responsable IS NOT NULL GROUP BY responsable""", args).fetchall()
        assert {name: (total, opened) for name, total, opened in teams} == {
            row['nombre']: (row['total'], row['abiertos']) for row in stats['equipos']}
        months = db.execute(f"""SELECT to_char(recibido_at AT TIME ZONE 'America/Lima', 'YYYY-MM'),count(*)
            FROM ({sql}) AS data GROUP BY 1""", args).fetchall()
        assert dict(months) == {row['mes']: row['total'] for row in stats['mensual']}
        reviews = db.execute(f"""SELECT d.origen,(d.origen='demo' OR d.titulo LIKE '[DEMO]%%') AS demo,
            count(*),count(d.motivo_revision),count(v.report_id),count(*) FILTER (WHERE v.report_id IS NOT NULL AND
            (d.tipo,d.severidad,d.activo_afectado) IS NOT DISTINCT FROM (v.tipo,v.severidad,v.activo_afectado))
            FROM ({sql}) AS d LEFT JOIN report_reviews v ON v.report_id=d.id GROUP BY 1,2""", args).fetchall()
        assert {(origin, demo): (total, review, validated, correct) for origin, demo, total, review, validated, correct in reviews} == {
            (row['origen'], row['demo']): tuple(row[key] for key in ('total','revision','validados','aciertos'))
            for row in stats['clasificador']}
        print('Dashboard y SQL coinciden:', 'filtrado' if filters else 'total', vals[:6], flush=True)


def rights(api, db, rid, accounts):
    headers = {}
    for account in accounts:
        token = api.post('/api/auth/login', json={k: account[k] for k in ('username', 'password')}).raise_for_status().json()
        headers[account['role']] = {'Authorization': 'Bearer ' + token['access_token']}
    expected = {
        '/api/dashboard': ('administrador','analista','gestor'),
        '/api/informes/cola/xlsx': ('administrador','analista','gestor'),
        '/api/exportar/xlsx': ('administrador','analista','gestor'),
        '/api/audit': ('administrador','auditor'),
        '/api/audit/exportar/xlsx': ('administrador','auditor'),
        '/api/users': ('administrador',), '/api/reglas': ('administrador',),
        '/api/revision': ('administrador','analista'), '/api/notificaciones': ('administrador','analista','gestor'),
        '/api/reportes/' + rid: ('administrador','analista','gestor'),
        '/api/reportes/' + rid + '/bitacora': ('administrador','analista','gestor','auditor'),
    }
    for path, allowed in expected.items():
        assert api.get(path).status_code == 401, path
        for role, auth in headers.items():
            status = api.get(path, headers=auth).status_code
            assert status == (200 if role in allowed else 403), (path, role, status)
    mutations = [
        ('POST', '/api/users', {'username':'validacion', 'password':'Solo-un-valor-de-prueba-2026', 'role':'auditor'}, 'gestor'),
        ('PUT', '/api/activos/' + str(uuid4()), {'nombre':'Validación sin escritura'}, 'gestor'),
        ('PUT', '/api/equipos', {'nombre':'Validación sin escritura'}, 'analista'),
        ('POST', '/api/reportes/' + rid + '/responder', None, 'gestor'),
        ('POST', '/api/reportes/' + rid + '/comentarios', {'contenido':'Validación sin escritura'}, 'auditor'),
        ('PUT', '/api/reportes/' + rid + '/revision', {'tipo':'phishing','severidad':'media'}, 'gestor'),
    ]
    for method, path, payload, role in mutations:
        assert api.request(method, path, json=payload).status_code == 401
        assert api.request(method, path, json=payload, headers=headers[role]).status_code == 403
    rejected = api.get('/api/auth/me', headers={'Authorization':'Bearer invalid-revalidation-token'})
    assert rejected.status_code == 401
    rows = db.execute('SELECT phase,status_code FROM audit_log WHERE request_id=%s ORDER BY occurred_at',
                      (rejected.headers['X-Request-ID'],)).fetchall()
    assert rows == [('entry', None), ('rejected', 401), ('exit', 401)]
    nav = api.post('/api/audit/navegacion', headers=headers['gestor'], json={'anterior':'inbox','siguiente':'dashboard'}).raise_for_status()
    assert db.execute("SELECT action,module,status_code FROM audit_log WHERE request_id=%s AND phase='navigation' ORDER BY occurred_at", (nav.headers['X-Request-ID'],)).fetchall() == [('module_exit','inbox',None), ('module_enter','dashboard',None)]
    cors = api.options('/api/reportes', headers={'Origin':'https://externo.invalid','Access-Control-Request-Method':'POST','Access-Control-Request-Headers':'authorization,content-type'})
    assert 'access-control-allow-origin' not in cors.headers
    print('RBAC:', len(expected)*5 + len(mutations)*2, 'comprobaciones HTTP. Rechazo 401:', rows,
          '| Preflight externo:', cors.status_code, 'sin ACAO', flush=True)
    for statement in ('UPDATE audit_log SET action=action WHERE false', 'DELETE FROM audit_log WHERE false', 'TRUNCATE audit_log'):
        with psycopg.connect(CFG['DATABASE_URL'], connect_timeout=5) as isolated:
            try:
                isolated.execute(statement)
            except psycopg.Error:
                isolated.rollback()
            else:
                isolated.rollback()
                raise AssertionError('El trigger permitió la sentencia: ' + statement.split()[0])
    print('SQL directo: UPDATE, DELETE y TRUNCATE rechazados.', flush=True)
    return headers


def formats(api, db, auth):
    bundle = str(Path.home() / '.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe')
    read_pdf = [bundle, '-c', r'import sys,re; from io import BytesIO; from pypdf import PdfReader; t=" ".join(" ".join(p.extract_text().split()) for p in PdfReader(BytesIO(sys.stdin.buffer.read())).pages); print(re.search(r"Filas incluidas (\d+)",t).group(1))']
    requests = []
    for kind in ('cola','sla','pendientes','mensual','tendencia','clasificador','equipos'):
        for filters in ({'tipo':'phishing'}, {'desde':'1900-01-01','hasta':'1900-01-02','tipo':'phishing'}):
            files = {}
            for fmt in ('pdf','docx','xlsx'):
                response = api.get(f'/api/informes/{kind}/{fmt}', headers=auth, params=filters)
                if response.status_code != 200:
                    print('Fallo de exportación:', kind, fmt, response.status_code, response.headers.get('X-Request-ID'),
                          '| Salud:', api.get('/health?detalle=true').json(), flush=True)
                response.raise_for_status()
                requests.append(response.headers['X-Request-ID'])
                files[fmt] = response.content
            workbook = load_workbook(BytesIO(files['xlsx']))
            sheet = workbook.active
            word = Document(BytesIO(files['docx'])).tables[0]
            pdf = subprocess.run(read_pdf, input=files['pdf'], capture_output=True, timeout=30, check=True)
            assert int(pdf.stdout) == len(word.rows)-1 == sheet.max_row-1, kind
            if 'desde' in filters:
                assert sheet.max_row == 1, kind
            elif kind == 'cola':
                assert sheet.max_row > 1 and all(row[4] == 'phishing' for row in list(sheet.values)[1:])
    count = db.execute("SELECT count(*) FROM audit_log WHERE request_id=ANY(%s) AND phase='exit' AND status_code=200", (requests,)).fetchone()[0]
    assert count == len(requests)
    print('Exportaciones verificadas:', count, 'archivos abiertos, 21 combinaciones con dos juegos de filtros; 42 salidas auditadas.', flush=True)


def main():
    accounts = json.loads((RUNTIME / 'access.json').read_text(encoding='utf-8'))
    with httpx.Client(base_url='http://127.0.0.1:8000', timeout=115, trust_env=False) as api, psycopg.connect(CFG['DATABASE_URL'], connect_timeout=5, autocommit=True) as db:
        health = api.get('/health?detalle=true').raise_for_status().json()
        assert all(health['servicios'][name] == 'ok' for name in ('fastapi','postgresql','redis','n8n'))
        print('Salud inicial:', health, '| PostgreSQL', db.execute('SHOW server_version').fetchone()[0], flush=True)
        assert db.execute('SELECT count(*) FROM reports WHERE id=%s', (EVIDENCE_ID,)).fetchone()[0] == 1
        print('Caso anterior persistió tras Stop/Start:', EVIDENCE_ID, flush=True)
        measured = db.execute('SELECT is_demo,count(*) FROM triage_baselines GROUP BY is_demo ORDER BY is_demo').fetchall()
        print('Líneas base registradas (is_demo, cantidad):', measured, flush=True)
        if sys.argv[1:] == ['exportaciones']:
            manager = next(account for account in accounts if account['role'] == 'gestor')
            token = api.post('/api/auth/login', json={k: manager[k] for k in ('username', 'password')}).raise_for_status().json()
            auth = {'Authorization': 'Bearer ' + token['access_token']}
            try:
                formats(api, db, auth)
            finally:
                print('Cierre de la sesión de prueba:', api.post('/api/auth/logout', headers=auth).status_code, flush=True)
            return
        redis = Redis.from_url(CFG['REDIS_URL'], decode_responses=True, socket_timeout=4)
        rid = routing_check(api, db, redis)
        headers = rights(api, db, rid, accounts)
        try:
            dashboard_check(api, db, headers['gestor'])
            formats(api, db, headers['gestor'])
            print('Salud final:', api.get('/health?detalle=true').raise_for_status().json(), flush=True)
        finally:
            for auth in headers.values():
                api.post('/api/auth/logout', headers=auth).raise_for_status()


if __name__ == '__main__':
    main()
