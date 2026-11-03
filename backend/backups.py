"""Verified local backups used by schema upgrades."""
import os
import sqlite3
import subprocess
from contextlib import closing
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.engine import make_url

from .config import ROOT


def backup_database(database):
    directory = (ROOT / '.venv/soc-runtime/migration-backups' if database.url
                 else database.path.parent / 'migration-backups')
    directory.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    name = f'soc-{stamp}-{uuid4().hex[:8]}'
    destination = directory / (name + ('.dump' if database.url else '.sqlite3'))
    staging = destination.with_suffix(destination.suffix + '.partial')
    try:
        if database.url:
            dump_postgres(database.url, staging)
        else:
            with closing(sqlite3.connect(database.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=10)) as source:
                with closing(sqlite3.connect(staging)) as copy:
                    source.backup(copy)
                    if copy.execute('PRAGMA integrity_check').fetchall() != [('ok',)]:
                        raise RuntimeError('La copia SQLite no superó la verificación.')
        staging.replace(destination)
    finally:
        staging.unlink(missing_ok=True)
    return destination


def dump_postgres(url, destination):
    target = make_url(url)
    compose = ROOT / '.venv/soc-runtime/compose.env'
    if target.host == '127.0.0.1' and target.port == 5434 and compose.is_file():
        # Use the same PostgreSQL major version as the project's container.
        docker = ['docker', 'compose', '--env-file', str(compose), 'exec', '-T', 'postgres']
        command = docker + ['sh', '-c', 'IFS= read -r PGPASSWORD; export PGPASSWORD; exec pg_dump "$@"',
                            'pg_dump', '-h', '127.0.0.1', '-U', target.username, '-d', target.database]
        credentials = ((target.password or '') + '\n').encode()
        environment = None
    else:
        docker = []
        command = ['pg_dump']
        credentials = None
        environment = {**os.environ, 'PGHOST': target.host or '', 'PGPORT': str(target.port or 5432),
                       'PGUSER': target.username or '', 'PGDATABASE': target.database or '',
                       'PGPASSWORD': target.password or ''}
        for key in ('sslmode', 'sslrootcert', 'sslcert', 'sslkey'):
            if key in target.query:
                environment['PG' + key.upper()] = str(target.query[key])
    try:
        with destination.open('wb') as output:
            subprocess.run(command + ['--format=custom', '--no-password'], input=credentials,
                           stdout=output, stderr=subprocess.PIPE, env=environment, check=True, timeout=300, cwd=ROOT)
        # A child process inherits the OS file position, which buffered reads may advance.
        with destination.open('rb', buffering=0) as archive:
            if archive.read(5) != b'PGDMP':
                raise RuntimeError('El volcado PostgreSQL no tiene el formato custom esperado.')
            archive.seek(0)
            catalog = subprocess.run(docker + ['pg_restore', '--list'], stdin=archive, capture_output=True,
                                     check=True, timeout=60, cwd=ROOT).stdout
        if not catalog.strip():
            raise RuntimeError('El volcado PostgreSQL no tiene un catálogo válido.')
    except (OSError, subprocess.SubprocessError):
        raise RuntimeError('Falló el respaldo o su validación en PostgreSQL. Se detuvo la migración.') from None
