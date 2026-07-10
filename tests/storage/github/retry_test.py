"""Tests for the transient-GitHub-error retry helper."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from http import HTTPStatus

import httpx
import pytest
from gidgethub import BadRequest, GitHubBroken

from timessquare.storage.github.retry import (
    MAX_ATTEMPTS,
    retry_transient_github_errors,
)


class FakeSleep:
    """An injectable async sleep that records durations instead of waiting."""

    def __init__(self) -> None:
        self.calls: list[float] = []

    async def __call__(self, seconds: float) -> None:
        self.calls.append(seconds)


def make_flaky_call(
    exc: BaseException, fail_times: int, result: str = "ok"
) -> Callable[[], Awaitable[str]]:
    """Build a zero-arg awaitable that raises ``exc`` the first ``fail_times``
    invocations and then returns ``result``.
    """
    state = {"count": 0}

    async def call() -> str:
        if state["count"] < fail_times:
            state["count"] += 1
            raise exc
        return result

    return call


@pytest.mark.asyncio
async def test_retry_then_recover() -> None:
    """A call that raises a transient error a couple of times and then
    succeeds returns the success value.
    """
    sleep = FakeSleep()
    call = make_flaky_call(httpx.ReadTimeout("slow"), fail_times=2)

    result = await retry_transient_github_errors(call, sleep=sleep)

    assert result == "ok"
    # Slept once between each of the two failed attempts.
    assert len(sleep.calls) == 2


@pytest.mark.asyncio
async def test_exhaustion_reraises_last_error() -> None:
    """A call that always raises a transient error re-raises after the max
    number of attempts.
    """
    sleep = FakeSleep()
    call = make_flaky_call(httpx.ConnectError("down"), fail_times=1000)

    with pytest.raises(httpx.ConnectError):
        await retry_transient_github_errors(call, sleep=sleep)

    # Bounded: slept between attempts but not after the final one.
    assert len(sleep.calls) == MAX_ATTEMPTS - 1


@pytest.mark.asyncio
async def test_fail_fast_on_non_transient() -> None:
    """A non-transient error is raised immediately without retrying."""
    sleep = FakeSleep()
    call = make_flaky_call(ValueError("nope"), fail_times=1000)

    with pytest.raises(ValueError, match="nope"):
        await retry_transient_github_errors(call, sleep=sleep)

    assert sleep.calls == []


@pytest.mark.asyncio
async def test_fail_fast_on_github_4xx() -> None:
    """A gidgethub 4xx error (e.g. BadRequest) is not retried."""
    sleep = FakeSleep()
    call = make_flaky_call(BadRequest(HTTPStatus.NOT_FOUND), fail_times=1000)

    with pytest.raises(BadRequest):
        await retry_transient_github_errors(call, sleep=sleep)

    assert sleep.calls == []


@pytest.mark.asyncio
async def test_github_5xx_is_retried() -> None:
    """A GitHub 5xx (gidgethub.GitHubBroken) is treated as transient and
    retried.
    """
    sleep = FakeSleep()
    call = make_flaky_call(
        GitHubBroken(HTTPStatus.INTERNAL_SERVER_ERROR), fail_times=1
    )

    result = await retry_transient_github_errors(call, sleep=sleep)

    assert result == "ok"
    assert len(sleep.calls) == 1
