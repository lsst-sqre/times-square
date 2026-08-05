"""Tests for the PageService execution-failure handling."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_asyncio
import respx
import structlog
from httpx import Response
from pydantic import AnyHttpUrl
from safir.database import (
    create_database_engine,
    initialize_database,
    stamp_database_async,
)
from safir.dependencies.db_session import db_session_dependency

from timessquare.config import config
from timessquare.dbschema import Base
from timessquare.domain.executionoutcome import (
    NotebookExecutionErrorCode,
    NotebookExecutionFailure,
)
from timessquare.domain.nbhtml import NbDisplaySettings, NbHtmlKey
from timessquare.domain.page import (
    PageInstanceIdProtocol,
    PageInstanceModel,
    PageModel,
)
from timessquare.domain.ssemodels import HtmlEventsModel
from timessquare.factory import ProcessContext, WorkerFactory
from timessquare.services.page import (
    EVENTS_POLL_BASE_INTERVAL,
    EVENTS_POLL_MAX_INTERVAL,
    PageService,
)
from timessquare.storage.noteburst import NoteburstJobModel, NoteburstJobStatus

JOB_URL = "https://test.example.com/noteburst/v1/notebooks/xyz"
HTML_BASE_URL = "https://example.com/times-square/api/v1/pages/demo/html"


@pytest_asyncio.fixture
async def page_service() -> AsyncGenerator[PageService]:
    logger = structlog.get_logger(config.logger_name)

    engine = create_database_engine(
        config.database_url, config.database_password.get_secret_value()
    )
    await initialize_database(engine, logger, schema=Base.metadata, reset=True)
    await stamp_database_async(engine)
    await engine.dispose()

    await db_session_dependency.initialize(
        str(config.database_url), config.database_password.get_secret_value()
    )
    process_context = await ProcessContext.create()

    async for db_session in db_session_dependency():
        factory = WorkerFactory(
            logger=logger,
            session=db_session,
            process_context=process_context,
        )
        yield factory.create_page_service()

    await process_context.aclose()
    await db_session_dependency.aclose()


def _queued_post() -> Response:
    return Response(
        202,
        json={
            "job_id": "xyz",
            "kernel_name": "",
            "enqueue_time": datetime.now(tz=UTC).isoformat(),
            "status": "queued",
            "self_url": JOB_URL,
        },
    )


def _queued_job() -> Response:
    """Build a job-status response for a job that is still queued."""
    return Response(
        200,
        json={
            "job_id": "xyz",
            "kernel_name": "",
            "enqueue_time": "2022-03-15T04:12:00Z",
            "status": "queued",
            "self_url": JOB_URL,
        },
    )


def _in_progress_job() -> Response:
    """Build a job-status response for a job that is executing."""
    return Response(
        200,
        json={
            "job_id": "xyz",
            "kernel_name": "",
            "enqueue_time": "2022-03-15T04:12:00Z",
            "status": "in_progress",
            "self_url": JOB_URL,
            "start_time": "2022-03-15T04:13:00Z",
        },
    )


def _failed_job(
    *,
    enqueue_time: str = "2022-03-15T04:12:00Z",
    start_time: str = "2022-03-15T04:13:00Z",
    finish_time: str = "2022-03-15T04:13:10Z",
) -> Response:
    """Build a job-status response for a job that failed with a timeout.

    The execution's timestamps are overridable so that a test can simulate a
    re-execution that fails the same way at a later time.
    """
    return Response(
        200,
        json={
            "job_id": "xyz",
            "kernel_name": "",
            "enqueue_time": enqueue_time,
            "status": "complete",
            "self_url": JOB_URL,
            "start_time": start_time,
            "finish_time": finish_time,
            "success": False,
            "ipynb": None,
            "timeout": 30.0,
            "error": {"code": "timeout"},
        },
    )


def _successful_job(ipynb: str) -> Response:
    return Response(
        200,
        json={
            "job_id": "xyz",
            "kernel_name": "",
            "enqueue_time": "2022-03-15T04:12:00Z",
            "status": "complete",
            "self_url": JOB_URL,
            "start_time": "2022-03-15T04:13:00Z",
            "finish_time": "2022-03-15T04:13:10Z",
            "success": True,
            "ipynb": ipynb,
        },
    )


@pytest.mark.asyncio
async def test_terminal_failure_deletes_job_and_guards_reexecution(
    page_service: PageService, respx_mock: respx.Router
) -> None:
    """On a terminal Noteburst failure, the stale job record is deleted, the
    failure is cached, and later polls do not re-request execution.
    """
    ipynb = (Path(__file__).parent.parent / "data" / "demo.ipynb").read_text()
    page = PageModel.create_from_api_upload(
        ipynb=ipynb, title="Demo", uploader_username="testuser"
    )
    await page_service.add_page_to_store(page)

    page_instance = PageInstanceModel(page=page, values={"A": 2})

    post_route = respx_mock.post(
        "https://test.example.com/noteburst/v1/notebooks/"
    ).mock(return_value=_queued_post())

    # First status request enqueues a new execution and stores a job.
    respx_mock.get(JOB_URL).mock(return_value=_queued_post())
    status = await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    assert status.available is False
    assert status.execution_error is None
    assert (
        await page_service._job_store.get_instance(page_instance.id)
        is not None
    )
    posts_after_request = post_route.call_count

    # Noteburst reports a terminal failure.
    respx_mock.get(JOB_URL).mock(return_value=_failed_job())
    status = await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    assert status.available is False
    assert status.execution_error is not None
    assert status.execution_error.code == "timeout"

    # The stale job-store record was deleted, and the failure was cached.
    assert await page_service._job_store.get_instance(page_instance.id) is None
    assert (
        await page_service._execution_failure_store.get_instance(
            page_instance.id
        )
        is not None
    )

    # A later poll returns the cached failure without a new execution.
    posts_after_failure = post_route.call_count
    status = await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    assert status.execution_error is not None
    assert post_route.call_count == posts_after_failure
    assert posts_after_failure == posts_after_request


@pytest.mark.asyncio
async def test_explicit_rerun_clears_cached_failure(
    page_service: PageService, respx_mock: respx.Router
) -> None:
    """Requesting a fresh execution clears a cached terminal failure, so the
    terminal state does not mask a re-run of a fixed notebook.
    """
    ipynb = (Path(__file__).parent.parent / "data" / "demo.ipynb").read_text()
    page = PageModel.create_from_api_upload(
        ipynb=ipynb, title="Demo", uploader_username="testuser"
    )
    await page_service.add_page_to_store(page)

    page_instance = PageInstanceModel(page=page, values={"A": 2})

    post_route = respx_mock.post(
        "https://test.example.com/noteburst/v1/notebooks/"
    ).mock(return_value=_queued_post())

    # Drive the page instance into a cached terminal failure.
    respx_mock.get(JOB_URL).mock(return_value=_queued_post())
    await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    respx_mock.get(JOB_URL).mock(return_value=_failed_job())
    status = await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    assert status.execution_error is not None

    # An explicit re-run request clears the cached failure.
    respx_mock.get(JOB_URL).mock(return_value=_queued_post())
    await page_service.request_noteburst_execution(page_instance)
    assert (
        await page_service._execution_failure_store.get_instance(
            page_instance.id
        )
        is None
    )

    # The next poll consults the fresh job rather than short-circuiting on the
    # stale terminal failure.
    posts_after_rerun = post_route.call_count
    status = await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    assert status.execution_error is None
    assert status.available is False
    assert post_route.call_count == posts_after_rerun


@pytest.mark.asyncio
async def test_live_job_takes_precedence_over_cached_failure(
    page_service: PageService, respx_mock: respx.Router
) -> None:
    """A live Noteburst job record wins over a cached terminal failure, so a
    marker written by a concurrent poll cannot hide a fresh execution.
    """
    ipynb = (Path(__file__).parent.parent / "data" / "demo.ipynb").read_text()
    page = PageModel.create_from_api_upload(
        ipynb=ipynb, title="Demo", uploader_username="testuser"
    )
    await page_service.add_page_to_store(page)

    page_instance = PageInstanceModel(page=page, values={"A": 2})

    post_route = respx_mock.post(
        "https://test.example.com/noteburst/v1/notebooks/"
    ).mock(return_value=_queued_post())

    # Drive the page instance into a cached terminal failure.
    respx_mock.get(JOB_URL).mock(return_value=_queued_post())
    await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    respx_mock.get(JOB_URL).mock(return_value=_failed_job())
    status = await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    assert status.execution_error is not None
    failure = status.execution_error

    # Simulate the race: a fresh execution stores a new job record, then a
    # concurrent poll of the old job re-writes the failure marker.
    respx_mock.get(JOB_URL).mock(return_value=_queued_post())
    await page_service.request_noteburst_execution(page_instance)
    await page_service._execution_failure_store.store_failure(
        failure=failure, page_id=page_instance.id
    )

    # The live job wins: a pending state, and no new execution request.
    posts_after_rerun = post_route.call_count
    status = await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    assert status.execution_error is None
    assert status.available is False
    assert post_route.call_count == posts_after_rerun


def _decode_sse(chunk: bytes) -> dict[str, Any]:
    """Decode the JSON payload carried by one encoded SSE event."""
    data_line = next(
        line
        for line in chunk.decode().splitlines()
        if line.startswith("data:")
    )
    return json.loads(data_line[len("data:") :].strip())


async def _first_event_payload(
    page_service: PageService,
    *,
    name: str,
    query_params: dict[str, Any],
) -> dict[str, Any]:
    """Consume the first SSE event from the events iterator and return its
    decoded JSON payload.
    """
    iterator = cast(
        "AsyncGenerator[bytes]",
        await page_service.get_html_events_iter(
            name=name,
            query_params=query_params,
            html_base_url=HTML_BASE_URL,
        ),
    )
    try:
        first = await anext(iterator)
    finally:
        await iterator.aclose()
    return _decode_sse(first)


@pytest.mark.asyncio
async def test_events_terminal_failure(
    page_service: PageService, respx_mock: respx.Router
) -> None:
    """The SSE events stream emits a terminal event carrying execution_error
    for a failed execution and performs the same cleanup as the interactive
    path (failure cached, stale job record deleted).
    """
    ipynb = (Path(__file__).parent.parent / "data" / "demo.ipynb").read_text()
    page = PageModel.create_from_api_upload(
        ipynb=ipynb, title="Demo", uploader_username="testuser"
    )
    await page_service.add_page_to_store(page)
    page_instance = PageInstanceModel(page=page, values={"A": 2})

    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=_queued_post()
    )

    # Seed a Noteburst job record (the SSE iterator only reads existing jobs).
    respx_mock.get(JOB_URL).mock(return_value=_queued_post())
    await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    assert (
        await page_service._job_store.get_instance(page_instance.id)
        is not None
    )

    # Noteburst now reports a terminal execution failure.
    respx_mock.get(JOB_URL).mock(return_value=_failed_job())

    payload = await _first_event_payload(
        page_service, name=page.name, query_params={"A": 2}
    )
    assert payload["execution_error"] is not None
    assert payload["execution_error"]["code"] == "timeout"
    assert payload["execution_error"]["title"]
    assert payload["execution_error"]["message"]

    # Same cleanup as the interactive path.
    assert await page_service._job_store.get_instance(page_instance.id) is None
    assert (
        await page_service._execution_failure_store.get_instance(
            page_instance.id
        )
        is not None
    )

    # With the job record gone, the stream keeps reporting the terminal
    # failure from the cached marker.
    payload = await _first_event_payload(
        page_service, name=page.name, query_params={"A": 2}
    )
    assert payload["execution_error"] is not None
    assert payload["execution_error"]["code"] == "timeout"


@pytest.mark.asyncio
async def test_events_normal_has_null_execution_error(
    page_service: PageService, respx_mock: respx.Router
) -> None:
    """execution_error is null on the SSE payload in the normal pending
    case (backward compatible).
    """
    ipynb = (Path(__file__).parent.parent / "data" / "demo.ipynb").read_text()
    page = PageModel.create_from_api_upload(
        ipynb=ipynb, title="Demo", uploader_username="testuser"
    )
    await page_service.add_page_to_store(page)

    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=_queued_post()
    )
    respx_mock.get(JOB_URL).mock(return_value=_queued_post())
    await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )

    payload = await _first_event_payload(
        page_service, name=page.name, query_params={"A": 2}
    )
    assert payload["execution_error"] is None


@pytest.mark.asyncio
async def test_events_stale_html_survives_failed_background_refresh(
    page_service: PageService, respx_mock: respx.Router
) -> None:
    """While stale HTML is cached, a background refresh that fails does not
    turn the SSE stream terminal: the stream keeps reporting the cached HTML,
    and failure handling is left to the background worker that owns the
    refresh.
    """
    ipynb = (Path(__file__).parent.parent / "data" / "demo.ipynb").read_text()
    page = PageModel.create_from_api_upload(
        ipynb=ipynb, title="Demo", uploader_username="testuser"
    )
    await page_service.add_page_to_store(page)
    page_instance = PageInstanceModel(page=page, values={"A": 2})

    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=_queued_post()
    )

    # Render and cache HTML for the page instance.
    respx_mock.get(JOB_URL).mock(return_value=_queued_post())
    await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    respx_mock.get(JOB_URL).mock(return_value=_successful_job(ipynb))
    status = await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    assert status.available is True

    # A background refresh (as from soft_delete_html) puts a new job in flight
    # while the stale HTML stays cached...
    respx_mock.get(JOB_URL).mock(return_value=_queued_post())
    await page_service.request_noteburst_execution(page_instance)

    # ...and that refresh job completes as a terminal failure.
    respx_mock.get(JOB_URL).mock(return_value=_failed_job())

    payload = await _first_event_payload(
        page_service, name=page.name, query_params={"A": 2}
    )
    assert payload["execution_error"] is None
    assert payload["html_url"] is not None
    assert payload["html_hash"] is not None

    # No failure marker was cached, and the refresh job's record survives for
    # the worker that owns it.
    assert (
        await page_service._execution_failure_store.get_instance(
            page_instance.id
        )
        is None
    )
    assert (
        await page_service._job_store.get_instance(page_instance.id)
        is not None
    )


@pytest.mark.asyncio
async def test_events_live_job_takes_precedence_over_cached_failure(
    page_service: PageService, respx_mock: respx.Router
) -> None:
    """On the SSE stream a live Noteburst job record wins over a cached
    terminal failure, so a marker written by a concurrent poll of a superseded
    job cannot hide an execution that is still in flight.
    """
    ipynb = (Path(__file__).parent.parent / "data" / "demo.ipynb").read_text()
    page = PageModel.create_from_api_upload(
        ipynb=ipynb, title="Demo", uploader_username="testuser"
    )
    await page_service.add_page_to_store(page)
    page_instance = PageInstanceModel(page=page, values={"A": 2})

    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=_queued_post()
    )

    # A pending job is in flight...
    respx_mock.get(JOB_URL).mock(return_value=_queued_post())
    await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    assert (
        await page_service._job_store.get_instance(page_instance.id)
        is not None
    )

    # ...and a stale failure marker exists from a superseded execution.
    await page_service._execution_failure_store.store_failure(
        failure=NotebookExecutionFailure(
            code=NotebookExecutionErrorCode.timeout,
            title="Notebook execution timeout",
            message="A stale failure from a superseded job.",
        ),
        page_id=page_instance.id,
    )

    payload = await _first_event_payload(
        page_service, name=page.name, query_params={"A": 2}
    )
    assert payload["execution_error"] is None

    # The in-flight job record is untouched.
    assert (
        await page_service._job_store.get_instance(page_instance.id)
        is not None
    )


async def _create_demo_page(page_service: PageService) -> PageModel:
    """Add the demo notebook to the page store and return its page model."""
    ipynb = (Path(__file__).parent.parent / "data" / "demo.ipynb").read_text()
    page = PageModel.create_from_api_upload(
        ipynb=ipynb, title="Demo", uploader_username="testuser"
    )
    await page_service.add_page_to_store(page)
    return page


async def _build_payload(
    page_service: PageService,
    *,
    page: PageModel,
    query_params: dict[str, Any],
) -> HtmlEventsModel:
    """Build one events payload directly through the service helper."""
    page_instance = PageInstanceModel(page=page, values=dict(query_params))
    html_key = NbHtmlKey(
        display_settings=NbDisplaySettings.from_url_params(query_params),
        page_instance_id=page_instance.id,
    )
    poll = await page_service._build_events_payload(
        page_instance=page_instance,
        html_key=html_key,
        query_params=query_params,
        html_base_url=HTML_BASE_URL,
    )
    return poll.payload


@pytest.mark.asyncio
async def test_build_events_payload_no_state(
    page_service: PageService, respx_mock: respx.Router
) -> None:
    """With no job in flight and no cached HTML, the payload reports an
    all-null state and the bare HTML URL.
    """
    page = await _create_demo_page(page_service)

    payload = await _build_payload(
        page_service, page=page, query_params={"A": 2}
    )

    assert payload.execution_status is None
    assert payload.date_submitted is None
    assert payload.date_started is None
    assert payload.date_finished is None
    assert payload.execution_duration is None
    assert payload.html_hash is None
    assert payload.execution_error is None
    assert str(payload.html_url) == HTML_BASE_URL


@pytest.mark.asyncio
async def test_build_events_payload_in_flight_job(
    page_service: PageService, respx_mock: respx.Router
) -> None:
    """With a Noteburst job in flight, the payload reports the job's status
    and submission time and no HTML.
    """
    page = await _create_demo_page(page_service)

    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=_queued_post()
    )
    respx_mock.get(JOB_URL).mock(return_value=_queued_job())
    await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )

    payload = await _build_payload(
        page_service, page=page, query_params={"A": 2}
    )

    assert payload.execution_status == NoteburstJobStatus.queued
    assert payload.date_submitted is not None
    assert payload.date_finished is None
    assert payload.execution_duration is None
    assert payload.html_hash is None
    assert payload.execution_error is None


@pytest.mark.asyncio
async def test_build_events_payload_cached_html(
    page_service: PageService, respx_mock: respx.Router
) -> None:
    """With HTML cached for the page instance, the payload reports a complete
    execution and the HTML's hash and URL.
    """
    ipynb = (Path(__file__).parent.parent / "data" / "demo.ipynb").read_text()
    page = await _create_demo_page(page_service)

    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=_queued_post()
    )
    respx_mock.get(JOB_URL).mock(return_value=_queued_post())
    await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    respx_mock.get(JOB_URL).mock(return_value=_successful_job(ipynb))
    status = await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    assert status.available is True

    payload = await _build_payload(
        page_service, page=page, query_params={"A": 2}
    )

    assert payload.execution_status == NoteburstJobStatus.complete
    assert payload.date_started is not None
    assert payload.date_finished is not None
    assert payload.execution_duration is not None
    assert payload.execution_duration.total_seconds() == 10.0
    assert payload.html_hash is not None
    assert str(payload.html_url).startswith(HTML_BASE_URL)
    assert "ts_hide_code" in str(payload.html_url)
    assert payload.execution_error is None


@pytest.mark.asyncio
async def test_build_events_payload_terminal_failure(
    page_service: PageService, respx_mock: respx.Router
) -> None:
    """When Noteburst reports a terminal failure, the payload carries the
    execution error and the stale job record is cleaned up.
    """
    page = await _create_demo_page(page_service)
    page_instance = PageInstanceModel(page=page, values={"A": 2})

    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=_queued_post()
    )
    respx_mock.get(JOB_URL).mock(return_value=_queued_post())
    await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )
    respx_mock.get(JOB_URL).mock(return_value=_failed_job())

    payload = await _build_payload(
        page_service, page=page, query_params={"A": 2}
    )

    assert payload.execution_error is not None
    assert payload.execution_error.code == "timeout"
    assert payload.html_hash is None
    assert await page_service._job_store.get_instance(page_instance.id) is None
    assert (
        await page_service._execution_failure_store.get_instance(
            page_instance.id
        )
        is not None
    )


def test_events_poll_interval_backs_off_when_idle() -> None:
    """While a subscribed stream is idle, the poll interval doubles after each
    poll, starting at the base interval and capped at the maximum interval.
    """
    intervals = [EVENTS_POLL_BASE_INTERVAL]
    for _ in range(4):
        intervals.append(
            PageService._next_events_poll_interval(
                interval=intervals[-1],
                is_idle=True,
                base_interval=EVENTS_POLL_BASE_INTERVAL,
                max_interval=EVENTS_POLL_MAX_INTERVAL,
            )
        )

    assert intervals == [1.0, 2.0, 4.0, 8.0, 10.0]


def test_events_poll_interval_resets_when_not_idle() -> None:
    """A poll that is not idle — a job record exists, or the payload changed —
    returns the interval to the base interval however far it had backed off.
    """
    assert (
        PageService._next_events_poll_interval(
            interval=EVENTS_POLL_MAX_INTERVAL,
            is_idle=False,
            base_interval=EVENTS_POLL_BASE_INTERVAL,
            max_interval=EVENTS_POLL_MAX_INTERVAL,
        )
        == EVENTS_POLL_BASE_INTERVAL
    )


QUIET_WINDOW = 0.2
"""Seconds to watch a subscribed stream for an event that must not arrive."""

EVENT_TIMEOUT = 5.0
"""Seconds to wait for an event that must arrive."""


FAST_POLL_INTERVAL = 0.01
"""Poll interval injected into streams whose behavior does not depend on the
backoff, so that a quiet window of a fraction of a second covers many polls.
"""

BACKOFF_BASE_INTERVAL = 0.001
"""Base poll interval injected into streams that exercise the backoff."""

BACKOFF_MAX_INTERVAL = QUIET_WINDOW
"""Maximum poll interval injected into streams that exercise the backoff."""

MAX_IDLE_POLLS = 20
"""Most polls a backed-off stream can make in a quiet window.

