"""Authenticated orchestration for aggregate previews and atomic report publication."""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
import logging
from pathlib import Path
from tempfile import TemporaryDirectory

from pydantic import SecretStr

from src.data.manifest import ManifestStore, VERSION_ID
from src.data.models import content_hash
from src.data.revisions import operation_identity
from src.evaluation.store import EvaluationStore
from src.explainability.store import ExplanationStore
from src.inference.services import SocApi
from src.reports.composition import (
    data_section, evaluation_section, explanation_section, operational_section, training_section,
)
from src.reports.exporters import export_all, render_figure, snapshot_digest, snapshot_payload
from src.reports.scientific import ReportRequest, ReportSnapshot
from src.training.runs import RunStore
from src.utils.config import AnalyticsSettings
from src.utils.errors import AnalyticsError, ServiceError
from src.utils.reproducibility import software_versions

LOGGER = logging.getLogger("soc_analytics.reporting")


class ReportingWorkspace:
    """Reuse existing stores and API permissions without opening sealed source rows."""

    def __init__(self, settings: AnalyticsSettings, api: SocApi) -> None:
        self.settings, self.api = settings, api
        self.manifests = ManifestStore(settings)
        self.training = RunStore(settings)
        self.evaluations = EvaluationStore(settings)
        self.explanations = ExplanationStore(settings)
        self.directory = settings.path(Path(settings.runs_dir) / settings.reporting.directory)

    def _authorize(self, token: SecretStr) -> None:
        if not self.api.me(token).can("report_export"):
            raise ServiceError("Tu rol no permite exportar informes del SOC.", 403)

    def catalog(self, token: SecretStr) -> dict:
        """List version identifiers and aggregate status for existing evidence."""
        self._authorize(token)
        self.api.audit_event(token, "consultar_informes")
        return {
            "manifests": [row["Versión"] for row in self.manifests.list()],
            "experiments": [row for row in self.training.versions() if row["status"] == "completo"],
            "evaluations": [row for row in self.evaluations.list() if row["status"] == "completa"],
            "explanations": [{key: row[key] for key in ("run_id", "mode", "source")}
                             for row in self.explanations.records()],
        }

    def _check_selection(self, request: ReportRequest) -> None:
        for selections in (request.experiments, request.evaluations, request.explanations):
            if len(selections) > self.settings.reporting.max_selections or len(set(selections)) != len(selections):
                raise AnalyticsError("Selecciona versiones únicas dentro del máximo configurado.")
        if len(set(request.sections)) != len(request.sections):
            raise AnalyticsError("Selecciona cada sección una sola vez.")

    def compose(self, request: ReportRequest, token: SecretStr) -> ReportSnapshot:
        """Freeze selected archived results and an optional operational API summary."""
        self._authorize(token)
        self._check_selection(request)
        identifier, date = operation_identity()
        self.api.audit_event(token, "consultar_informes", run_id=identifier)
        manifest = json.loads(self.manifests.read(request.manifest)) if request.manifest and "datos" in request.sections else None
        training = ([self.training.verified(key, "result.json") for key in request.experiments]
                    if "entrenamiento" in request.sections else [])
        evaluations = ([self.evaluations.result(key) for key in request.evaluations]
                       if "evaluacion" in request.sections else [])
        explanations = ([self.explanations.read(key) for key in request.explanations]
                        if "explicabilidad" in request.sections else [])
        comparisons = self.evaluations.comparisons() if evaluations else []
        summary = None
        if "operacion" in request.sections:
            try:
                summary = self.api.dashboard(token, request.desde, request.hasta)
                _validate_dashboard(summary)
            except ServiceError as error:
                if error.status_code in (401, 403):
                    raise
                summary = None
                LOGGER.warning("Tablero no disponible durante la composición de informe")
        compact = request.template == "ejecutivo"
        builders = {
            "datos": lambda: data_section(manifest, compact),
            "entrenamiento": lambda: training_section(training),
            "evaluacion": lambda: evaluation_section(evaluations, comparisons),
            "explicabilidad": lambda: explanation_section(explanations),
            "operacion": lambda: operational_section(summary, compact),
        }
        sections = tuple(builders[name]() for name in request.sections)
        provenance = [
            ("Semilla global", str(self.settings.seed)),
            ("Configuración analítica SHA-256", content_hash(self.settings.model_dump(mode="json"))),
            ("Política de figuras", f"{self.settings.figures.dpi} DPI, "
             f"{self.settings.reporting.figure_width_inches} × {self.settings.reporting.figure_height_inches} pulgadas"),
        ]
        provenance.extend((f"Versión de software · {name}", version)
                          for name, version in software_versions(self.settings.software + ("weasyprint", "python-docx", "openpyxl")).items())
        references = [*([manifest] if manifest else []), *training, *evaluations, *explanations]
        for report in references:
            key = report["run_id"]
            provenance.append(("Evidencia " + key, report["content_sha256"]))
            for field in ("dataset_sha256", "phase2_run_id", "model_sha256", "current_prompt_reference_sha256",
                          "configuration_sha256", "background_sha256", "reference"):
                if report.get(field) is not None:
                    provenance.append((key + " · " + field, str(report[field])))
        for report in training:
            key = report["run_id"]
            provenance.append((key + " · dataset SHA-256", report["partition"]["source_sha256"]))
            for family, evidence in report["families"].items():
                artifact = evidence["artifact"]
                if artifact.get("sha256"):
                    provenance.append((key + " · " + family + " · modelo SHA-256", artifact["sha256"]))
                for provider, model in artifact.get("configured_models", {}).items():
                    if provider in ("groq", "gemini"):
                        provenance.append((key + " · modelo configurado " + provider, model))
        if manifest:
            for source in manifest["content"]["sources"]:
                provenance.append(("Dataset " + source["id"] + " · SHA-256", source["sha256"] or "No disponible"))
        if summary is not None:
            # Bind only exported aggregates. Team names and asset identifiers never enter provenance.
            provenance.append(("Tablero agregado SHA-256", content_hash(asdict(operational_section(summary, compact)))))
        conclusions = [
            f"Se incluyeron {len(sections)} secciones con "
            f"{sum(len(section.tables) for section in sections)} tablas y "
            f"{sum(len(section.figures) for section in sections)} figuras.",
            f"{sum(any(note.startswith('Pendiente.') for note in section.notes) for section in sections)} "
            "secciones carecen de evidencia seleccionada o accesible.",
        ]
        synthetic = sum(report.get("source", report.get("request", {}).get("source")) == "sintetico"
                        for report in [*training, *evaluations, *explanations])
        conclusions.append(f"{synthetic} resultados seleccionados corresponden a pruebas sintéticas identificadas.")
        if manifest:
            holdout = manifest["content"]["holdout"]
            ready = sum(holdout["test_ready_by_target"].values())
            conclusions.append(f"El holdout revisado está disponible para {ready} de "
                               f"{len(holdout['test_ready_by_target'])} objetivos. "
                               f"Persisten {holdout['preparation_pending']} decisiones pendientes de preparación.")
            failures = sum(row["status"] == "Error" for row in manifest["content"]["quality"])
            conclusions.append(f"El inventario conserva {failures} controles de calidad en estado de error.")
        if evaluations:
            conclusions.append(f"Se conservaron {len(evaluations)} evaluaciones publicadas y sus condiciones de inferencia estadística.")
            for source in sorted({report["source"] for report in evaluations}):
                values = [report["metrics"]["overall"]["f1_macro"] for report in evaluations if report["source"] == source]
                conclusions.append(f"Los {len(values)} resultados de origen {source} muestran F1 macro "
                                   f"entre {min(values):.4f} y {max(values):.4f}, dentro de sus cohortes y objetivos identificados.")
        if summary is not None:
            conclusions.append(f"La población operativa contiene {summary['total']} reportes y {summary['demo']} registros DEMO.")
            sla = summary["sla"]
            missed = sum(sla.get(key + "_evaluable", 0) - sla.get(key + "_a_tiempo", 0) for key in ("respuesta", "resolucion"))
            conclusions.append(f"Se observaron {missed} hitos de SLA incumplidos. "
                               f"{sum(row['validados'] for row in summary['clasificador'])} reportes tienen validación humana.")
        conclusions.append("La interpretación se restringe a las poblaciones, fechas y referencias identificadas. "
                           "Los hallazgos son descriptivos y conservan las limitaciones de cada tabla y figura.")
        self._authorize(token)
        return ReportSnapshot(identifier, date, request, sections, tuple(provenance), tuple(conclusions))

    def preview_figures(self, snapshot: ReportSnapshot, token: SecretStr) -> tuple[bytes, ...]:
        """Render the frozen preview in a background task, with fresh role validation."""
        self._authorize(token)
        return tuple(render_figure(figure, self.settings).png
                     for section in snapshot.sections for figure in section.figures)

    def publish(self, snapshot: ReportSnapshot, token: SecretStr) -> dict:
        """Authorize generation and publish a complete, hash-bound version atomically."""
        self._authorize(token)
        if not VERSION_ID.fullmatch(snapshot.run_id):
            raise AnalyticsError("La versión del informe es inválida.")
        self._check_selection(snapshot.request)
        self.api.audit_event(token, "autorizar_informe", run_id=snapshot.run_id, outcome="iniciado")
        try:
            outputs = export_all(snapshot, self.settings)
            metadata = {"content": snapshot_payload(snapshot), "content_sha256": snapshot_digest(snapshot),
                        "files": [{"name": item.filename, "mime": item.mime, "size": len(item.data),
                                   "sha256": sha256(item.data).hexdigest()} for item in outputs]}
            self.directory.mkdir(parents=True, exist_ok=True)
            destination = self.settings.path(self.directory / snapshot.run_id)
            with TemporaryDirectory(prefix=".informe-", dir=self.directory) as temporary:
                staging = Path(temporary)
                for output in outputs:
                    (staging / output.filename).write_bytes(output.data)
                (staging / "manifest.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")
                self._authorize(token)
                if destination.exists():
                    raise AnalyticsError("Esta versión de informe ya fue publicada. Genera una nueva previsualización.")
                staging.rename(destination)
                try:
                    self.api.audit_event(token, "generar_informe", run_id=snapshot.run_id)
                except AnalyticsError:
                    # Withdraw a publication whose completion could not be audited.
                    destination.rename(staging)
                    raise
            LOGGER.info("Se publicó un informe con %s formatos y figuras", len(outputs) - 1)
            return {"run_id": snapshot.run_id, "content_sha256": metadata["content_sha256"], "outputs": outputs}
        except Exception as error:
            try:
                self.api.audit_event(token, "generar_informe", run_id=snapshot.run_id, outcome="error")
            except AnalyticsError:
                LOGGER.warning("No se confirmó la auditoría de generación fallida")
            if isinstance(error, AnalyticsError):
                raise
            LOGGER.error("Falló la exportación científica; detalles omitidos por privacidad")
            raise AnalyticsError("No se pudo generar el informe. Revisa las dependencias de exportación, el almacenamiento y los servicios.") from None


