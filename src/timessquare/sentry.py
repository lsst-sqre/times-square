"""Sentry integration helpers."""

import re
from collections.abc import Callable
from typing import Any

__all__ = ["SENTRY_MAX_VALUE_LENGTH", "make_traces_sampler"]

SENTRY_MAX_VALUE_LENGTH = 1024
"""Maximum length of any string serialized into a Sentry event.

sentry-sdk 2.x defaults to ``None``, i.e. unbounded serialization of local
variables. Times Square holds the full source of a notebook in the local
variables of several frames on the Noteburst submission path, so an uncaught
exception raised while a large notebook is in flight produced an event over
Sentry's 1 MiB ingest limit, which was then dropped server-side as
``too_large:event``. This restores the sentry-sdk 1.x limit.
"""

EVENTS_REGEX = re.compile("/pages/.*/events$")


def make_traces_sampler(
    original_rate: float,
) -> Callable[[dict[str, Any]], float]:
    """Don't instrument events SSE endpoint to avoid leaking memory.

    Sample every other trace at the configured rate.

    When an SSE endpoint is instrumented, Sentry accumlates spans for every
    sent event in memory until the initial connection is closed. Without Sentry
    tracing instrumentation, SSE endpoints don't leak memory.
    """

    def traces_sampler(context: dict[str, Any]) -> float:
        try:
            path = context["asgi_scope"]["path"]
            if EVENTS_REGEX.search(path):
                return 0
        except IndexError:
            pass
        return original_rate

    return traces_sampler