Doubling from `BACKOFF_BASE_INTERVAL` exhausts the window in about nine polls,
whereas a stream pinned to the base interval would poll
``QUIET_WINDOW / BACKOFF_BASE_INTERVAL`` (200) times at most. Real polls are
slower than that theoretical maximum, which only makes a stream's poll count
smaller, so this upper bound holds however loaded the runner is.
"""

MAX_BACKED_OFF_POLLS = 2
"""Most polls a stream whose interval stayed at `BACKOFF_MAX_INTERVAL` can make
in a quiet window.

`BACKOFF_MAX_INTERVAL` is `QUIET_WINDOW`, so such a stream polls once per
window at most, plus one more if a poll lands on the window's edge.
"""

MIN_RESET_POLLS = 5
"""Fewest polls a stream that returned to `BACKOFF_BASE_INTERVAL` must make in
a quiet window for the reset to be proven.

The bound only has to separate a reset stream from one still polling at
`BACKOFF_MAX_INTERVAL`, which manages `MAX_BACKED_OFF_POLLS` polls at most, so
it is deliberately far below the ``QUIET_WINDOW / BACKOFF_BASE_INTERVAL`` (200)
polls the base interval allows in theory. It leaves each poll
``QUIET_WINDOW / MIN_RESET_POLLS`` (40 ms) for its Redis round trips — orders
of magnitude more than they take — so a loaded runner does not turn the
assertion into a flake.
"""


@asynccontextmanager
async def _events_stream(
    page_service: PageService,
    *,
    name: str,
    query_params: dict[str, Any],
    base_interval: float = FAST_POLL_INTERVAL,
    max_interval: float = FAST_POLL_INTERVAL,
) -> AsyncIterator[AsyncGenerator[bytes]]:
    """Subscribe to a page's SSE events stream for the duration of the
    context, closing the stream on exit.
    """
    iterator = cast(
        "AsyncGenerator[bytes]",
        await page_service.get_html_events_iter(
            name=name,
            query_params=query_params,
            html_base_url=HTML_BASE_URL,
            base_poll_interval=base_interval,
            max_poll_interval=max_interval,
        ),
    )
    try:
        yield iterator
    finally:
        await iterator.aclose()


def _count_polls(
    page_service: PageService, monkeypatch: pytest.MonkeyPatch
) -> list[str]:
    """Record the events loop's polls by spying on the job-store lookup that
    starts every poll, returning the list the polls are recorded in.
    """
    polls: list[str] = []
    get_instance = page_service._job_store.get_instance

    async def counting_get_instance(
        page_id: PageInstanceIdProtocol,
    ) -> NoteburstJobModel | None:
        polls.append(page_id.cache_key)
        return await get_instance(page_id)

    monkeypatch.setattr(
        page_service._job_store, "get_instance", counting_get_instance
    )
    return polls


async def _next_event(iterator: AsyncGenerator[bytes]) -> dict[str, Any]:
    """Wait for the stream's next event and return its decoded payload."""
    chunk = await asyncio.wait_for(anext(iterator), EVENT_TIMEOUT)
    return _decode_sse(chunk)


