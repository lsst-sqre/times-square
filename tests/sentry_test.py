"""Tests for the Sentry SDK configuration.

These are regression tests for DM-55927: sentry-sdk 2.x serializes frame
locals without a length limit, so an uncaught exception raised while a large
notebook is in flight produced an event over Sentry's 1 MiB ingest limit and
was dropped server-side as ``too_large:event``.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import sys
from collections.abc import Iterator
from typing import Any

import httpx
import pytest
import respx
import sentry_sdk
from httpx import AsyncClient
from safir.sentry import before_send_handler
from safir.testing.sentry import Captured, capture_events_fixture
from safir.testing.sentry import TestTransport as SentryTestTransport

from timessquare.config import config
from timessquare.sentry import (
    SENTRY_MAX_VALUE_LENGTH,
    init_sentry,
    make_traces_sampler,
)

from .support.github import DATA
from .support.noteburst import NOTEBURST_URL, queued_job_response

SENTRY_INGEST_LIMIT = 1_048_576
"""Largest event Sentry's ingest API accepts, in bytes (1 MiB)."""

MAX_EVENT_SIZE = SENTRY_INGEST_LIMIT // 2
"""Largest acceptable serialized event.

Half of `SENTRY_INGEST_LIMIT`, so the test fails while there is still ample
headroom rather than at the point where real events start being dropped.
"""

MIN_IPYNB_SIZE = 100_000
"""Smallest notebook `_large_ipynb` may return, in bytes.

The unbounded event only grows past `MAX_EVENT_SIZE` once the notebook is
larger than roughly 47 KB, so a filler that silently shrank below that would
leave the test passing whether or not the values are bounded.
"""


def _large_ipynb() -> str:
    """Return a notebook large enough that unbounded serialization of the
    frame locals holding it overflows Sentry's event size limit.
    """
    notebook = json.loads((DATA / "demo.ipynb").read_text())
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
    ipynb = json.dumps(notebook)
    assert len(ipynb) > MIN_IPYNB_SIZE
    return ipynb


def _capture_sentry_init(
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, Any]:
    """Replace ``sentry_sdk.init`` with a recorder of its keyword arguments."""
    captured: dict[str, Any] = {}

    def fake_init(**kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(sentry_sdk, "init", fake_init)
    return captured


def _entrypoint_sentry_options(
    monkeypatch: pytest.MonkeyPatch, module_name: str
) -> dict[str, Any]:
    """Return the keyword arguments an entrypoint module passes to
    ``sentry_sdk.init`` when it is imported.

    Both entrypoints initialize Sentry as a module-level side effect, and both
    are already imported — with their init calls already spent — before any
    test runs. The module is therefore executed a second time here, in a
    throwaway namespace and with ``sentry_sdk.init`` replaced by a recorder,
    so that neither the real `sys.modules` entry nor the live Sentry client is
    disturbed. Asserting on the live client instead would only ever describe
    whichever entrypoint the test session imported last.
    """
    captured = _capture_sentry_init(monkeypatch)
    origin = importlib.import_module(module_name).__file__
    assert origin is not None
    # The probe's dotted name keeps it inside the real package, so the
    # module's relative imports resolve against the already-imported
    # timessquare modules instead of re-executing them.
    probe_name = f"{module_name}__sentry_probe"
    spec = importlib.util.spec_from_file_location(probe_name, origin)
    assert spec is not None
    assert spec.loader is not None
    probe = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, probe_name, probe)
    spec.loader.exec_module(probe)
    return captured


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
def sentry_events(monkeypatch: pytest.MonkeyPatch) -> Captured:
    """Capture the events the service's own Sentry client sends.

    The live client is the one an entrypoint configured at import time; only
    its transport is swapped out, so every option governing how an event is
    serialized stays exactly as the service set it. That is what makes this a
    regression test: nothing here re-states a limit, so if the service stops
    bounding the values it serializes, the captured events stop being bounded
    too.

    Which entrypoint won the import race is deliberately not this fixture's
    concern — `test_entrypoint_bounds_serialized_values` pins the bound for
    each entrypoint separately.
    """
    monkeypatch.setattr(
        sentry_sdk.get_client(), "transport", SentryTestTransport()
    )
    return capture_events_fixture(monkeypatch)()


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
    post_route.mock(return_value=queued_job_response())
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
    # A must differ from demo.ipynb's default of 4: with the default
    # parameters, get_html_and_status finds the job already stored for the
    # page at creation and polls it with get_job rather than POSTing a new
    # execution request, which fails on the unmocked GET with a confusing
    # respx AllMockedAssertionError instead of the ConnectError under test.
    with pytest.raises(httpx.ConnectError):
        await client.get(html_status_url, params={"A": 2})

    assert len(sentry_events.errors) == 1
    event = sentry_events.errors[0]

    oversized = [
        (function, name, len(string))
        for function, name, string in _iter_frame_vars(event)
        if len(string) > SENTRY_MAX_VALUE_LENGTH
    ]
    assert oversized == []

    assert len(json.dumps(event).encode()) < MAX_EVENT_SIZE


@pytest.mark.parametrize(
    ("module_name", "tracing_option"),
    [
        pytest.param("timessquare.main", "traces_sampler", id="api"),
        pytest.param(
            "timessquare.worker.main", "traces_sample_rate", id="worker"
        ),
    ],
)
def test_entrypoint_bounds_serialized_values(
    monkeypatch: pytest.MonkeyPatch, module_name: str, tracing_option: str
) -> None:
    """Both processes bound serialized values, and each brings its own
    tracing option.

    The bug this pins is asymmetric by nature: an entrypoint that stopped
    going through `init_sentry` would keep reporting oversized events even
    though the other entrypoint, and every assertion made against the live
    client, still looked correct.
    """
    options = _entrypoint_sentry_options(monkeypatch, module_name)

    assert options["max_value_length"] == SENTRY_MAX_VALUE_LENGTH
    assert options["dsn"] == config.sentry_dsn
    assert options["environment"] == config.environment_name
    assert options["before_send"] is before_send_handler
    assert tracing_option in options


def test_init_sentry_applies_shared_options(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The helper owns every option both processes must configure alike."""
    captured = _capture_sentry_init(monkeypatch)

    init_sentry()

    assert captured["dsn"] == config.sentry_dsn
    assert captured["environment"] == config.environment_name
    assert captured["before_send"] is before_send_handler
    assert captured["max_value_length"] == SENTRY_MAX_VALUE_LENGTH


@pytest.mark.parametrize(
    "tracing",
    [
        pytest.param({"traces_sampler": make_traces_sampler(0.1)}, id="api"),
        pytest.param({"traces_sample_rate": 0.1}, id="worker"),
    ],
)
def test_init_sentry_forwards_per_process_options(
    monkeypatch: pytest.MonkeyPatch, tracing: dict[str, Any]
) -> None:
    """Each process contributes its own tracing option as an argument."""
    captured = _capture_sentry_init(monkeypatch)

    init_sentry(**tracing)

    for name, value in tracing.items():
        assert captured[name] is value
    assert captured["max_value_length"] == SENTRY_MAX_VALUE_LENGTH
