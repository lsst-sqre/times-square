"""Sentry integration helpers."""

import re
from collections.abc import Callable
from typing import Any

__all__ = ["make_traces_sampler"]

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
