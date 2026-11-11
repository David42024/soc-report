"""Exact local linear contributions and interventional Shapley values in TF-IDF."""
from __future__ import annotations

import re

import numpy as np
from sklearn.pipeline import Pipeline

from src.explainability.evidence import text_hash
from src.explainability.settings import ExplainabilitySettings
from src.utils.errors import AnalyticsError


class LinearTextExplainer:
    """Use the frozen vectorizer and a Development-only background mean."""

    def __init__(self, model: Pipeline, background: list[str], policy: ExplainabilitySettings) -> None:
        self.model, self.policy = model, policy
        self.vectorizer, self.classifier = model.named_steps["tfidf"], model.named_steps["classifier"]
        v = self.vectorizer
        if (v.analyzer != "word" or v.preprocessor is not None or v.tokenizer is not None or v.strip_accents is not None
                or not v.lowercase or re.compile(v.token_pattern).groups or not background):
            raise AnalyticsError("La atribución requiere el vectorizador de palabras compatible y un fondo de Desarrollo.")
        self.features = v.get_feature_names_out()
        self.mean = np.asarray(v.transform(background).mean(axis=0)).ravel()
        self.classes = list(map(str, model.classes_))

    def _coefficients(self, label: str) -> tuple[np.ndarray, float]:
        index = self.classes.index(label)
        if len(self.classes) == 2:
            return (self.classifier.coef_[0], float(self.classifier.intercept_[0])) if index == 1 else (
                np.zeros_like(self.classifier.coef_[0]), 0.0)
        return self.classifier.coef_[index], float(self.classifier.intercept_[index])

    def explain(self, text: str, focus: str | None = None) -> dict:
        """Reconstruct the selected class's contrast against its strongest rival."""
        x = self.vectorizer.transform([text]).toarray()[0]
        values = {label: float(weights @ x + intercept) for label in self.classes
                  for weights, intercept in (self._coefficients(label),)}
        predicted = str(self.model.predict([text])[0])
        selected = focus or predicted
        if selected not in self.classes:
            raise AnalyticsError("La clase seleccionada no pertenece al modelo publicado.")
        rival = max((label for label in self.classes if label != selected), key=values.get)
        weights, intercept = self._coefficients(selected)
        other, other_intercept = self._coefficients(rival)
        coefficients, intercept = weights - other, intercept - other_intercept
        contributions = coefficients * x
        shap = coefficients * (x - self.mean)
        base = float(intercept + coefficients @ self.mean)
        score = values[selected] - values[rival]
        residual = abs(score - (base + float(shap.sum())))
        if residual > self.policy.tolerance:
            raise AnalyticsError("La suma de atribuciones no reconstruye el contraste del modelo.")
        rows = [{"feature": str(self.features[i]), "tfidf": float(x[i]), "coefficient": float(coefficients[i]),
                 "contribution": float(contributions[i]), "shap": float(shap[i]), "present": bool(x[i])}
                for i in range(len(self.features))]
        present = sorted((row for row in rows if row["present"]), key=lambda row: (-abs(row["contribution"]), row["feature"]))
        shap_top = sorted(rows, key=lambda row: (-abs(row["shap"]), row["feature"]))[:self.policy.top_features]
        tokens = self._tokens(text, present)
        return {"method": "shap_lineal_intervencional_tfidf", "input_sha256": text_hash(text), "predicted": predicted,
                "focus": selected, "rival": rival, "unit": "log_odds" if hasattr(self.model, "predict_proba") else "margen_svm",
                "score": score, "intercept": float(intercept), "baseline": base, "shap_sum": float(shap.sum()),
                "reconstruction_error": residual, "contribution_sum": float(contributions.sum()),
                "feature_count": len(rows), "present_count": len(present), "terms": present[:self.policy.top_features],
                "shap_terms": shap_top, "omitted_shap_sum": float(shap.sum() - sum(row["shap"] for row in shap_top)),
                "token_projection_residual": float(contributions.sum() - sum(item["weight"] for item in tokens)),
                "tokens": tokens, "limitation": "Las unidades son del contraste lineal entre clases. El juego Shapley sustituye características TF-IDF por su media de Desarrollo e ignora sus dependencias. Incluye efectos de términos ausentes."}

    def _tokens(self, text: str, terms: list[dict]) -> list[dict]:
        matches = list(re.finditer(self.vectorizer.token_pattern, text))
        words = [match.group().lower() for match in matches]
        weights = np.zeros(len(words))
        for term in terms:
            parts = term["feature"].split(" ")
            found = [i for i in range(len(words) - len(parts) + 1) if words[i:i + len(parts)] == parts]
            for offset in found:
                weights[offset:offset + len(parts)] += term["contribution"] / (len(found) * len(parts))
        return [{"start": match.start(), "end": match.end(), "text": match.group(), "weight": float(weight)}
                for match, weight in zip(matches, weights)]

    def reliability(self, text: str, report: dict) -> dict:
        """Evaluate bounded local perturbations without using the sealed test set."""
        focus = report["focus"]
        variants = {"mayusculas": text.upper(), "espacios": re.sub(r"\s+", "  ", text)}
        base_terms = {item["feature"] for item in report["terms"]}
        results = []
        for name, variant in variants.items():
            altered = self.explain(variant, focus)
            changed_terms = {item["feature"] for item in altered["terms"]}
            results.append({"perturbation": name, "prediction_same": altered["predicted"] == report["predicted"],
                            "score_change": altered["score"] - report["score"],
                            "term_jaccard": len(base_terms & changed_terms) / len(base_terms | changed_terms) if base_terms | changed_terms else None})
        positive = sorted((item for item in report["tokens"] if item["weight"] > 0), key=lambda item: -item["weight"])
        if positive:
            token = positive[0]
            altered_text = text[:token["start"]] + " " + text[token["end"]:]
            altered = self.explain(altered_text, focus)
            deletion = {"start": token["start"], "end": token["end"], "quote": text[token["start"]:token["end"]],
                        "score_drop": report["score"] - altered["score"], "prediction_changed": altered["predicted"] != report["predicted"]}
        else:
            deletion = None
        return {"scope": "experimento_local_desarrollo_validacion", "external_requests": 0, "stability": results,
                "deletion": deletion, "limitation": "La eliminación puede alterar significado, normalización y n-gramas. La sensibilidad mide el modelo local y requiere interpretación humana."}
