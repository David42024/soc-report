"""Bounded application logs isolated from operational backend logging."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler

from .config import AnalyticsSettings
from .security import redact


class RedactingFormatter(logging.Formatter):
    """Remove recognizable credential values from final formatted log lines."""

    def format(self, record: logging.LogRecord) -> str:
        return str(redact(super().format(record)))


def configure_logging(settings: AnalyticsSettings) -> logging.Logger:
    """Configure only the analytical namespace, with rotation and no propagation."""
    logger = logging.getLogger("soc_analytics")
    directory = settings.path(settings.runs_dir) / "_logs"
    directory.mkdir(parents=True, exist_ok=True)
    destination = directory / "analytics.log"
    if not any(getattr(handler, "baseFilename", None) == str(destination) for handler in logger.handlers):
        handler = RotatingFileHandler(destination, maxBytes=settings.logging.max_bytes,
                                      backupCount=settings.logging.backups, encoding="utf-8")
        handler.setFormatter(RedactingFormatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        logger.addHandler(handler)
    logger.setLevel(settings.logging.level)
    logger.propagate = False
    return logger
