"""Run the JDBC exercise against the SOC database or a temporary PostgreSQL instance."""

import argparse
from collections import Counter
import csv
import os
from pathlib import Path
import secrets
import shutil
import socket
import subprocess
import tempfile
from urllib.parse import unquote, urlsplit


LAB = Path(__file__).resolve().parent
RESULTS = LAB.parents[1] / "tmp" / "jmeter"
EXPECTED = Counter({"Primeros 1000 reportes": 24, "Títulos de todos los reportes": 24})


def run(*command, env=None, timeout=60):
    subprocess.run(command, check=True, stdin=subprocess.DEVNULL, env=env, timeout=timeout)


def check_results(path):
    with path.open(encoding="utf-8", newline="") as report:
        samples = list(csv.DictReader(report))
    counts = Counter(sample["label"] for sample in samples)
    failures = [sample for sample in samples if sample["success"] != "true"]
    if failures:
        first = failures[0]
        detail = first["failureMessage"] or first["responseMessage"]
        raise RuntimeError(f'{len(failures)} muestras fallidas. {first["label"]}: {detail[:300]}')
    if counts != EXPECTED:
        raise RuntimeError(f"Se esperaban 24 muestras por consulta. Se obtuvo {dict(counts)}.")


def execute_plan(args, output, url, username, password, *properties):
    env = {**os.environ, "SOC_JMETER_DB_PASSWORD": password}
    results_file = output / "resultados.jtl"
    dashboard = output / "informe"
    jmeter_options = (
        "-t", LAB / "soc-jdbc.jmx", f"-Juser.classpath={args.driver}",
        f"-Jsoc.jdbc.url={url}", f"-Jsoc.jdbc.user={username}", *properties,
        "-Jjmeter.save.saveservice.output_format=csv", "-Jjmeter.save.saveservice.print_field_names=true",
        "-Jjmeter.save.saveservice.response_data=false", "-Jjmeter.save.saveservice.response_data.on_error=false",
        "-j", output / "jmeter.log",
    )
    jar = args.jmeter_home / "bin" / "ApacheJMeter.jar"
    if args.gui:
        javaw = Path(args.java).with_name("javaw.exe")
        with (output / "inicio-gui.log").open("wb") as log:
            subprocess.Popen([javaw, "-Duser.language=es", "-jar", jar, *jmeter_options,
                              f"-Jsoc.jdbc.gui_results={results_file.as_posix()}"],
                             stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, env=env)
        return

    run(args.java, "-Djava.awt.headless=true", "-jar", jar, "-n", *jmeter_options,
        "-l", results_file, "-e", "-o", dashboard, env=env)
    check_results(results_file)
    if not (dashboard / "index.html").is_file():
        raise RuntimeError("JMeter terminó sin generar el informe HTML.")


def run_soc(args, output):
    from dotenv import dotenv_values
    import psycopg

    config = dotenv_values(LAB.parents[1] / ".env")
    dsn = os.environ.get("DATABASE_URL", config.get("DATABASE_URL") or "")
    url = urlsplit(dsn)
    if url.scheme not in {"postgresql", "postgres"} or url.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("DATABASE_URL debe apuntar al PostgreSQL local de SOC.")
    if not url.username or url.password is None or not url.path.strip("/") or url.query:
        raise ValueError("DATABASE_URL debe incluir el usuario, contraseña y nombre de la base, sin opciones adicionales.")

    with psycopg.connect(dsn, connect_timeout=5, options="-c default_transaction_read_only=on") as connection:
        version, read_only, count = connection.execute(
            "SELECT current_setting('server_version'), current_setting('transaction_read_only'), "
            "(SELECT count(*) FROM public.reports)"
        ).fetchone()
    if read_only != "on":
        raise RuntimeError("La conexión de verificación no está en modo de solo lectura.")
    print(f"PostgreSQL {version}. La tabla public.reports contiene {count} reportes al iniciar.", flush=True)

    host = "[::1]" if url.hostname == "::1" else url.hostname
    jdbc_url = f"jdbc:postgresql://{host}:{url.port or 5432}{url.path}"
    execute_plan(args, output, jdbc_url, unquote(url.username), unquote(url.password),
                 "-Jsoc.jdbc.table=public.reports", "-Jsoc.jdbc.expected_reports=[0-9]{1,3}|1000",
                 "-Jsoc.jdbc.expected_titles=[0-9]+")


