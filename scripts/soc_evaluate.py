"""Verify the Phase 3 evaluator on a completed synthetic Phase 2 run."""
from __future__ import annotations

import argparse

from src.evaluation.workspace import technical_evaluation
from src.utils.config import load_config
from src.utils.errors import AnalyticsError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="ID de una corrida técnica sintética de Fase 2.")
    args = parser.parse_args()
    try:
        reports, comparison = technical_evaluation(load_config(), args.run)
    except AnalyticsError as error:
        print(str(error))
        return 1
    for report in reports:
        metrics = report["metrics"]["overall"]
        print(f"Prueba técnica sintética {report['family']} · {report['run_id']} · n={report['rows']} · F1 macro={metrics['f1_macro']:.4f}")
    print(f"Comparación versionada {comparison['run_id']}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
