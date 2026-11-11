"""Configure Phase 2 adapters without creating a second fitting or inference engine."""
from __future__ import annotations

from math import isfinite

from src.training.settings import LocalParameters
from .contracts import SearchOptions


class ConfiguredSearch:
    """Delegate fitting, inference, caching and artifact publication to the existing adapter."""

    def __init__(self, base, options: SearchOptions) -> None:
        self.base, self.options, self.name = base, options, base.name

    def suggest(self, trial) -> dict:
        # Mapping order is not part of the canonical configuration hash.
        sampled = {name: self.options.space[name].suggest(trial, name) for name in sorted(self.options.space)}
        if self.name == "langflow":
            prompt, threshold = self.base.options[0]
            prompt, threshold = sampled.get("prompt", prompt), sampled.get("threshold", threshold)
            return {"prompt": prompt, "prompt_sha256": self.base.prompts[prompt].sha256, "threshold": threshold}
        return LocalParameters.model_validate({**self.base.parameters.model_dump(), **sampled}).model_dump(mode="json")

    def evaluate(self, train, validation, parameters: dict, scope: str, check_cancel) -> dict:
        """Keep F1 for existing reports and record the selected objective separately."""
        measured = self.base.evaluate(train, validation, parameters, scope, check_cancel)
        metrics = measured["metrics"]
        if self.options.metric == "penalized_f1":
            value = (metrics["f1_macro"] - self.options.critical_penalty * metrics["critical_fnr"]
                     - self.options.review_penalty * metrics["review_rate"])
        else:
            value = metrics.get(self.options.metric)
        if value is None or not isfinite(value):
            raise ValueError("La métrica objetivo carece de evidencia válida en este subconjunto.")
        return {**measured, "objective": float(value), "objective_name": self.options.metric}

    def publish(self, train, parameters: dict, directory) -> dict:
        return self.base.publish(train, parameters, directory)