def _watch_for_event(iterator: AsyncGenerator[bytes]) -> asyncio.Task[bytes]:
    """Start waiting for the stream's next event without blocking, letting the
    stream keep polling in the background.
    """
    return asyncio.create_task(anext(iterator))


async def _assert_quiet(watcher: asyncio.Task[bytes]) -> None:
    """Assert that no event arrives on a watched stream while the page
    instance's state is unchanged.
    """
    await asyncio.sleep(QUIET_WINDOW)
    assert not watcher.done()


async def _await_watched_event(watcher: asyncio.Task[bytes]) -> dict[str, Any]:
    """Wait for a watched stream's pending event and return its payload."""
    return _decode_sse(await asyncio.wait_for(watcher, EVENT_TIMEOUT))


async def _cancel_watcher(watcher: asyncio.Task[bytes]) -> None:
    """Stop watching a stream for an event that never arrived."""
    watcher.cancel()
    with suppress(asyncio.CancelledError):
        await watcher


@pytest.mark.asyncio
async def test_events_initial_snapshot_then_silence(
    page_service: PageService, respx_mock: respx.Router
) -> None:
    """Subscribing to a page with no job in flight and no cached HTML yields
    exactly one initial all-null event, and nothing further while the page
    instance's state is unchanged.
    """
    page = await _create_demo_page(page_service)

    async with _events_stream(
        page_service, name=page.name, query_params={"A": 2}
    ) as stream:
        payload = await _next_event(stream)
        assert payload["execution_status"] is None
        assert payload["date_submitted"] is None
        assert payload["date_started"] is None
        assert payload["date_finished"] is None
        assert payload["execution_duration"] is None
        assert payload["html_hash"] is None
        assert payload["execution_error"] is None
        assert payload["html_url"] == HTML_BASE_URL

        watcher = _watch_for_event(stream)
        await _assert_quiet(watcher)
        await _cancel_watcher(watcher)