def _validate_dashboard(summary: dict) -> None:
    """Reject incomplete or inconsistent numeric aggregates before publication."""
    import math

    try:
        total, demo = summary["total"], summary["demo"]
        if type(total) is not int or type(demo) is not int or not 0 <= demo <= total:
            raise ValueError
        for field in ("tipos", "severidades"):
            values = summary[field]
            if (not isinstance(values, dict) or any(type(n) is not int or n < 0 for n in values.values())
                    or sum(values.values()) != total):
                raise ValueError
        for milestone in ("respuesta", "resolucion"):
            eligible = summary["sla"].get(milestone + "_evaluable", 0)
            timely = summary["sla"].get(milestone + "_a_tiempo", 0)
            if type(eligible) is not int or type(timely) is not int or not 0 <= timely <= eligible <= total:
                raise ValueError
        for row in summary["clasificador"]:
            if any(type(row[key]) is not int for key in ("total", "revision", "validados", "aciertos")):
                raise ValueError
            if not 0 <= row["aciertos"] <= row["validados"] <= row["total"] or not 0 <= row["revision"] <= row["total"]:
                raise ValueError
        if sum(row["total"] for row in summary["clasificador"]) != total:
            raise ValueError
        for row in summary["tiempos"].values():
            if type(row["muestra"]) is not int or not 0 < row["muestra"] <= total:
                raise ValueError
            if not math.isfinite(row["segundos"]) or row["segundos"] < 0:
                raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ServiceError("El tablero SOC contiene agregados incompletos o inconsistentes.") from None
