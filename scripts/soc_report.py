"""Generate authorized, versioned SOC scientific reports using existing JWT login."""
from __future__ import annotations

import argparse
from datetime import date
from getpass import getpass
import logging
import sys

from pydantic import SecretStr, ValidationError

from src.inference.services import SocApi
from src.reports.scientific import ReportRequest, SECTION_TITLES, TEMPLATES
from src.reports.workspace import ReportingWorkspace
from src.utils.config import load_config
from src.utils.errors import AnalyticsError
from src.utils.logging import configure_logging


def main() -> int:
    """Use existing identities and request no external classification."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", required=True)
    parser.add_argument("--template", choices=tuple(TEMPLATES), default="academico")
    parser.add_argument("--section", action="append", choices=tuple(SECTION_TITLES))
    parser.add_argument("--manifest")
    parser.add_argument("--experiment", action="append", default=[])
    parser.add_argument("--evaluation", action="append", default=[])
    parser.add_argument("--explanation", action="append", default=[])
    parser.add_argument("--desde", type=date.fromisoformat)
    parser.add_argument("--hasta", type=date.fromisoformat)
    args = parser.parse_args()
    api, session = None, None
    try:
        settings = load_config()
        configure_logging(settings)
        request = ReportRequest(template=args.template, sections=tuple(args.section or TEMPLATES[args.template].sections),
            manifest=args.manifest, experiments=tuple(args.experiment), evaluations=tuple(args.evaluation),
            explanations=tuple(args.explanation), desde=args.desde, hasta=args.hasta)
        api = SocApi(settings.api)
        session = api.login(args.username, SecretStr(getpass("Contraseña SOC: ")),
                            SecretStr(getpass("Segundo factor, si está activo: ")))
        workspace = ReportingWorkspace(settings, api)
        report = workspace.compose(request, session.token)
        workspace.publish(report, session.token)
        print(f"Informe generado en {workspace.directory / report.run_id}")
        print(f"Versión de evidencia {report.run_id}")
        return 0
    except (AnalyticsError, ValidationError) as error:
        message = str(error) if isinstance(error, AnalyticsError) else "Selección de informe inválida."
        print(message, file=sys.stderr)
        return 1
    finally:
        if session and api:
            try:
                api.logout(session.token)
            except AnalyticsError:
                logging.getLogger("soc_analytics.reporting").warning("No se confirmó el cierre de sesión en el backend")


if __name__ == "__main__":
    raise SystemExit(main())