@pytest.mark.asyncio
async def test_events_emits_once_per_state_change(
    page_service: PageService, respx_mock: respx.Router
) -> None:
    """Each execution state transition produces exactly one event, while the
    identical polls between transitions produce none.
    """
    ipynb = (Path(__file__).parent.parent / "data" / "demo.ipynb").read_text()
    page = await _create_demo_page(page_service)
    page_instance = PageInstanceModel(page=page, values={"A": 2})

    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=_queued_post()
    )
    job_route = respx_mock.get(JOB_URL).mock(return_value=_queued_job())
    await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )

    async with _events_stream(
        page_service, name=page.name, query_params={"A": 2}
    ) as stream:
        queued = await _next_event(stream)
        assert queued["execution_status"] == "queued"

        # The stream keeps polling the unchanged job without emitting.
        watcher = _watch_for_event(stream)
        polls_before = job_route.call_count
        await _assert_quiet(watcher)
        assert job_route.call_count > polls_before

        # The transition to in_progress produces the pending event.
        job_route.mock(return_value=_in_progress_job())
        in_progress = await _await_watched_event(watcher)
        assert in_progress["execution_status"] == "in_progress"
        assert in_progress["date_started"] is not None
        assert in_progress["date_finished"] is None

        # ...and so does the transition to complete, which the stream itself
        # finishes by rendering the HTML and clearing the job record.
        job_route.mock(return_value=_successful_job(ipynb))
        complete = await _next_event(stream)
        assert complete["execution_status"] == "complete"
        assert complete["date_finished"] is not None
        assert complete["execution_duration"] == 10.0
        assert complete["execution_error"] is None
        assert complete["html_hash"] is not None
        assert complete["html_url"].startswith(HTML_BASE_URL)
        assert (
            await page_service._job_store.get_instance(page_instance.id)
            is None
        )


