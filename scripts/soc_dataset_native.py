"""Optional Windows evaluation using installed PostgreSQL and n8n binaries."""
import os
from pathlib import Path
from secrets import token_urlsafe
from shutil import which
import socket
import subprocess
from time import monotonic, sleep

import httpx
import psycopg

from scripts.soc_dataset_stack import WORKFLOW_ID, workflow_files


def installed(name):
    path = which(name)
    if not path:
        raise ValueError(f"Falta {name} en PATH para la evaluación nativa.")
    return Path(path)


def available_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class NativeStack:
    def __init__(self, directory):
        self.directory = directory
        self.pg_bin = installed("pg_ctl").parent
        node = installed("node")
        n8n = installed("n8n.cmd").parent / "node_modules/n8n/bin/n8n"
        if not n8n.is_file():
            raise ValueError("No se encontró el punto de entrada de la instalación npm de n8n.")
        self.n8n = (str(node), str(n8n))
        self.pg_data = directory / "pg-native"
        self.router = None
        self.pg_started = False
        credentials = directory / "native.secret"
        if not credentials.exists():
            credentials.write_text(f"{token_urlsafe(32)}\n{token_urlsafe(32)}\n", encoding="ascii")
        self.password, encryption_key = credentials.read_text(encoding="ascii").splitlines()
        self.n8n_port = available_port()
        self.pg_port = None
        self.environment = {
            # Drop inherited n8n-specific settings so the original installation stays isolated.
            **{key: value for key, value in os.environ.items()
               if not key.startswith(("N8N_", "DB_", "EXECUTIONS_", "QUEUE_", "LANGFLOW_"))
               and key not in {"WEBHOOK_URL", "GENERIC_TIMEZONE"}},
            "N8N_USER_FOLDER": str(directory / "n8n-native"),
            "N8N_ENCRYPTION_KEY": encryption_key,
            "N8N_LISTEN_ADDRESS": "127.0.0.1",
            "N8N_HOST": "127.0.0.1",
            "N8N_PORT": str(self.n8n_port),
            "N8N_PROTOCOL": "http",
            "N8N_DIAGNOSTICS_ENABLED": "false",
            "N8N_VERSION_NOTIFICATIONS_ENABLED": "false",
            "N8N_TEMPLATES_ENABLED": "false",
            "N8N_RUNNERS_ENABLED": "false",
            "N8N_SECURE_COOKIE": "false",
            "EXECUTIONS_DATA_SAVE_ON_ERROR": "none",
            "EXECUTIONS_DATA_SAVE_ON_SUCCESS": "none",
            "DB_TYPE": "sqlite",
        }
        self.n8n_version = self.command(*self.n8n, "--version").splitlines()[-1]

    def command(self, *args, capture=True):
        try:
            result = subprocess.run(
                args, env=self.environment, stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE if capture else subprocess.DEVNULL,
                stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace",
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=130, check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise RuntimeError(f"No respondió {Path(args[0]).name}.") from None
        if result.returncode:
            action = args[2] if args[:2] == self.n8n else args[1]
            raise RuntimeError(f"Falló {Path(args[0]).name} {action} (código {result.returncode}).")
        return (result.stdout or "").strip()

    def start(self, api_port, internal, webhook):
        if not (self.pg_data / "PG_VERSION").exists():
            password_file = self.directory / "pg-init.secret"
            password_file.write_text(self.password + "\n", encoding="ascii")
            try:
                self.command(str(self.pg_bin / "initdb.exe"), "-D", str(self.pg_data), "-U", "soc_evaluation",
                             "-A", "scram-sha-256", "--encoding=UTF8", "--no-locale", "--pwfile", str(password_file))
            finally:
                password_file.unlink(missing_ok=True)
        self.pg_port = available_port()
        self.pg_started = True
        self.command(str(self.pg_bin / "pg_ctl.exe"), "start", "-D", str(self.pg_data), "-w", "-t", "60",
                     "-l", str(self.directory / "postgres.log"), "-o", f"-h 127.0.0.1 -p {self.pg_port}", capture=False)
        with psycopg.connect(host="127.0.0.1", port=self.pg_port, user="soc_evaluation",
                             password=self.password, dbname="postgres", autocommit=True, connect_timeout=5) as db:
            if db.execute("SELECT 1 FROM pg_database WHERE datname='soc_evaluation'").fetchone() is None:
                db.execute("CREATE DATABASE soc_evaluation")
        staging = self.directory / "import"
        with workflow_files(staging, api_port, "127.0.0.1", internal, webhook):
            self.command(*self.n8n, "import:credentials", f"--input={staging / 'credentials.json'}")
            self.command(*self.n8n, "import:workflow", f"--input={staging / 'workflow.json'}")
            self.command(*self.n8n, "update:workflow", f"--id={WORKFLOW_ID}", "--active=true")
        self.start_router()
        return self.pg_port, self.n8n_port

    def stop_router(self):
        if self.router and self.router.poll() is None:
            self.router.terminate()
            self.router.wait(15)

    def start_router(self):
        with (self.directory / "n8n.log").open("ab") as log:
            self.router = subprocess.Popen(
                [*self.n8n, "start"], env=self.environment, stdin=subprocess.DEVNULL,
                stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW,
            )
        limit = monotonic() + 70
        with httpx.Client(timeout=2, trust_env=False) as client:
            while self.router.poll() is None and monotonic() < limit:
                try:
                    if client.get(f"http://127.0.0.1:{self.n8n_port}/healthz/readiness").is_success:
                        return
                except httpx.RequestError:
                    pass
                sleep(0.3)
        raise RuntimeError(f"n8n nativo no inició. Consulta {self.directory / 'n8n.log'}.")

    def close(self):
        try:
            self.stop_router()
        finally:
            if self.pg_started:
                self.command(str(self.pg_bin / "pg_ctl.exe"), "stop", "-D", str(self.pg_data), "-m", "fast", "-w")