def run_demo(args, output):
    pg_ctl = shutil.which("pg_ctl")
    if not pg_ctl:
        raise RuntimeError("Agrega la carpeta bin de PostgreSQL nativo a PATH.")
    pg_bin = Path(pg_ctl).parent
    admin = secrets.token_urlsafe(24)
    reader = secrets.token_urlsafe(24)
    pg_env = {**os.environ, "SOC_JMETER_DB_PASSWORD": reader, "PGPASSWORD": admin, "PGCLIENTENCODING": "UTF8"}
    with tempfile.TemporaryDirectory(prefix="postgres-", dir=output) as staging:
        data = Path(staging) / "data"
        password_file = Path(staging) / "bootstrap-password"
        password_file.write_text(admin + "\n", encoding="ascii")
        try:
            run(pg_bin / "initdb.exe", "-D", data, "-U", "postgres", "--auth=scram-sha-256",
                "--encoding=UTF8", "--no-locale", "--pwfile", password_file)
        finally:
            password_file.unlink()

        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            port = str(listener.getsockname()[1])
        try:
            run(pg_ctl, "start", "-D", data, "-w", "-t", "20", "-l", output / "postgres.log",
                "-o", f"-h 127.0.0.1 -p {port}")
            psql = (pg_bin / "psql.exe", "-X", "-w", "-v", "ON_ERROR_STOP=1",
                    "-h", "127.0.0.1", "-p", port, "-U", "postgres")
            run(*psql, "-d", "postgres", "-c", "CREATE DATABASE prueba", env=pg_env)
            run(*psql, "-d", "prueba", "--single-transaction", "-f", LAB / "seed.sql", env=pg_env)
            print("PostgreSQL listo con 1200 reportes sintéticos. Ejecutando JMeter.", flush=True)
            execute_plan(args, output, f"jdbc:postgresql://127.0.0.1:{port}/prueba", "soc_jmeter_reader", reader)
        finally:
            if (data / "postmaster.pid").exists():
                run(pg_ctl, "stop", "-D", data, "-m", "fast", "-w", "-t", "20")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--soc", action="store_true", help="Usa el PostgreSQL local configurado en DATABASE_URL.")
    parser.add_argument("--gui", action="store_true", help="Abre el plan en la interfaz gráfica. Requiere --soc.")
    parser.add_argument("--jmeter-home", type=Path, required=True)
    parser.add_argument("--driver", type=Path, required=True, help="Archivo JAR de pgJDBC")
    parser.add_argument("--java", type=Path, default=shutil.which("java"))
    args = parser.parse_args()
    if args.gui and not args.soc:
        parser.error("--gui requiere --soc.")
    args.jmeter_home = args.jmeter_home.resolve()
    args.driver = args.driver.resolve()
    for executable in (args.java, args.jmeter_home / "bin" / "ApacheJMeter.jar", args.driver):
        if not executable or not Path(executable).is_file():
            parser.error(f"No se encontró el archivo requerido: {executable}")

    RESULTS.mkdir(parents=True, exist_ok=True)
    target = "soc-" if args.soc else ""
    mode = "gui" if args.gui else "jdbc"
    output = Path(tempfile.mkdtemp(prefix=f"{target}{mode}-", dir=RESULTS))
    print(f"Resultados de la ejecución: {output}", flush=True)
    if args.soc:
        run_soc(args, output)
    else:
        run_demo(args, output)
    if args.gui:
        print("Iniciando JMeter GUI. Pulsa Ctrl+R en la ventana para iniciar la prueba.")
        return
    print("48 muestras JDBC correctas.")
    print(f"Informe: {output / 'informe' / 'index.html'}")


if __name__ == "__main__":
    main()