@pytest.mark.asyncio
async def test_events_terminal_failure_emits_once_and_stays_open(
    page_service: PageService, respx_mock: respx.Router
) -> None:
    """A terminal execution failure produces exactly one event carrying
    execution_error, with the same cleanup as the interactive path, and the
    stream stays open so a later re-execution is observed without the client
    resubscribing.
    """
    page = await _create_demo_page(page_service)
    page_instance = PageInstanceModel(page=page, values={"A": 2})

    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=_queued_post()
    )
    job_route = respx_mock.get(JOB_URL).mock(return_value=_queued_job())
    await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )

    async with _events_stream(
        page_service, name=page.name, query_params={"A": 2}
    ) as stream:
        queued = await _next_event(stream)
        assert queued["execution_error"] is None

        # Noteburst reports a terminal failure.
        job_route.mock(return_value=_failed_job())
        failed = await _next_event(stream)
        assert failed["execution_error"] is not None
        assert failed["execution_error"]["code"] == "timeout"

        # Same cleanup as the interactive path.
        assert (
            await page_service._job_store.get_instance(page_instance.id)
            is None
        )
        assert (
            await page_service._execution_failure_store.get_instance(
                page_instance.id
            )
            is not None
        )

        # The terminal failure is reported once, not on every later poll.
        watcher = _watch_for_event(stream)
        await _assert_quiet(watcher)

        # The stream is still open, so a re-execution is reported on it.
        job_route.mock(return_value=_queued_job())
        await page_service._job_store.store_job(
            job=NoteburstJobModel(
                date_submitted=datetime.now(tz=UTC),
                job_url=AnyHttpUrl(JOB_URL),
            ),
            page_id=page_instance.id,
        )
        rerun = await _await_watched_event(watcher)
        assert rerun["execution_status"] == "queued"
        assert rerun["execution_error"] is None


