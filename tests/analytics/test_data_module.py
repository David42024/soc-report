"""Regression tests for the protected Phase 1 data inventory and its artifacts."""
from dataclasses import replace
from hashlib import sha256
from io import BytesIO
import json
import sqlite3
from uuid import uuid4
from zipfile import ZipFile

from fastapi.testclient import TestClient
from PIL import Image
import pytest

from backend.config import Settings
from backend.db import utc_now
from backend.main import create_app
from backend.security import hash_password
from scripts.vcdb import DATASET, REVISION, canonical_text
from src.data.manifest import holdout_status
from src.data.models import content_hash, DataRecord, TARGETS
from src.data.quality import find_similar, group_records, quality_checks
from src.data.sources import _protected
from src.data.statistics import RecordFilters, coverage, frequencies, numeric_summary, page_slice, select_records, term_frequencies
from src.reports.data_presentation import coverage_comparison, coverage_plot
from src.reports.figures import export_png
from src.utils.errors import DatasetError, ServiceError
from src.utils.privacy import RedactionSession


def test_inventory_keeps_original_schema_provenance_and_quality(data_workspace):
    workspace, token, paths, state = data_workspace
    view = workspace.open(token)
    sources = {source.id: source for source in view.inventory.sources}
    public, simulation, operational = (sources[key] for key in ("eurepoc", "article_simulation", "operational_reports"))
    assert len(public.records) == 14
    assert public.columns[-3:-1] == ("initiator_country", "initiator_country__2")
    assert public.original_columns.count("initiator_country") == 2
    assert public.sha256 == sha256(paths["eurepoc"].read_bytes()).hexdigest()
    assert "privado@example.test" not in public.records[0].description
    assert public.records[0].label("tipo_fuente").values == ("Malware", "Phishing")
    assert public.records[0].label("tipo").values == ()
    assert view.groups.by_record[public.records[0].key] == view.groups.by_record[public.records[1].key]
    assert simulation.records[0].nature == "sintetica"
    assert simulation.records[0].label("clase_simulada").provenance == "simulacion"
    real, demo = operational.records
    assert real.label("tipo").values == ("acceso_no_autorizado",)
    assert real.predictions["tipo"].values == ("phishing",)
    assert all(real.label(field).human_reference for field in TARGETS)
    assert real.reviewed_at == "2026-01-01T14:00:00+00:00"
    assert demo.nature == "demo" and not demo.label("tipo").human_reference
    checks = {item.code: item for item in quality_checks(view.inventory, view.groups, view.similarity, workspace.settings.data)}
    assert checks["estructura"].status == checks["etiquetas"].status == checks["duplicado_id"].status == "Error"
    assert checks["faltantes"].count == 1
    assert checks["duplicado_texto"].count == 2
    assert checks["naturaleza"].count == 3
    assert checks["revision"].count == 14
    assert state["audit"][0]["action"] == "consultar_datos"


