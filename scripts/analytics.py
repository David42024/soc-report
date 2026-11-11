"""Launch the analytical UI with external configuration and startup hash seed."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys

from src.utils.config import load_config
from src.utils.errors import AnalyticsError


def main() -> int:
    """Start Streamlit or validate its public configuration without services."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Validar configuración y catálogo sin iniciar servicios.")
    arguments = parser.parse_args()
    try:
        settings = load_config()
        if arguments.check:
            from src.data.catalog import DatasetCatalog
            from src.inference.services import SocApi
            catalog = DatasetCatalog(settings, SocApi(settings.api))
            print(f"Configuración válida. {len(catalog.sources)} fuentes registradas. Semilla {settings.seed}.")
            return 0
        environment = {**os.environ, "PYTHONHASHSEED": str(settings.seed)}
        return subprocess.call([sys.executable, "-m", "streamlit", "run", str(settings.path(settings.ui.entrypoint)),
                                "--server.address", settings.ui.host, "--server.port", str(settings.ui.port)],
                               cwd=settings.root, env=environment)
    except AnalyticsError as error:
        print(str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
