"""Run the reproducible local synthetic test of the SOC training protocol."""
from __future__ import annotations

import argparse

from src.training.jobs import technical_run
from src.training.runs import JobSpec
from src.utils.config import load_config
from src.utils.errors import AnalyticsError


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, help="Trials por fold externo para cada modelo.")
    parser.add_argument("--seed", type=int, help="Semilla de la ejecución técnica.")
    args = parser.parse_args()
    try:
        settings = load_config()
        seed = settings.seed if args.seed is None else args.seed
        trials = settings.training.default_trials_per_fold if args.trials is None else args.trials
        if not 0 <= seed < 2**32 or not 1 <= trials <= settings.training.max_trials_per_fold:
            parser.error("Semilla o número de trials fuera de los límites configurados.")
        spec = JobSpec(source="sintetico", target="tipo", seed=seed, trials=trials,
                       models=("tfidf_logreg", "tfidf_svm"), local=settings.training.local)
        run_id, result = technical_run(settings, spec)
        print(f"Prueba técnica sintética {run_id}")
        if not result:
            print("La ejecución terminó con error. Consulta state.json en el directorio de la corrida.")
            return 1
        for model, metrics in result["families"].items():
            print(f"{model} 5 folds externos, F1 macro media {metrics['summary']['mean']:.4f}")
        print(f"Solicitudes LangFlow {result['flow_calls']}. Evaluaciones de Prueba {result['test_evaluations']}.")
        print(settings.path(f"{settings.runs_dir}/{settings.training.directory}/{run_id}/result.json"))
        return 0
    except AnalyticsError as error:
        print(str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