def test_edits_are_protected_versioned_attributed_and_audited(data_workspace):
    workspace, token, paths, state = data_workspace
    original = paths["eurepoc"].read_bytes()
    view = workspace.open(token)
    record = view.inventory.sources[0].records[0]
    edits = {"titulo": "Reporte de phishing validado", "descripcion": "La cuenta recibió un correo en reserva@example.test con un enlace.",
             "tipo": "phishing", "severidad": "alta", "activo_afectado": "servidor", "fuente": "Revisión del caso",
             "origen": "Validación documental", "grupo": "campaña-01", "estado": "revisado",
             "campos_revisados": list(TARGETS), "observaciones": "Consulta a revisor@example.test"}
    with pytest.raises(DatasetError, match="Confirma"):
        workspace.save_revision(view, record.key, edits, 0, False, token)
    with pytest.raises(DatasetError, match="severidad"):
        workspace.save_revision(view, record.key, {**edits, "severidad": "fuera-de-taxonomia"}, 0, True, token)
    with pytest.raises(DatasetError, match="valor visible"):
        workspace.save_revision(view, record.key, {**edits, "activo_afectado": "activo@example.test"}, 0, True, token)
    first = workspace.save_revision(view, record.key, edits, 0, True, token)
    assert first.actor_id == "actor-1" and first.version == 1 and first.base_sha256 == record.base_sha256
    assert first.created_at.endswith("+00:00")
    assert state["audit"][-1] == {"action": "autorizar_revision_datos", "source_id": "eurepoc",
                                  "run_id": first.run_id, "outcome": "iniciado"}
    assert b"reserva@example.test" not in workspace.revisions.path.read_bytes()
    assert b"revisor@example.test" not in workspace.revisions.path.read_bytes()
    with sqlite3.connect(workspace.revisions.path) as connection, pytest.raises(sqlite3.IntegrityError):
        connection.execute("DELETE FROM revisions")
    with pytest.raises(DatasetError, match="Otra edición"):
        workspace.save_revision(view, record.key, {"observaciones": "Versión anterior"}, 0, True, token)
    updated = workspace.refresh_revisions(view.original, token)
    corrected = updated.record(record.key)
    assert corrected.group == "campaña-01" and corrected.source_id == record.source_id
    assert corrected.title == "Reporte de phishing validado"
    assert all(corrected.label(field).human_reference for field in TARGETS)
    second = workspace.save_revision(updated, record.key, {"descripcion": "Cambió la descripción técnica del incidente."}, 1, True, token)
    latest = workspace.refresh_revisions(view.original, token)
    assert second.previous_sha256 == first.sha256 and latest.record(record.key).review_state == "pendiente"
    assert latest.record(record.key).label("tipo").provenance == "propuesta"
    assert [entry.version for entry in workspace.history(latest, record.key, token)] == [2, 1]
    assert paths["eurepoc"].read_bytes() == original


def test_roles_stale_files_and_failed_audit_block_data_operations(data_workspace):
    workspace, token, paths, state = data_workspace
    state["role"] = "auditor"
    with pytest.raises(DatasetError, match="rol"):
        workspace.open(token)
    assert not state["audit"]
    state["role"] = "gestor"
    view = workspace.open(token)
    record = view.inventory.sources[0].records[0]
    with pytest.raises(DatasetError, match="rol"):
        workspace.save_revision(view, record.key, {"observaciones": "Lectura"}, 0, True, token)
    with pytest.raises(DatasetError, match="rol"):
        workspace.save_manifest(view, token)
    state["role"] = "analista"
    state["audit_ok"] = False
    with pytest.raises(ServiceError):
        workspace.save_revision(view, record.key, {"observaciones": "Auditoría requerida"}, 0, True, token)
    assert workspace.revisions.revisions() == ()
    with pytest.raises(ServiceError):
        workspace.save_manifest(view, token)
    assert workspace.manifests.list() == []
    with pytest.raises(ServiceError):
        workspace.open(token)
    state["audit_ok"] = True
    with paths["eurepoc"].open("a", encoding="utf-8") as handle:
        handle.write("\n")
    with pytest.raises(DatasetError, match="Cambió"):
        workspace.save_revision(view, record.key, {"observaciones": "Original anterior"}, 0, True, token)


def test_manifest_reproducibility_eligibility_and_integrity(data_workspace):
    workspace, token, _, _ = data_workspace
    view = workspace.open(token)
    first = workspace.save_manifest(view, token)
    second = workspace.save_manifest(workspace.open(token), token)
    assert first["run_id"] != second["run_id"]
    assert first["content_sha256"] == second["content_sha256"]
    _, data = workspace.read_manifest(first["run_id"], token)
    payload = json.loads(data)
    content = payload["content"]
    assert content_hash(content) == first["content_sha256"]
    assert len(content["groups"]["by_record"]) == len(view.inventory.records())
    assert content["holdout"]["test_ready_by_target"] == dict.fromkeys(TARGETS, False)
    assert all([row["source_id"] for row in rows] == ["operational_reports"]
               for rows in content["eligibility"]["candidates_by_target"].values())
    assert b"revisor-operativo" not in data and b"privado@example.test" not in data
    assert view.inventory.sources[0].records[0].description.encode() not in data
    stored = workspace.manifests.directory / first["run_id"] / "manifest.json"
    stored.write_bytes(data.replace(b'"phase": 1', b'"phase": 2'))
    with pytest.raises(DatasetError, match="huella"):
        workspace.read_manifest(first["run_id"], token)


