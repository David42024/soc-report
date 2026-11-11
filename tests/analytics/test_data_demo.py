"""Synthetic completeness must never become evidence of real human review."""
import json
from collections import Counter

from pydantic import SecretStr
import pytest

from src.data.catalog import DatasetCatalog
from src.data.demo import demo_path, demo_summary
from src.data.models import SEVERITIES, TARGETS, TYPES
from src.data.workspace import DataWorkspace
from src.utils.errors import DatasetError


def test_complete_demo_manifest_preserves_real_reserve(settings, api):
    token = SecretStr("private-test-token")
    real_path = settings.path(settings.data.sealed_holdout_file).with_name("holdout-preparation.json")
    real_path.parent.mkdir(parents=True)
    real_path.write_text('{"cases": [{"disposition": null}]}', encoding="utf-8")
    original = real_path.read_bytes()
    workspace = DataWorkspace(DatasetCatalog(settings, api))
    view = workspace.open_demo(token)
    summary = demo_summary(view.inventory)
    assert (summary["total_cases"], summary["development_cases"], summary["reserved_cases"]) == (640, 480, 160)
    assert summary["complete_by_target"] == dict.fromkeys(TARGETS, 640)
    records = view.inventory.records()
    assert set(record.label("tipo").values[0] for record in records) == set(TYPES)
    assert set(record.label("severidad").values[0] for record in records) == set(SEVERITIES)
    assert set(Counter(record.label("tipo").values[0] for record in records).values()) == {64}
    for record in records:
        assert record.title and record.description and record.nature == "sintetica"
        assert all(record.label(field).provenance == "simulacion" and not record.label(field).human_reference for field in TARGETS)
    reserved = {view.groups.by_record[row.key] for row in records if row.partition == "reservado"}
    development = {view.groups.by_record[row.key] for row in records if row.partition == "desarrollo"}
    assert not reserved & development
    saved = workspace.save_manifest(view, token)
    _, payload = workspace.read_manifest(saved["run_id"], token)
    content = json.loads(payload)["content"]
    assert content["synthetic_demo"]["ready_by_target"] == dict.fromkeys(TARGETS, True)
    assert content["holdout"]["test_ready_by_target"] == dict.fromkeys(TARGETS, False)
    assert content["holdout"]["type_review_verified"] is False
    assert content["eligibility"]["candidates_by_target"] == dict.fromkeys(TARGETS, [])
    assert workspace.list_manifests(token)[0]["Naturaleza"] == "Sintética"
    assert real_path.read_bytes() == original
    assert not settings.path(settings.data.sealed_holdout_file).exists()
    assert workspace.open_demo(token).inventory == view.inventory


def test_demo_detects_changes_in_published_data(data_workspace):
    workspace, token, _, _ = data_workspace
    view = workspace.open_demo(token)
    path = demo_path(workspace.settings)
    path.write_bytes(path.read_bytes() + b" ")
    with pytest.raises(DatasetError, match="generador"):
        workspace.save_manifest(view, token)


def test_read_only_role_cannot_create_demo(data_workspace):
    workspace, token, _, state = data_workspace
    state["role"] = "gestor"
    with pytest.raises(DatasetError):
        workspace.open_demo(token)
    assert not demo_path(workspace.settings).exists()
    state["role"] = "analista"
    workspace.open_demo(token)
    state["role"] = "gestor"
    assert len(workspace.open_demo(token).inventory.records()) == 640
    with pytest.raises(DatasetError, match="rol"):
        workspace.save_manifest(workspace.open_demo(token), token)
