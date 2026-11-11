from io import BytesIO
import json
import logging

import numpy as np
from PIL import Image
from matplotlib.figure import Figure
from pydantic import SecretStr
import pytest
import yaml

from src.reports.figures import export_png
from src.utils.config import ApiSettings, load_config, project_path
from src.utils.errors import ConfigurationError
from src.utils.logging import RedactingFormatter
from src.utils.reproducibility import seed_everything
from src.utils.security import redact
from src.utils.tasks import TaskRunner


def test_environment_overrides_public_parameters_without_retaining_credentials(settings):
    configured = load_config(settings.root, environment={"SOC_API_URL": "https://soc.example.test",
        "SOC_ANALYTICS_PORT": "8510", "GROQ_API_KEY": "gsk_never_export_this_secret", "DATABASE_URL": "postgresql://u:p@localhost/db"})
    assert configured.api.base_url == "https://soc.example.test"
    assert configured.ui.port == 8510
    assert "gsk_" not in configured.model_dump_json()
    assert "postgresql://" not in configured.model_dump_json()


@pytest.mark.parametrize("url", ["https://user:password@example.test", "http://remote.example.test", "https://soc.example.test/?token=secret", "file:///secret"])
def test_configuration_rejects_credential_urls_and_nonlocal_plain_http(settings, url):
    with pytest.raises(ValueError):
        ApiSettings(**{**settings.api.model_dump(), "base_url": url})


def test_config_errors_are_safe_and_paths_cannot_escape_project(settings):
    with pytest.raises(ConfigurationError):
        project_path(settings.root, "../outside")
    path = settings.source_file
    content = yaml.safe_load(path.read_text(encoding="utf-8"))
    content["api"]["base_url"] = "https://admin:do-not-show-this@example.test"
    path.write_text(yaml.safe_dump(content), encoding="utf-8")
    with pytest.raises(ConfigurationError) as caught:
        load_config(settings.root, environment={})
    assert "do-not-show-this" not in str(caught.value)


def test_redaction_covers_nested_secrets_and_formatted_log_credentials():
    result = redact({"password": "private", "nested": {"groq_api_key": "private", "jwt": SecretStr("private")},
                     "url": "postgresql://user:private@localhost/db", "seed": 42})
    assert "private" not in json.dumps(result)
    assert result["seed"] == 42
    record = logging.LogRecord("soc_analytics", logging.WARNING, "test", 1, "gsk_abcdefghijklmno", (), None)
    assert "abcdefghijklmno" not in RedactingFormatter("%(message)s").format(record)


def test_reproducibility_and_background_worker():
    seed_everything(42)
    first = np.random.random(4)
    seed_everything(42)
    assert np.array_equal(first, np.random.random(4))
    runner = TaskRunner(1)
    try:
        assert runner.submit(sum, [1, 2, 3]).result(timeout=2) == 6
    finally:
        runner.close()


def test_scientific_export_has_600_dpi(settings):
    figure = Figure(figsize=(2, 1))
    axes = figure.subplots()
    axes.plot([0, 1], [0, 1], label="Referencia de prueba")
    axes.set(title="Prueba de exportación", xlabel="Tiempo (s)", ylabel="Valor (unidad)")
    axes.legend()
    image = Image.open(BytesIO(export_png(figure, settings.figures)))
    assert image.info["dpi"][0] == pytest.approx(600, abs=1)