def test_group_conflict_and_concept_similarity_are_kept_separate(settings, data_workspace):
    descriptions = (
        "The operators detected acceso no autorizado after several account alerts and isolated the endpoint.",
        "The operators detected unauthorized access after several account alerts and isolated the endpoint.",
    )
    reserve, candidate = tuple(DataRecord(key=str(i), source_id="eurepoc", incident_id=str(i), base_sha256=str(i),
            source_label="Fuente", nature="real", partition="reservado" if i == 0 else "sin_asignar", origin="registro",
            description=text, text_sha256=canonical_text(text)) for i, text in enumerate(descriptions))
    groups = group_records((reserve, candidate))
    similarity = find_similar((reserve, candidate), groups, settings.data)
    assert similarity.pairs == similarity.cross_reserved_pairs == 1
    assert similarity.reserved_risk_groups == frozenset(groups.by_record.values())
    assert not groups.conflicts
    linked = group_records((replace(reserve, links=("a",), pilot_exposure=True),
                            replace(candidate, links=("b",)), replace(candidate, key="3", links=("a", "b"))))
    assert len(linked.members) == len(linked.conflicts) == 1
    workspace, token, _, _ = data_workspace
    assert not holdout_status(workspace.open(token).inventory, linked)["test_ready_by_target"]["tipo"]


def test_native_vcdb_campaign_groups_different_reports(data_workspace, monkeypatch):
    workspace, _, _, _ = data_workspace
    spec = workspace.reader.catalog.source("eurepoc").model_copy(
        update={"id": "vcdb_original", "path": "fixture.zip", "kind": "vcdb_archive"})
    path = workspace.settings.path(spec.path)
    pilot, reserved = str(uuid4()), str(uuid4())
    with ZipFile(path, "w") as archive:
        for identifier, summary in ((pilot, "Se cerró una cuenta del equipo."),
                                    (reserved, "Se confirmó otra interrupción del servicio.")):
            row = {"incident_id": identifier, "campaign_id": "campaign-1", "summary": summary}
            archive.writestr(f"fixture/data/json/validated/{identifier}.json", json.dumps(row))
    monkeypatch.setattr("src.data.sources.ARCHIVE_HASH", sha256(path.read_bytes()).hexdigest())
    redactor = RedactionSession()
    source, _ = workspace.reader._archive(spec, {reserved}, {pilot}, set(), {},
        lambda record: _protected(record, redactor, workspace.settings.data.max_text_characters))
    groups = group_records(source.records)
    assert all(record.group == "campaign-1" for record in source.records)
    assert len(groups.conflicts) == 1


def test_reserved_artifact_requires_independent_reviews_bound_to_preparation(data_workspace):
    workspace, token, _, _ = data_workspace
    reader = workspace.reader
    identifier, reference = str(uuid4()), "https://example.test/fixture"
    queue = {"dataset": DATASET, "status": "draft_for_independent_review", "sampling": "Preparación aislada de prueba.",
             "cases": [{"source_id": identifier}]}
    row = {"source_id": identifier, "source_url": reference, "group": "grupo-reserva", "redaction_reviewed": True,
           "source_stage": "initial_public_report", "titulo": "Incidente bajo revisión",
           "descripcion": "Se verificó una interrupción en los sistemas del laboratorio."}
    preparation = {"cases": [{**row, "disposition": "include"}]}
    eligible = {identifier: {"source_urls": [reference], "suggested_partition": "holdout_candidate"}}
    path = workspace.settings.path(workspace.settings.data.sealed_holdout_file)
    path.parent.mkdir(parents=True)
    artifact = {"revision": REVISION, "stage": "holdout", "sampling": queue["sampling"], "cases": [
        {**row, "tipo": "otro", "reviews": [{"reviewer": "persona-1", "tipo": "otro"}]}]}
    path.write_text(json.dumps(artifact), encoding="utf-8")
    def read():
        return reader._holdout(queue, {identifier}, preparation, preparation["cases"], eligible, (set(), set()))
    assert not read().type_review_verified
    artifact["cases"][0]["reviews"].append({"reviewer": "persona-2", "tipo": "otro"})
    path.write_text(json.dumps(artifact), encoding="utf-8")
    accepted = read()
    assert accepted.type_review_verified and accepted.reviewed_cases == 1
    view = workspace.open(token)
    assert holdout_status(replace(view.inventory, holdout=accepted), view.groups)["test_ready_by_target"] == {
        "tipo": True, "severidad": False, "activo_afectado": False}
    preparation["cases"][0]["descripcion"] += " El texto autorizado se actualizó."
    assert not read().type_review_verified