@pytest.mark.asyncio
async def test_events_reexecution_failing_identically_is_reported(
    page_service: PageService, respx_mock: respx.Router
) -> None:
    """A re-execution that fails with the same error within a single poll gap
    is reported, even though the stream never observes the intervening queued
    state: only the cached failure marker's restatement of an already-reported
    failure is suppressed.
    """
    page = await _create_demo_page(page_service)
    page_instance = PageInstanceModel(page=page, values={"A": 2})

    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=_queued_post()
    )
    job_route = respx_mock.get(JOB_URL).mock(return_value=_queued_job())
    await page_service.get_html_and_status(
        name=page.name, query_params={"A": 2}
    )

    async with _events_stream(
        page_service, name=page.name, query_params={"A": 2}
    ) as stream:
        await _next_event(stream)

        # The first execution fails terminally, which is reported once.
        job_route.mock(return_value=_failed_job())
        failed = await _next_event(stream)
        assert failed["execution_error"]["code"] == "timeout"
        assert failed["date_started"] is not None

        # The marker restatement of that failure is not re-emitted.
        watcher = _watch_for_event(stream)
        await _assert_quiet(watcher)

        # A re-execution is queued and fails identically before the next poll,
        # so that poll goes straight from a live job record to the same
        # failure classified afresh. Mock the new outcome before storing the
        # job record so that no poll can see the record alongside the old one.
        job_route.mock(
            return_value=_failed_job(
                enqueue_time="2022-03-15T05:12:00Z",
                start_time="2022-03-15T05:13:00Z",
                finish_time="2022-03-15T05:13:20Z",
            )
        )
        await page_service._job_store.store_job(
            job=NoteburstJobModel(
                date_submitted=datetime.now(tz=UTC),
                job_url=AnyHttpUrl(JOB_URL),
            ),
            page_id=page_instance.id,
        )

        # The identical failure of the new execution is reported, with the new
        # execution's dates rather than the marker's nulls.
        refailed = await _await_watched_event(watcher)
        assert refailed["execution_error"] == failed["execution_error"]
        assert refailed["execution_status"] == "complete"
        assert refailed["date_started"] is not None
        assert refailed["date_started"] != failed["date_started"]
        assert refailed["date_finished"] is not None
        assert refailed["execution_duration"] == 20.0

        # The new failure is itself reported only once.
        watcher = _watch_for_event(stream)
        await _assert_quiet(watcher)
        await _cancel_watcher(watcher)
        assert (
            await page_service._job_store.get_instance(page_instance.id)
            is None
        )


