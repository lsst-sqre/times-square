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


def init_sentry(**options: Any) -> None:
    """Initialize the Sentry SDK for a Times Square process.

    Both the FastAPI app and the arq worker call this so that the options
    they must configure identically — the DSN, the environment, the
    ``before_send`` handler, and `SENTRY_MAX_VALUE_LENGTH` — are set in one
    place and cannot drift apart.

    Parameters
    ----------
    **options
        Additional Sentry options specific to the calling process, such as
        its tracing configuration: the app passes ``traces_sampler`` (see
        `make_traces_sampler`) while the worker, which serves no SSE
        endpoints, passes ``traces_sample_rate``. These are merged with, and
        may override, the shared options.
    """
    sentry_sdk.init(
        dsn=config.sentry_dsn,
        environment=config.environment_name,
        before_send=before_send_handler,
        max_value_length=SENTRY_MAX_VALUE_LENGTH,
        **options,
    )
