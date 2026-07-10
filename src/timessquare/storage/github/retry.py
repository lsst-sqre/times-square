"""Retry helper for transient GitHub API errors.

This module provides a small, isolated utility for making GitHub content
reads self-heal through brief GitHub API slowness. It retries an awaitable
GitHub call on *transient* errors (network/timeout errors and GitHub 5xx
responses) with exponential backoff and jitter, and fails fast on everything
else (e.g. GitHub 4xx, validation errors, YAML syntax errors), re-raising the
last error once the bounded number of attempts is exhausted.

The retry policy is a set of hardcoded, sensible constants rather than
configuration knobs. The ``sleep`` callable is injectable so tests can run
without actually waiting.
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable

import httpx
from gidgethub import GitHubBroken

__all__ = [
    "INITIAL_BACKOFF",
    "MAX_ATTEMPTS",
    "MAX_BACKOFF",
    "retry_transient_github_errors",
]

SleepCallable = Callable[[float], Awaitable[None]]
"""Signature of an awaitable sleep, e.g. `asyncio.sleep`."""

TRANSIENT_HTTPX_ERRORS: tuple[type[httpx.HTTPError], ...] = (
    httpx.ReadTimeout,
    httpx.ConnectTimeout,
    httpx.ConnectError,
    httpx.ReadError,
    httpx.WriteError,
    httpx.PoolTimeout,
    httpx.RemoteProtocolError,
)
"""httpx transport/timeout errors that indicate a transient failure."""

MAX_ATTEMPTS = 3
"""Total number of attempts (the initial call plus retries)."""

INITIAL_BACKOFF = 0.5
"""Base backoff delay, in seconds, before the first retry."""

MAX_BACKOFF = 5.0
"""Ceiling for the backoff delay, in seconds."""


def _is_transient(exc: BaseException) -> bool:
    """Classify whether an exception is a transient GitHub error worth
    retrying.
    """
    return isinstance(exc, (*TRANSIENT_HTTPX_ERRORS, GitHubBroken))


def _backoff_delay(attempt: int) -> float:
    """Compute the backoff delay before a retry with full jitter.

    Parameters
    ----------
    attempt
        The 1-based number of the attempt that just failed.

    Returns
    -------
    float
        Seconds to sleep before the next attempt.
    """
    delay = min(MAX_BACKOFF, INITIAL_BACKOFF * (2 ** (attempt - 1)))
    return random.uniform(0, delay)


async def retry_transient_github_errors[T](
    call: Callable[[], Awaitable[T]],
    *,
    sleep: SleepCallable = asyncio.sleep,
) -> T:
    """Run a GitHub call, retrying it on transient errors with exponential
    backoff and jitter.

    Parameters
    ----------
    call
        A zero-argument callable that returns a fresh awaitable each time it
        is invoked (e.g. ``lambda: github_client.getitem(...)``). A new
        awaitable is created for every attempt so each retry issues a fresh
        request.
    sleep
        Awaitable sleep used between attempts. Injectable so tests can avoid
        real delays; defaults to `asyncio.sleep`.

    Returns
    -------
    T
        The result of the first successful call.

    Raises
    ------
    Exception
        Re-raises the last transient error once `MAX_ATTEMPTS` is exhausted,
        or immediately re-raises any non-transient error.

    Examples
    --------
    Wrap a gidgethub request in a lambda rather than awaiting it directly,
    so that the helper can re-invoke it to create a fresh request for each
    attempt:

    >>> data = await retry_transient_github_errors(
    ...     lambda: github_client.getitem(
    ...         "repos/{owner}/{repo}/contents/{path}{?ref}",
    ...         url_vars={
    ...             "owner": "lsst-sqre",
    ...             "repo": "times-square-demo",
    ...             "path": "times-square.yaml",
    ...             "ref": head_sha,
    ...         },
    ...     )
    ... )

    Passing the coroutine itself (``retry_transient_github_errors(
    github_client.getitem(...))``) would not work: a coroutine can only be
    awaited once, so retries would fail.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            return await call()
        except Exception as exc:
            if not _is_transient(exc) or attempt >= MAX_ATTEMPTS:
                raise
            await sleep(_backoff_delay(attempt))
    # Unreachable: the loop either returns or raises on the final attempt.
    raise AssertionError("retry loop exited without returning or raising")
