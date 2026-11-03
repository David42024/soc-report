"""Exercise the measurement workflow in an isolated, disposable PostgreSQL database."""
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import dotenv_values
import psycopg
from psycopg import sql

from backend.config import ROOT, Settings
import test_impact_study


class LiveImpactTests(test_impact_study.OperationalImpactTests):
    def settings(self, path):
        url = dotenv_values(ROOT / '.env')['DATABASE_URL']
        parsed = urlsplit(url)
        self.assertEqual((parsed.hostname, parsed.port), ('127.0.0.1', 5434))
        name = 'soc_impact_test_' + uuid4().hex
        connection = psycopg.connect(url, connect_timeout=5, autocommit=True)
        self.addCleanup(connection.close)
        connection.execute(sql.SQL('CREATE DATABASE {} TEMPLATE template0').format(sql.Identifier(name)))
        self.addCleanup(connection.execute, sql.SQL('DROP DATABASE {}').format(sql.Identifier(name)))
        return Settings(database_url=parsed._replace(path='/' + name).geturl())
