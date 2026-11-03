"""Identity propagated to request audit records and PostgreSQL change triggers."""
from contextvars import ContextVar

identity = ContextVar("soc_identity", default=None)
