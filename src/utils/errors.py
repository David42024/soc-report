"""Errors whose messages can be shown without upstream payloads or secrets."""


class AnalyticsError(Exception):
    """Base error with a safe, actionable user-facing message."""


class ConfigurationError(AnalyticsError):
    """An external configuration cannot be used safely."""


class DatasetError(AnalyticsError):
    """A registered source is unavailable or violates its format contract."""


class ServiceError(AnalyticsError):
    """A SOC endpoint failed without disclosing the upstream response."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code