@pytest.mark.asyncio
async def test_events_idle_stream_backs_off(
    page_service: PageService,
    respx_mock: respx.Router,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An idle subscription polls the page instance's state progressively less
    often, instead of once per base interval for as long as it stays open.
    """
    page = await _create_demo_page(page_service)

    async with _events_stream(
        page_service,
        name=page.name,
        query_params={"A": 2},
        base_interval=BACKOFF_BASE_INTERVAL,
        max_interval=BACKOFF_MAX_INTERVAL,
    ) as stream:
        await _next_event(stream)

        watcher = _watch_for_event(stream)
        polls = _count_polls(page_service, monkeypatch)
        await asyncio.sleep(QUIET_WINDOW)
        idle_polls = len(polls)
        await _cancel_watcher(watcher)

    assert idle_polls > 0
    assert idle_polls <= MAX_IDLE_POLLS


@pytest.mark.asyncio
async def test_events_backoff_resets_when_a_job_appears(
    page_service: PageService,
    respx_mock: respx.Router,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A backed-off idle stream returns to the base poll interval once a
    Noteburst job record exists for the page instance, so an execution is
    reported promptly however long the stream idled first.
    """
    page = await _create_demo_page(page_service)
    page_instance = PageInstanceModel(page=page, values={"A": 2})
    respx_mock.get(JOB_URL).mock(return_value=_queued_job())

    async with _events_stream(
        page_service,
        name=page.name,
        query_params={"A": 2},
        base_interval=BACKOFF_BASE_INTERVAL,
        max_interval=BACKOFF_MAX_INTERVAL,
    ) as stream:
        await _next_event(stream)

        # The idle stream backs off...
        watcher = _watch_for_event(stream)
        polls = _count_polls(page_service, monkeypatch)
        await asyncio.sleep(QUIET_WINDOW)
        idle_polls = len(polls)

        # ...until an execution is queued for the page instance, which the
        # stream reports...
        await page_service._job_store.store_job(
            job=NoteburstJobModel(
                date_submitted=datetime.now(tz=UTC),
                job_url=AnyHttpUrl(JOB_URL),
            ),
            page_id=page_instance.id,
        )
        queued = await _await_watched_event(watcher)
        assert queued["execution_status"] == "queued"

        # ...and while that job is in flight the stream polls at the base
        # interval again, many times over in a window that a stream still
        # backed off to `BACKOFF_MAX_INTERVAL` would barely poll in at all.
        watcher = _watch_for_event(stream)
        polls.clear()
        await asyncio.sleep(QUIET_WINDOW)
        in_flight_polls = len(polls)
        assert not watcher.done()
        await _cancel_watcher(watcher)

    assert idle_polls <= MAX_IDLE_POLLS
    assert in_flight_polls >= MIN_RESET_POLLS


@pytest.mark.asyncio
async def test_events_successful_completion_renders_html_and_backs_off(
    page_service: PageService,
    respx_mock: respx.Router,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A stream that observes a successful completion renders and caches the
    HTML itself, so the subscriber gets the html_hash without any client
    requesting the HTML endpoint, and the settled stream then backs off.
    """
    ipynb = (Path(__file__).parent.parent / "data" / "demo.ipynb").read_text()
    page = await _create_demo_page(page_service)
    query_params: dict[str, Any] = {"A": 2}
    page_instance = PageInstanceModel(page=page, values=query_params)
    html_key = NbHtmlKey(
        display_settings=NbDisplaySettings.from_url_params(query_params),
        page_instance_id=page_instance.id,
    )

    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=_queued_post()
    )
    job_route = respx_mock.get(JOB_URL).mock(return_value=_queued_job())
    await page_service.get_html_and_status(
        name=page.name, query_params=query_params
    )

    async with _events_stream(
        page_service,
        name=page.name,
        query_params=query_params,
        base_interval=BACKOFF_BASE_INTERVAL,
        max_interval=BACKOFF_MAX_INTERVAL,
    ) as stream:
        queued = await _next_event(stream)
        assert queued["execution_status"] == "queued"
        assert queued["html_hash"] is None

        # The execution completes successfully while only the stream is
        # watching, and the stream reports the rendered HTML.
        job_route.mock(return_value=_successful_job(ipynb))
        complete = await _next_event(stream)
        assert complete["execution_status"] == "complete"
        assert complete["execution_error"] is None
        assert complete["html_hash"] is not None
        assert complete["html_url"].startswith(HTML_BASE_URL)

        # The stream finished the job the way the interactive path does.
        assert (
            await page_service._job_store.get_instance(page_instance.id)
            is None
        )
        assert (
            await page_service._html_store.get_instance(html_key) is not None
        )

        # With the job record cleared, the next poll re-derives the execution's
        # dates from the cached HTML, which settles the payload. This is the
        # same follow-up event a completion observed through the interactive
        # path produces.
        settled = await _next_event(stream)
        assert settled["execution_status"] == "complete"
        assert settled["html_hash"] == complete["html_hash"]

        # With the page instance settled, the stream goes quiet and backs off.
        watcher = _watch_for_event(stream)
        polls = _count_polls(page_service, monkeypatch)
        await asyncio.sleep(QUIET_WINDOW)
        idle_polls = len(polls)
        assert not watcher.done()
        await _cancel_watcher(watcher)

    assert idle_polls > 0
    assert idle_polls <= MAX_IDLE_POLLS
