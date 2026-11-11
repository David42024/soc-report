"""Reproduce Phase 4 on published synthetic Phase 2 models and Validation."""
import argparse

from src.explainability.workspace import ExplanationWorkspace
from src.inference.services import SocApi
from src.utils.config import load_config
from src.utils.errors import AnalyticsError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True)
    options = parser.parse_args()
    try:
        settings = load_config()
        workspace = ExplanationWorkspace(settings, SocApi(settings.api))
        result = workspace.training.verified(options.run, "result.json")
        if result["partition"]["source"] != "sintetico":
            raise AnalyticsError("El comando técnico admite únicamente modelos sintéticos publicados.")
        for family in result["families"]:
            report = workspace._local(options.run, family, "validation", lambda _: None)
            print(f"{family} · {report['run_id']} · {report['summary']['cases']} casos de Validación · {report['external_requests']} llamadas externas")
    except AnalyticsError as error:
        print(str(error))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
