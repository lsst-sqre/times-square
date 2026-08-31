"""Sentry integration helpers."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

import sentry_sdk
from safir.sentry import before_send_handler

from .config import config

__all__ = ["SENTRY_MAX_VALUE_LENGTH", "init_sentry", "make_traces_sampler"]

SENTRY_MAX_VALUE_LENGTH = 1024
"""Maximum length, in bytes, of a string serialized into a Sentry event.

sentry-sdk 2.x leaves this unbounded, which kept events carrying notebook
source from ever reaching Sentry; the changelog entry for DM-55927 has the
rationale and the trade-off.

The SDK's serializer clips every string in an event, not only frame locals:
exception messages, structlog messages, request bodies, tags, and ``extra``
values are all subject to this bound. Values added after serialization by a
``before_send`` handler are not, which exempts the contexts and tags Safir
builds from a ``SlackException``.
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


def init_sentry(
    *,
    traces_sampler: Callable[[dict[str, Any]], float] | None = None,
    traces_sample_rate: float | None = None,
) -> None:
    """Initialize the Sentry SDK for a Times Square process.

    Both the FastAPI app and the arq worker call this so that the options
    they must configure identically — the DSN, the environment, the
    ``before_send`` handler, and `SENTRY_MAX_VALUE_LENGTH` — are set in one
    place and cannot drift apart. Only the per-process tracing
    configuration is accepted; the shared options cannot be overridden.

    Parameters
    ----------
    traces_sampler
        Dynamic trace sampler for the calling process: the app passes the
        result of `make_traces_sampler` so SSE endpoints are never
        instrumented.
    traces_sample_rate
        Static trace sample rate: the worker, which serves no SSE
        endpoints, passes the configured rate.
    """
    sentry_sdk.init(
        dsn=config.sentry_dsn,
        environment=config.environment_name,
        before_send=before_send_handler,
        max_value_length=SENTRY_MAX_VALUE_LENGTH,
        traces_sampler=traces_sampler,
        traces_sample_rate=traces_sample_rate,
    )