def test_filters_descriptive_statistics_and_scientific_png(data_workspace):
    workspace, token, _, _ = data_workspace
    sources = workspace.open(token).inventory.sources
    public = sources[0].records
    selected = select_records(public, RecordFilters(search="interrupción servidor", nature="real",
                                                   native_labels=(("tipo_fuente", "Phishing"),)))
    assert len(selected) == 1 and selected[0].incident_id == "pub-1"
    page, current, total = page_slice(public, 20, 10)
    assert (len(page), current, total) == (4, 2, 2)
    labels = frequencies(public, "tipo_fuente")
    assert labels[0]["Frecuencia (registros)"] == 13 and labels[0]["Frecuencia relativa (%)"] == 100
    assert labels[1]["Denominador (registros válidos)"] == 13
    assert coverage(public)[0]["Faltantes (registros)"] == 14
    summary = numeric_summary([1.0, 3.0, 7.0], 4, "puntos")
    assert [summary[key] for key in ("Q1", "Mediana", "Q3", "Rango")] == [2, 3, 5, 6]
    assert numeric_summary([2.0], 1, "puntos")["Desviación estándar (muestral)"] is None
    terms, n = term_frequencies(selected, ("servidor", "privado", "correo"))
    assert n == 1 and {term["Término"] for term in terms} == {"servidor", "correo"}
    figure, guide = coverage_plot(coverage_comparison(sources, "tipo"), "tipo", workspace.settings.figures)
    assert figure.axes[0].get_xlabel().endswith("(%)") and figure.axes[0].get_legend()
    assert "1 de 3" in guide.finding and guide.how_to_read and guide.limitations
    with Image.open(BytesIO(export_png(figure, workspace.settings.figures))) as png:
        assert png.info["dpi"] == pytest.approx((600, 600), abs=0.1)


def test_data_audit_uses_real_jwt_and_backend_permissions(tmp_path):
    app = create_app(Settings(sqlite_path=tmp_path / "data-audit.sqlite3", operator_token="test-operator",
                              legacy_operator_enabled=True, jwt_secret="test-data-jwt-independent-secret-longer-than-32-characters"))
    path = "/api/analitica/eventos"
    with TestClient(app) as server:
        encoded = hash_password("test-password")
        identities = {role: str(uuid4()) for role in ("analista", "gestor", "auditor")}
        with app.state.db.session(write=True) as execute:
            for role, actor in identities.items():
                execute("INSERT INTO users (id,username,password_hash,role,creado_at) VALUES (%s,%s,%s,%s,%s)",
                        (actor, role, encoded, role, utc_now()))
        for role in identities:
            token = server.post("/api/auth/login", json={"username": role, "password": "test-password"}).json()["access_token"]
            headers = {"Authorization": "Bearer " + token}
            assert server.post(path, headers=headers, json={"action": "consultar_datos"}).status_code == (403 if role == "auditor" else 204)
            run_id = "20260101T120000000000Z_" + uuid4().hex[:12]
            for action in ("autorizar_revision_datos", "autorizar_manifiesto_datos"):
                body = {"action": action, "source_id": "eurepoc", "run_id": run_id, "outcome": "iniciado"}
                assert server.post(path, headers=headers, json=body).status_code == (204 if role == "analista" else 403)
                assert server.post(path, headers=headers, json={**body, "run_id": None}).status_code == 422
        assert server.post(path, headers={"Authorization": "Bearer test-operator"}, json={"action": "consultar_datos"}).status_code == 401
        with app.state.db.session() as execute:
            rows = list(execute("SELECT user_id,role,action FROM audit_log WHERE module='analitica/datos' AND outcome IN ('iniciado','completado')"))
        assert len(rows) == 4
        assert all(row["user_id"] == identities[row["role"]] for row in rows)
