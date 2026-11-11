"""Verify evidence provenance, export concordance, permissions and safe formula use."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
from time import monotonic
from uuid import uuid4
from zipfile import ZipFile

from docx import Document
from fastapi.testclient import TestClient
import httpx
from openpyxl import load_workbook
from PIL import Image
from pydantic import SecretStr, ValidationError
import pytest
from sklearn.pipeline import Pipeline
from streamlit.testing.v1 import AppTest

from backend.config import Settings
from backend.db import utc_now
from backend.main import create_app
from backend.security import hash_password
from src.data.models import content_hash
from src.evaluation.workspace import technical_evaluation
from src.explainability.workspace import ExplanationWorkspace
from src.inference.services import Session, SocApi
from src.reports.composition import operational_section
from src.reports.exporters import scientific_excel, snapshot_digest, snapshot_payload
from src.reports.presentation import TableGuide
from src.reports.scientific import ReportRequest, ReportSection, ReportTable, TEMPLATES, display_cell
from src.reports.workspace import ReportingWorkspace
from src.training.experiments import RunRegistry
from src.training.jobs import technical_run
from src.training.runs import JobSpec
from src.utils.config import PROJECT_ROOT
from src.utils.errors import AnalyticsError, ServiceError
from src.utils.streamlit_runtime import Runtime, _inventory, clear_private_state
from src.utils.tasks import TaskRunner


@pytest.fixture
def reporting(settings):
    summary = {
        "total": 3, "demo": 1, "severidades": {"critica": 1, "alta": 2}, "tipos": {"phishing": 3},
        "sla": {"respuesta_evaluable": 3, "respuesta_a_tiempo": 2},
        "clasificador": [{"origen": "fallback", "total": 3, "revision": 2, "validados": 0, "aciertos": 0}],
        "tiempos": {"respuesta": {"muestra": 2, "segundos": 120.0}},
        "equipos": [{"nombre": "nombre.restringido@example.test"}],
    }
    state = {"role": "gestor", "audit": [], "dashboard": summary, "dashboard_status": 200, "fail_completion": False, "queries": []}

    def respond(request):
        if request.headers.get("Authorization") != "Bearer private-test-token":
            return httpx.Response(401)
        if request.url.path.endswith("/me"):
            return httpx.Response(200, json={"id": "fixture-gestor", "username": "gestor", "role": state["role"], "active": 1})
        if request.url.path.endswith("/analitica/eventos"):
            payload = json.loads(request.content)
            if state["fail_completion"] and payload["action"] == "generar_informe" and payload["outcome"] == "completado":
                return httpx.Response(503)
            state["audit"].append(payload)
            return httpx.Response(204)
        if request.url.path.endswith("/dashboard"):
            state["queries"].append(dict(request.url.params))
            return httpx.Response(state["dashboard_status"], json=state["dashboard"])
        pytest.fail("La generación pidió un endpoint ajeno a las fuentes autorizadas.")
    api = SocApi(settings.api, transport=httpx.MockTransport(respond))
    return ReportingWorkspace(settings, api), SecretStr("private-test-token"), state


def request(template="academico", **kwargs):
    return ReportRequest(template=template, sections=TEMPLATES[template].sections, **kwargs)


def test_archived_results_export_in_three_formats_without_new_inference(reporting, monkeypatch):
    workspace, token, state = reporting
    settings = workspace.settings
    spec = JobSpec(source="sintetico", target="tipo", seed=settings.seed, trials=1,
                   models=("tfidf_logreg", "tfidf_svm"), local=settings.training.local)
    phase2, training = technical_run(settings, spec)
    evaluations, comparison = technical_evaluation(settings, phase2)
    xai = ExplanationWorkspace(settings, workspace.api)._local(phase2, "tfidf_logreg", "validation", lambda _: None)
    before = sha256(workspace.training.path(phase2).joinpath("result.json").read_bytes()).hexdigest()

    def forbidden(*_args, **_kwargs):
        pytest.fail("La exportación intentó ajustar, inferir o abrir Prueba.")

    monkeypatch.setattr(Pipeline, "fit", forbidden)
    monkeypatch.setattr("src.evaluation.workspace.load_test", forbidden)
    monkeypatch.setattr("src.evaluation.workspace.local_predictions", forbidden)
    chosen = request(experiments=(phase2,), evaluations=tuple(row["run_id"] for row in evaluations), explanations=(xai["run_id"],),
                     desde=date(2026, 1, 1), hasta=date(2026, 1, 31))
    snapshot = workspace.compose(chosen, token)
    assert state["queries"] == [{"desde": "2026-01-01", "hasta": "2026-01-31"}]
    serialized = json.dumps(snapshot_payload(snapshot), ensure_ascii=False)
    assert "nombre.restringido" not in serialized
    assert '"predictions"' not in serialized and '"cases"' not in serialized
    assert "12 grupos" in serialized and "prueba_tecnica" in serialized
    assert "sintética" in serialized and "requiere 20" in serialized
    outputs = workspace.publish(snapshot, token)["outputs"]
    assert len(outputs) == 4
    assert outputs[0].data.startswith(b"%PDF-") and len(outputs[0].data) > 10000
    document = Document(BytesIO(outputs[1].data))
    assert not document.styles["Title"].element.xpath(".//w:pBdr")
    word_rows = [[tuple(cell.text for cell in row.cells) for row in table.rows] for table in document.tables]
    expected = [table for section in snapshot.sections for table in section.tables]
    assert len(word_rows) == len(expected)
    for table, observed in zip(expected, word_rows):
        assert observed[0] == table.columns
        assert observed[1:] == [tuple(display_cell(value, table.style(i)) for i, value in enumerate(row)) for row in table.rows]
    workbook = load_workbook(BytesIO(outputs[2].data))
    texts = [cell.value for sheet in workbook for row in sheet for cell in row if cell.value is not None]
    assert snapshot_digest(snapshot) in texts and 2 / 3 in texts
    assert 24 in texts and 1.0 in texts
    assert any(isinstance(value, str) and value.startswith("=IF(") for value in texts)
    figure_sheets = [sheet for sheet in workbook if sheet.title.startswith("Figura ")]
    assert len(figure_sheets) == 5
    assert all(len(sheet._images) == 1 and sheet.page_setup.fitToHeight == 1 for sheet in figure_sheets)
    with ZipFile(BytesIO(outputs[3].data)) as archive:
        pngs = [name for name in archive.namelist() if name.endswith(".png")]
        assert len(pngs) == 5
        for name in pngs:
            with Image.open(BytesIO(archive.read(name))) as image:
                assert image.info["dpi"] == pytest.approx((600, 600), abs=.1)
            assert b"<svg" in archive.read(name.replace(".png", ".svg"))
    stored = json.loads((workspace.directory / snapshot.run_id / "manifest.json").read_text(encoding="utf-8"))
    assert stored["content_sha256"] == snapshot_digest(snapshot)
    assert all(sha256(output.data).hexdigest() == entry["sha256"] for output, entry in zip(outputs, stored["files"]))
    assert before == sha256(workspace.training.path(phase2).joinpath("result.json").read_bytes()).hexdigest()
    assert state["audit"][-1]["action"] == "generar_informe"
    assert comparison["run_id"] in serialized
    publications = workspace.catalog(token)["publications"]
    assert publications[0]["Versión"] == snapshot.run_id
    archived = workspace.read_publication(snapshot.run_id, token)
    assert [output.data for output in archived["outputs"]] == [output.data for output in outputs]
    target = workspace.directory / snapshot.run_id / outputs[0].filename
    original = target.read_bytes()
    target.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    with pytest.raises(AnalyticsError, match="huella"):
        workspace.read_publication(snapshot.run_id, token)


@pytest.mark.parametrize("template", tuple(TEMPLATES))
def test_templates_pending_sections_and_absent_ratios(reporting, template):
    workspace, token, state = reporting
    snapshot = workspace.compose(request(template), token)
    assert snapshot.template.title == TEMPLATES[template].title
    assert any("Pendiente." in note for section in snapshot.sections for note in section.notes)
    rows = operational_section(state["dashboard"]).tables
    assert rows[0].rows[1][-1] is None
    assert rows[1].rows[0][-1] is None
    assert any("3 reportes" in conclusion for conclusion in snapshot.conclusions)
    assert not any("Gemini observado" in note for section in snapshot.sections for note in section.notes)


def test_invalid_dates_selections_integrity_and_dashboard_errors(reporting):
    workspace, token, state = reporting
    with pytest.raises(ValidationError):
        request(desde=date(2026, 2, 1), hasta=date(2026, 1, 1))
    invalid = "20261110T220000000000Z_000000000000"
    with pytest.raises(AnalyticsError, match="únicas"):
        workspace.compose(request(experiments=(invalid, invalid)), token)
    with pytest.raises(AnalyticsError, match="manifiesto"):
        workspace.compose(request(manifest=invalid), token)
    state["dashboard"]["total"] = 1
    snapshot = workspace.compose(request("tecnico"), token)
    assert snapshot.sections[0].notes[0].startswith("Pendiente.")
    state["dashboard_status"] = 403
    with pytest.raises(ServiceError):
        workspace.compose(request(), token)


def test_rbac_revocation_and_failed_audit_prevent_downloads(reporting, monkeypatch):
    workspace, token, state = reporting
    for role in ("analista", "auditor", "solicitante"):
        state["role"] = role
        with pytest.raises(ServiceError) as caught:
            workspace.catalog(token)
        assert caught.value.status_code == 403
    state["role"] = "gestor"
    snapshot = workspace.compose(request("tecnico"), token)
    state["role"] = "analista"
    with pytest.raises(ServiceError):
        workspace.publish(snapshot, token)
    state["role"] = "gestor"
    state["fail_completion"] = True
    # Test publication rollback with small generated payloads, without PDF rendering.
    from src.reports.exporters import ReportExport
    monkeypatch.setattr("src.reports.workspace.export_all", lambda *_: (ReportExport("fixture.pdf", "application/pdf", b"%PDF-fixture"),))
    with pytest.raises(ServiceError):
        workspace.publish(snapshot, token)
    assert not (workspace.directory / snapshot.run_id).exists()
    assert not list(workspace.directory.glob(".informe-*"))
    assert state["audit"][-1]["outcome"] == "error"


def test_excel_treats_untrusted_strings_as_text(reporting):
    workspace, token, _ = reporting
    snapshot = workspace.compose(request("tecnico"), token)
    guide = TableGuide("Texto de prueba", "Texto", "Lee la celda.", "Dos entradas de control.", "Prueba de seguridad.")
    table = ReportTable(guide, ("Entrada",), (("=HYPERLINK(\"https://example.test\")",), ("+cmd",)))
    snapshot = replace(snapshot, sections=(ReportSection("Control", tables=(table,)),))
    workbook = load_workbook(BytesIO(scientific_excel(snapshot, ())))
    cells = [cell for row in workbook.worksheets[1] for cell in row if cell.value and str(cell.value).startswith(("=HYPER", "+cmd"))]
    assert len(cells) == 2 and all(cell.data_type == "s" for cell in cells)


def test_manifest_coverage_uses_valid_counts_preserves_originals_and_checks_integrity(data_workspace):
    data, token, paths, state = data_workspace
    before = {name: sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    view = data.open(token)
    manifest = data.save_manifest(view, token)
    state["role"] = "gestor"
    workspace = ReportingWorkspace(data.settings, data.api)
    selected = ReportRequest(template="academico", sections=("datos",), manifest=manifest["run_id"])
    snapshot = workspace.compose(selected, token)
    coverage = next(table for table in snapshot.sections[0].tables if "Cobertura" in table.guide.title)
    for row in coverage.rows:
        assert row[-1] == (row[3] / row[2] if row[2] else None)
    workbook = load_workbook(BytesIO(scientific_excel(snapshot, ())))
    assert any(cell.data_type == "f" for sheet in workbook for row in sheet for cell in row)
    assert "privado@example.test" not in json.dumps(snapshot_payload(snapshot))
    assert before == {name: sha256(path.read_bytes()).hexdigest() for name, path in paths.items()}
    path = workspace.manifests.directory / manifest["run_id"] / "manifest.json"
    envelope = json.loads(path.read_bytes())
    envelope["content"]["seed"] += 1
    path.write_text(json.dumps(envelope), encoding="utf-8")
    with pytest.raises(AnalyticsError, match="huella"):
        workspace.compose(selected, token)


def test_real_backend_report_audit_reuses_export_permission(tmp_path):
    app = create_app(Settings(sqlite_path=tmp_path / "reports.sqlite3", operator_token="legacy-fixture",
                              legacy_operator_enabled=True, jwt_secret="report-fixture-jwt-secret-at-least-32-characters"))
    identifier = "20261110T220000000000Z_000000000000"
    with TestClient(app) as server:
        with app.state.db.session(write=True) as execute:
            for role in ("administrador", "gestor", "analista", "auditor", "solicitante"):
                execute("INSERT INTO users (id,username,password_hash,role,creado_at) VALUES (%s,%s,%s,%s,%s)",
                        (str(uuid4()), role, hash_password("report-test-password"), role, utc_now()))
        for role in ("administrador", "gestor", "analista", "auditor", "solicitante"):
            response = server.post("/api/auth/login", json={"username": role, "password": "report-test-password"})
            headers = {"Authorization": "Bearer " + response.json()["access_token"]}
            for action, outcome in (("consultar_informes", "completado"), ("autorizar_informe", "iniciado"), ("generar_informe", "completado")):
                result = server.post("/api/analitica/eventos", headers=headers,
                                     json={"action": action, "run_id": identifier, "outcome": outcome})
                assert result.status_code == (204 if role in ("administrador", "gestor") else 403)
        result = server.post("/api/analitica/eventos", headers={"Authorization": "Bearer legacy-fixture"},
                             json={"action": "consultar_informes"})
        assert result.status_code == 401
        with app.state.db.session() as execute:
            rows = execute("SELECT module,action FROM audit_log WHERE entity_id=%s", (identifier,)).fetchall()
        assert len(rows) == 6 and {row["module"] for row in rows} == {"analitica/informes"}


def test_report_page_preview_export_and_session_clear(reporting, monkeypatch):
    workspace, token, state = reporting
    tasks = TaskRunner(2)
    checked_at = monotonic()
    monkeypatch.setattr("src.utils.streamlit_runtime.monotonic", lambda: checked_at)
    from src.data.catalog import DatasetCatalog
    runtime = Runtime(workspace.settings, workspace.api, DatasetCatalog(workspace.settings, workspace.api),
                      RunRegistry(workspace.settings), tasks, _inventory, reporting=workspace)
    monkeypatch.setattr("src.utils.streamlit_runtime.get_runtime", lambda: runtime)

    def settle(app, *keys):
        for key in keys:
            if key in app.session_state:
                app.session_state[key].result(timeout=90)
                app.run()
        assert not app.exception and not app.error
    try:
        page = str(PROJECT_ROOT / "pages/07_Informes.py")
        app = AppTest.from_file(page, default_timeout=90)
        app.run()
        assert not app.exception and not app.button
        app.session_state["auth_session"] = Session(token=token, user=workspace.api.me(token),
            checked_at=checked_at, expires_at=datetime.now(timezone.utc) + timedelta(days=1))
        app.run()
        settle(app, "informe_catalog")
        app.selectbox(key="informe_template").select("ejecutivo").run()
        app.button(key="informe_preview_button").click().run()
        settle(app, "informe_preview", "informe_figures")
        assert app.dataframe and app.get("image")
        assert any("Cómo leerlo" in item.value for item in app.markdown)
        app.button(key="informe_generate").click().run()
        settle(app, "informe_export")
        assert len(app.get("download_button")) == 4
        state["role"] = "analista"
        app.session_state["auth_session"] = app.session_state["auth_session"].model_copy(update={"user": workspace.api.me(token)})
        app.run()
        assert not app.get("download_button")
        with monkeypatch.context() as patch:
            fake = {"informe_preview_result": "private", "auth_session": "private", "other": "public"}
            patch.setattr("src.utils.streamlit_runtime.st.session_state", fake)
            clear_private_state()
            assert fake == {"other": "public"}
    finally:
        tasks.close()
