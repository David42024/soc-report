"""Bounded workers whose futures remain private to each Streamlit session."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from typing import Callable, ParamSpec, TypeVar

P = ParamSpec("P")
T = TypeVar("T")


class TaskRunner:
    """Run I/O away from the Streamlit script without calling UI APIs in workers."""

    def __init__(self, workers: int) -> None:
        self._executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="soc-analytics")

    def submit(self, function: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> Future[T]:
        """Submit a task; the caller owns and removes the resulting future."""
        return self._executor.submit(function, *args, **kwargs)

    def close(self) -> None:
        """Release workers when a process or test ends."""
        self._executor.shutdown(wait=False, cancel_futures=True)
