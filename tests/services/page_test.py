"""Tests for the PageService execution-failure handling."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

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
from timessquare.domain.page import PageInstanceModel, PageModel
from timessquare.factory import ProcessContext, WorkerFactory
from timessquare.services.page import PageService

JOB_URL = "https://test.example.com/noteburst/v1/notebooks/xyz"


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
    respx_mock.get(JOB_URL).mock(
        return_value=Response(
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
    )
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
