"""Aggregate observable XAI findings without merging different cohorts."""
from collections import Counter


def aggregate(cases: list[dict]) -> dict:
    """Count cases, evidence issues, relevant terms and measured perturbations."""
    terms, patterns = Counter(), Counter()
    issues = Counter()
    stability = []
    for case in cases:
        if "linear" in case:
            relevant = {row["feature"] for row in case["linear"]["terms"] if row["contribution"] > 0}
            label = case["linear"]["predicted"]
        else:
            relevant = {row["quote"].casefold() for row in case["evidence"]["claims"] if not row["negated"]}
            label = case["evidence"]["classification"]["tipo"]
        outcome = "sin_referencia" if case.get("correct") is None else "acierto" if case["correct"] else "error"
        patterns[(label, outcome)] += 1
        terms.update((word, label, outcome) for word in relevant)
        if "evidence" in case:
            issues.update(item["code"] for item in case["evidence"]["validation"]["issues"])
            issues.update("campo_sin_apoyo_" + field for field in case["evidence"]["unsupported_fields"])
            issues.update("cita_sin_coincidencia_literal_original" for item in case["evidence"].get("original_quotes") or []
                          if not item["exists"])
        if "reliability" in case:
            stability.extend(case["reliability"]["stability"])
    return {"cases": len(cases), "terms": [{"term": term, "class": label, "outcome": outcome, "cases": n}
            for (term, label, outcome), n in terms.most_common()],
            "patterns": [{"class": label, "outcome": outcome, "cases": n} for (label, outcome), n in sorted(patterns.items())],
            "inconsistencies": dict(issues), "stability": {"variants": len(stability),
                "prediction_same": sum(row["prediction_same"] for row in stability),
                "same_fraction": sum(row["prediction_same"] for row in stability) / len(stability) if stability else None}}
