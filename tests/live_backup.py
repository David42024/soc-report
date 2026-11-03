"""Restore a SOC backup into a disposable database on the project's PostgreSQL 16."""
import subprocess
import unittest
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg
from dotenv import dotenv_values
from psycopg import sql

from backend.backups import backup_database
from backend.config import ROOT, Settings
from backend.db import Database


class LiveBackupTests(unittest.TestCase):
    def test_custom_backup_restores_into_temporary_postgresql(self):
        url = dotenv_values(ROOT / '.env')['DATABASE_URL']
        parsed = urlsplit(url)
        self.assertEqual((parsed.hostname, parsed.port), ('127.0.0.1', 5434))
        db = Database(Settings(database_url=url))
        self.addCleanup(db.engine.dispose)
        name = 'soc_restore_' + uuid4().hex
        target = parsed._replace(path='/' + name).geturl()
        compose = ['docker', 'compose', '--env-file', str(ROOT / '.venv/soc-runtime/compose.env'),
                   'exec', '-T', 'postgres']
        with psycopg.connect(url, autocommit=True, connect_timeout=5) as source:
            report = source.execute('SELECT id,titulo FROM reports ORDER BY recibido_at LIMIT 1').fetchone()
            archive = backup_database(db)
            self.addCleanup(archive.unlink, missing_ok=True)
            source.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
            try:
                with archive.open('rb') as stream:
                    result = subprocess.run(compose + ['sh', '-c', 'PGPASSWORD="$POSTGRES_PASSWORD" exec pg_restore '
                                                        '--exit-on-error --no-owner -h 127.0.0.1 -U "$POSTGRES_USER" -d "$1"',
                                                        'pg_restore', name], stdin=stream, capture_output=True,
                                            timeout=90, cwd=ROOT)
                self.assertEqual(result.returncode, 0, 'pg_restore no pudo reconstruir la base temporal')
                with psycopg.connect(target, connect_timeout=5) as restored:
                    if report:
                        self.assertTrue(restored.execute('SELECT id,titulo FROM reports WHERE id=%s', (report[0],)).fetchone() == report,
                                        'El caso de referencia no coincide con el origen')
                    for table in ('reports', 'assignments', 'audit_log'):
                        self.assertIsNotNone(restored.execute('SELECT to_regclass(%s)', (table,)).fetchone()[0])
                    with self.assertRaises(psycopg.Error):
                        restored.execute('DELETE FROM audit_log WHERE false')
            finally:
                source.execute(sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
