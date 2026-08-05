"""Tests for the PageService execution-failure handling."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
import pytest_asyncio
import respx
import structlog
from httpx import Response
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
from timessquare.domain.page import PageInstanceModel, PageModel
from timessquare.domain.ssemodels import HtmlEventsModel
from timessquare.factory import ProcessContext, WorkerFactory
from timessquare.services.page import PageService
from timessquare.storage.noteburst import NoteburstJobStatus

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


def _failed_job() -> Response:
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
    data_line = next(
        line
        for line in first.decode().splitlines()
        if line.startswith("data:")
    )
    return json.loads(data_line[len("data:") :].strip())


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
    return await page_service._build_events_payload(
        page_instance=page_instance,
        html_key=html_key,
        query_params=query_params,
        html_base_url=HTML_BASE_URL,
    )


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
