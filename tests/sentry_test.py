"""Tests for the Sentry SDK configuration.

These are regression tests for DM-55927: sentry-sdk 2.x serializes frame
locals without a length limit, so an uncaught exception raised while a large
notebook is in flight produced an event over Sentry's 1 MiB ingest limit and
was dropped server-side as ``too_large:event``.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx
import sentry_sdk
from httpx import AsyncClient
from safir.testing.sentry import (
    Captured,
    capture_events_fixture,
    sentry_init_fixture,
)

from timessquare.config import config

NOTEBURST_URL = "https://test.example.com/noteburst/v1/notebooks/"

MAX_VALUE_LENGTH = 1100
"""Longest acceptable serialized string in an event.

This is the configured ``max_value_length`` (1024) plus room for the SDK's
truncation marker.
"""

MAX_EVENT_SIZE = 512 * 1024
"""Largest acceptable serialized event, comfortably under Sentry's 1 MiB
ingest limit.
"""


def _large_ipynb() -> str:
    """Return a notebook large enough (>100 KB) that unbounded serialization
    of the frame locals holding it overflows Sentry's event size limit.
    """
    data_path = Path(__file__).parent / "data" / "demo.ipynb"
    notebook = json.loads(data_path.read_text())
    filler = [
        f"Filler line {i:04d} of a deliberately enormous markdown cell.\n"
        for i in range(2000)
    ]
    notebook["cells"].insert(
        1,
        {
            "cell_type": "markdown",
            "id": "9d4b2f16-0000-4000-8000-000000000000",
            "metadata": {},
            "source": filler,
        },
    )
    return json.dumps(notebook)


def _iter_strings(value: Any) -> Iterator[str]:
    """Yield every string leaf of a serialized Sentry value."""
    match value:
        case str():
            yield value
        case dict():
            for item in value.values():
                yield from _iter_strings(item)
        case list() | tuple():
            for item in value:
                yield from _iter_strings(item)
        case _:
            pass


def _iter_frame_vars(event: dict[str, Any]) -> Iterator[tuple[str, str, str]]:
    """Yield ``(function, variable, string)`` for every string in the
    serialized local variables of every stack frame of an event.
    """
    for exception in event.get("exception", {}).get("values", []):
        frames = exception.get("stacktrace", {}).get("frames", [])
        for frame in frames:
            function = frame.get("function", "<unknown>")
            for name, value in (frame.get("vars") or {}).items():
                for string in _iter_strings(value):
                    yield function, name, string


@pytest.fixture
def sentry_events(monkeypatch: pytest.MonkeyPatch) -> Iterator[Captured]:
    """Capture Sentry events, reusing the service's own SDK options.

    The serialization options are read back from the live client, which both
    ``timessquare.main`` and ``timessquare.worker.main`` set up at import time
    with the same settings. Reusing them, rather than restating them here, is
    what makes this a regression test: if the service stops bounding the
    values it serializes, this fixture stops bounding them too.
    """
    app_options = sentry_sdk.get_client().options
    with sentry_init_fixture() as init:
        init(
            environment=app_options["environment"],
            before_send=app_options["before_send"],
            traces_sampler=app_options["traces_sampler"],
            max_value_length=app_options["max_value_length"],
        )
        yield capture_events_fixture(monkeypatch)()


@pytest.mark.asyncio
async def test_noteburst_error_event_size_is_bounded(
    client: AsyncClient,
    respx_mock: respx.Router,
    sentry_events: Captured,
) -> None:
    """An uncaught Noteburst error for a large notebook is small enough for
    Sentry to accept.
    """
    post_route = respx_mock.post(NOTEBURST_URL)
    post_route.mock(
        return_value=httpx.Response(
            202,
            json={
                "job_id": "xyz",
                "kernel_name": "",
                "enqueue_time": "2026-08-24T21:09:00Z",
                "status": "queued",
                "self_url": f"{NOTEBURST_URL}xyz",
            },
        )
    )
    r = await client.post(
        f"{config.path_prefix}/v1/pages",
        json={"title": "Demo", "ipynb": _large_ipynb()},
    )
    assert r.status_code == 201
    html_status_url = r.json()["html_status_url"]

    # Noteburst is now unreachable, as during a TLS outage. Polling a page
    # instance with no job in flight triggers a fresh execution request, and
    # the connection error propagates uncaught out of the handler.
    post_route.mock(side_effect=httpx.ConnectError("Connection refused"))
    with pytest.raises(httpx.ConnectError):
        await client.get(html_status_url, params={"A": 2})

    assert len(sentry_events.errors) == 1
    event = sentry_events.errors[0]

    oversized = [
        (function, name, len(string))
        for function, name, string in _iter_frame_vars(event)
        if len(string) > MAX_VALUE_LENGTH
    ]
    assert oversized == []

    assert len(json.dumps(event).encode()) < MAX_EVENT_SIZE
