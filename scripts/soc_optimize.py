"""Run the controlled Phase 7 demonstration through the Phase 2 training engine."""
from __future__ import annotations

import argparse
import json

from src.optimization.workspace import default_options
from src.training.jobs import technical_run
from src.training.runs import JobSpec
from src.utils.config import load_config
from src.utils.errors import AnalyticsError
from src.optimization.contracts import SearchOptions


def main() -> int:
    """The CLI is synthetic/local only and cannot call a cloud provider."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--timeout", type=float)
    parser.add_argument("--sampler", choices=("tpe", "random"), default="tpe")
    args = parser.parse_args()
    settings = load_config()
    options = default_options(settings)
    try:
        options = SearchOptions.model_validate({**options.model_dump(mode="json"), "sampler": args.sampler,
            "timeout_seconds": options.timeout_seconds if args.timeout is None else args.timeout})
        spec = JobSpec(source="sintetico", target="tipo", seed=settings.seed if args.seed is None else args.seed,
            trials=settings.optimization.default_trials if args.trials is None else args.trials,
            models=("tfidf_logreg",), local=settings.training.local, optimization=options)
        identifier, result = technical_run(settings, spec)
    except (ValueError, AnalyticsError):
        parser.error("Revisa trials, semilla, tiempo y los límites configurados del servidor.")
    print(json.dumps({"phase": 7, "phase2_run": identifier, "completed": bool(result), "cloud_calls": 0,
                      "test_evaluations": result["test_evaluations"] if result else None}))
    if result:
        family = result["families"]["tfidf_logreg"]
        print(json.dumps({"studies": len(family["folds"]), "trials": sum(len(fold["trials"]) for fold in family["folds"]),
                          "external_f1": family["summary"], "selected_parameters": family["validation_selection"]["winner"]["configuration"]}))
        print(settings.path(settings.runs_dir) / settings.training.directory / identifier / "result.json")
    return 0 if result else 1


if __name__ == "__main__":
    raise SystemExit(main())
