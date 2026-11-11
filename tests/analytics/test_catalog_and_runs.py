from hashlib import sha256
import json

from pydantic import SecretStr
import pytest
import yaml

from src.data.catalog import DatasetCatalog
from src.inference.services import SocApi
from src.reports.presentation import catalog_guide, runs_guide
from src.training.experiments import RunRegistry
from src.utils.errors import AnalyticsError, ConfigurationError, DatasetError, ServiceError


def register_csv(settings):
    source = settings.root / "existing.csv"
    source.write_text("id,tipo\n1,phishing\n2,malware\n", encoding="utf-8")
    registry = {"version": 1, "datasets": [{"id": "existing", "name": "Fuente de prueba existente", "kind": "csv", "path": "existing.csv",
        "provenance": "Fixture aislada", "labels": ["tipo"], "preview_columns": ["id", "tipo"], "limitation": "Fixture de prueba"}]}
    settings.path(settings.registry_file).write_text(yaml.safe_dump(registry), encoding="utf-8")
    return source


def test_source_read_is_authorized_bounded_hashed_and_unchanged(settings, api):
    path = register_csv(settings)
    original = path.read_bytes()
    catalog = DatasetCatalog(settings, api)
    assert catalog.inspect_all()[0]["rows"] == 2
    with pytest.raises(ServiceError):
        catalog.preview("existing", token=SecretStr("invalid"))
    preview = catalog.preview("existing", token=SecretStr("private-test-token"))
    assert preview["sha256"] == sha256(original).hexdigest()
    assert preview["rows"][0] == {"id": "1", "tipo": "phishing"}
    assert path.read_bytes() == original
    stamp = catalog.fingerprint()
    path.write_text("id,tipo\n3,fraude\n", encoding="utf-8")
    assert catalog.fingerprint() != stamp


def test_missing_source_and_registry_path_validation(settings, api):
    register_csv(settings).unlink()
    assert DatasetCatalog(settings, api).inspect_all()[0]["status"] == "ausente"
    registry = yaml.safe_load(settings.path(settings.registry_file).read_text())
    registry["datasets"][0]["path"] = "../outside.csv"
    settings.path(settings.registry_file).write_text(yaml.safe_dump(registry))
    with pytest.raises(ConfigurationError):
        DatasetCatalog(settings, api)


def test_csv_preserves_embedded_newlines_and_escaped_double_quotes(settings, api):
    path = register_csv(settings)
    path.write_text('id,tipo,nota\n1,phishing,"Texto ""urgente""\nsegunda línea"\n2,malware,Observación\n', encoding="utf-8")
    catalog = DatasetCatalog(settings, api)
    profile = catalog.inspect("existing")
    assert profile["status"] == "disponible" and profile["rows"] == 2
    assert len(profile["columns"]) == 3
    assert catalog.preview("existing", token=SecretStr("private-test-token"))["rows"][0]["id"] == "1"


def test_inconsistent_csv_is_reported_as_invalid(settings, api):
    path = register_csv(settings)
    path.write_text("id,tipo\n1,phishing,unexpected\n", encoding="utf-8")
    catalog = DatasetCatalog(settings, api)
    assert catalog.inspect("existing")["status"] == "formato no válido"
    with pytest.raises(DatasetError):
        catalog.preview("existing", token=SecretStr("private-test-token"))


def test_operational_access_uses_api_and_hashes_only_the_returned_scope(settings, api):
    catalog = DatasetCatalog(settings, api)
    preview = catalog.preview("operational_reports", token=SecretStr("private-test-token"))
    assert "hasta 100" in preview["hash_scope"]
    assert preview["rows"][0]["tipo"] == "phishing"
    assert "descripcion" not in preview["rows"][0]
    with pytest.raises(DatasetError):
        catalog.source("../.env")


def test_experiment_record_is_complete_atomic_and_contains_no_raw_data(settings, api):
    register_csv(settings)
    preview = DatasetCatalog(settings, api).preview("existing", token=SecretStr("private-test-token"))
    preview["rows"] = [{"description": "do not store this report"}]
    registry = RunRegistry(settings)
    record = registry.record_validation(preview, {"available_files": 1})
    assert record["seed"] == settings.seed
    assert record["dataset"]["sha256"] == preview["sha256"]
    assert record["created_at"] and record["config"] and record["software"]
    assert registry.records() == [record]
    assert "do not store this report" not in json.dumps(record)
    assert not list(settings.path(settings.runs_dir).glob("*/*.tmp"))
    with pytest.raises(AnalyticsError):
        registry.record_validation(preview, {"bad": float("nan")})


def test_interpretations_respond_to_observed_values():
    first = catalog_guide([])
    second = catalog_guide([{"status": "disponible", "synthetic": True}])
    assert first.finding != second.finding
    assert "1 de 1" in second.finding
    assert "0 verificaciones" in runs_guide([]).finding
