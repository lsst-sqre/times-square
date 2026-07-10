"""Tests that the background/scheduled worker tasks log-and-skip a Noteburst
execution failure instead of raising and posting a Slack worker exception.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

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
from timessquare.domain.page import PageModel
from timessquare.factory import ProcessContext, WorkerFactory
from timessquare.storage.noteburst import NoteburstJobModel
from timessquare.worker.functions.replace_nbhtml import replace_nbhtml
from timessquare.worker.functions.scheduled_page_run import scheduled_page_run

NOTEBURST_URL = "https://test.example.com/noteburst/v1/notebooks/"
JOB_URL = "https://test.example.com/noteburst/v1/notebooks/xyz"


def _queued_response() -> Response:
    """Return a 202 queued Noteburst submit/poll response."""
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


def _failed_response() -> Response:
    """Return a completed Noteburst response reporting a timeout execution
    failure (``ipynb=None``, ``success=False``).
    """
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
            "error": {"code": "timeout", "message": "timed out"},
        },
    )


def _contract_violation_response() -> Response:
    """Return a completed Noteburst response with the impossible
    ``success=True`` + ``ipynb=None`` state.
    """
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
            "ipynb": None,
        },
    )


@pytest_asyncio.fixture
async def worker_ctx() -> AsyncGenerator[dict[str, Any]]:
    """Return an arq worker ``ctx`` with a mock Slack client.

    The context wires up the database and a `ProcessContext` the way the real
    worker startup does, plus a mock Slack client so tests can assert whether
    the worker-exception Slack message was posted.
    """
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

    ctx: dict[str, Any] = {
        "logger": logger,
        "process_context": process_context,
        "slack": AsyncMock(),
    }
    yield ctx

    await process_context.aclose()
    await db_session_dependency.aclose()


async def _create_demo_page(process_context: ProcessContext) -> str:
    """Create and commit a demo page, returning its name."""
    ipynb_path = Path(__file__).parent.parent.parent / "data" / "demo.ipynb"
    page = PageModel.create_from_api_upload(
        ipynb=ipynb_path.read_text(),
        title="Demo",
        uploader_username="testuser",
    )
    logger = structlog.get_logger(config.logger_name)
    async for db_session in db_session_dependency():
        factory = WorkerFactory(
            logger=logger,
            session=db_session,
            process_context=process_context,
        )
        page_service = factory.create_page_service()
        await page_service.add_page_to_store(page)
        await db_session.commit()
    return page.name


@pytest.mark.asyncio
async def test_scheduled_page_run_execution_failure_logs_and_skips(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """scheduled_page_run completes normally on an execution failure without
    posting a worker-exception Slack message.
    """
    page_name = await _create_demo_page(worker_ctx["process_context"])

    respx_mock.post(NOTEBURST_URL).mock(return_value=_queued_response())
    respx_mock.get(JOB_URL).mock(return_value=_failed_response())

    result = await scheduled_page_run(
        worker_ctx,
        page_name=page_name,
        scheduled_time=datetime.now(tz=UTC),
    )

    assert result == "Done"
    worker_ctx["slack"].post.assert_not_called()


@pytest.mark.asyncio
async def test_scheduled_page_run_contract_violation_posts_slack(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """A genuine contract violation still raises and posts a Slack message."""
    page_name = await _create_demo_page(worker_ctx["process_context"])

    respx_mock.post(NOTEBURST_URL).mock(return_value=_queued_response())
    respx_mock.get(JOB_URL).mock(return_value=_contract_violation_response())

    with pytest.raises(RuntimeError):
        await scheduled_page_run(
            worker_ctx,
            page_name=page_name,
            scheduled_time=datetime.now(tz=UTC),
        )

    worker_ctx["slack"].post.assert_called_once()


@pytest.mark.asyncio
async def test_replace_nbhtml_execution_failure_logs_and_skips(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """replace_nbhtml completes normally on an execution failure without
    posting a worker-exception Slack message.
    """
    page_name = await _create_demo_page(worker_ctx["process_context"])

    respx_mock.get(JOB_URL).mock(return_value=_failed_response())

    noteburst_job = NoteburstJobModel(
        date_submitted=datetime(2022, 3, 15, 4, 12, tzinfo=UTC),
        job_url=JOB_URL,  # type: ignore[arg-type]
    )
    result = await replace_nbhtml(
        worker_ctx,
        page_name=page_name,
        parameter_values={},
        noteburst_job=noteburst_job,
    )

    assert result == "Done"
    worker_ctx["slack"].post.assert_not_called()
