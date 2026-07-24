"""Tests for the GitHubCheckRunService."""

from __future__ import annotations

import json
import warnings
from collections import deque
from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import respx
import structlog
from gidgethub.httpx import GitHubAPI
from httpx import Response
from safir.database import (
    create_database_engine,
    initialize_database,
    stamp_database_async,
)
from safir.dependencies.db_session import db_session_dependency
from safir.github.webhooks import GitHubCheckRunEventModel

from timessquare.config import config
from timessquare.dbschema import Base
from timessquare.domain.githubcheckrun import NotebookExecutionsCheck
from timessquare.domain.page import PageExecutionInfo, PageModel
from timessquare.domain.pageparameters import PageParameters
from timessquare.factory import ProcessContext, WorkerFactory
from timessquare.services.githubcheckrun import GitHubCheckRunService
from timessquare.services.githubrepo import GitHubRepoService
from timessquare.storage.noteburst import NoteburstJobModel

JOB_URL = "https://test.example.com/noteburst/v1/notebooks/xyz"


@pytest_asyncio.fixture
async def check_run_service() -> AsyncGenerator[GitHubCheckRunService]:
    """Return a GitHubCheckRunService wired to real services.

    The GitHub client and repository service are constructed but not
    exercised by the timeout-reporting path under test.
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

    async for db_session in db_session_dependency():
        factory = WorkerFactory(
            logger=logger,
            session=db_session,
            process_context=process_context,
        )
        page_service = factory.create_page_service()
        github_client = GitHubAPI(process_context.http_client, "times-square")
        repo_service = GitHubRepoService(
            http_client=process_context.http_client,
            github_client=github_client,
            page_service=page_service,
            logger=logger,
        )
        yield GitHubCheckRunService(
            http_client=process_context.http_client,
            github_client=github_client,
            repo_service=repo_service,
            page_service=page_service,
            logger=logger,
        )

    await process_context.aclose()
    await db_session_dependency.aclose()


def _make_check() -> NotebookExecutionsCheck:
    """Create a NotebookExecutionsCheck from a sample check-run webhook."""
    payload_path = (
        Path(__file__).parent.parent
        / "data"
        / "github_webhooks"
        / "check_run_created.json"
    )
    event = GitHubCheckRunEventModel.model_validate(
        json.loads(payload_path.read_text())
    )
    return NotebookExecutionsCheck(event.check_run, event.repository)


def _make_page_execution() -> PageExecutionInfo:
    """Create a GitHub-backed PageExecutionInfo with a pending job."""
    ipynb = (Path(__file__).parent.parent / "data" / "demo.ipynb").read_text()
    notebook = PageModel.read_ipynb(ipynb)
    parameters = PageParameters.create_from_notebook(notebook)
    page = PageModel.create_from_repo(
        ipynb=ipynb,
        title="Demo",
        parameters=parameters,
        github_owner="Codertocat",
        github_repo="Hello-World",
        repository_path_prefix="notebooks",
        repository_display_path_prefix="notebooks",
        repository_path_stem="demo",
        repository_source_extension=".ipynb",
        repository_sidecar_extension=".yaml",
        repository_source_sha="abc123",
        repository_sidecar_sha="def456",
    )
    job = NoteburstJobModel.model_validate(
        {"date_submitted": datetime.now(tz=UTC), "job_url": JOB_URL}
    )
    return PageExecutionInfo(
        page=page,
        values={},
        noteburst_status_code=202,
        noteburst_job=job,
    )


@pytest.mark.asyncio
async def test_report_timeout_in_progress(
    check_run_service: GitHubCheckRunService,
    respx_mock: respx.Router,
) -> None:
    """An in-progress job at timeout reports its runtime and state, and no
    "coroutine was never awaited" warning is raised.
    """
    enqueue_time = datetime.now(tz=UTC) - timedelta(seconds=30)
    respx_mock.get(JOB_URL).mock(
        return_value=Response(
            200,
            json={
                "self_url": JOB_URL,
                "enqueue_time": enqueue_time.isoformat(),
                "start_time": (
                    enqueue_time + timedelta(seconds=5)
                ).isoformat(),
                "status": "in_progress",
            },
        )
    )

    check = _make_check()
    page_execution = _make_page_execution()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        await check_run_service._report_pr_notebook_timeout_errors(
            check, deque([page_execution])
        )

    coroutine_warnings = [
        w
        for w in caught
        if "coroutine" in str(w.message) and "never awaited" in str(w.message)
    ]
    assert not coroutine_warnings

    assert len(check.annotations) == 1
    message = check.annotations[0].message
    assert "still in progress" in message
    assert "seconds" in message

    assert len(check.notebook_executions) == 1
    runtime = check.notebook_executions[0].runtime
    assert runtime is not None
    assert runtime.total_seconds() > 0


@pytest.mark.asyncio
async def test_report_timeout_queued(
    check_run_service: GitHubCheckRunService,
    respx_mock: respx.Router,
) -> None:
    """A queued job at timeout reports the queued state."""
    respx_mock.get(JOB_URL).mock(
        return_value=Response(
            200,
            json={
                "self_url": JOB_URL,
                "enqueue_time": datetime.now(tz=UTC).isoformat(),
                "status": "queued",
            },
        )
    )

    check = _make_check()
    page_execution = _make_page_execution()

    await check_run_service._report_pr_notebook_timeout_errors(
        check, deque([page_execution])
    )

    assert len(check.annotations) == 1
    message = check.annotations[0].message
    assert "still in the Noteburst queue." in message


@pytest.mark.asyncio
async def test_report_timeout_noteburst_error(
    check_run_service: GitHubCheckRunService,
    respx_mock: respx.Router,
) -> None:
    """A failed Noteburst status lookup still reports the timeout with no
    runtime, and no exception escapes.
    """
    respx_mock.get(JOB_URL).mock(return_value=Response(500, text="boom"))

    check = _make_check()
    page_execution = _make_page_execution()

    await check_run_service._report_pr_notebook_timeout_errors(
        check, deque([page_execution])
    )

    assert len(check.annotations) == 1
    assert check.annotations[0].title == "Noteburst timeout"

    assert len(check.notebook_executions) == 1
    assert check.notebook_executions[0].runtime is None


@pytest.mark.asyncio
async def test_report_timeout_noteburst_unreachable(
    check_run_service: GitHubCheckRunService,
    respx_mock: respx.Router,
) -> None:
    """A transport error during the Noteburst status lookup still reports
    the timeout with no runtime, and no exception escapes.
    """
    respx_mock.get(JOB_URL).mock(
        side_effect=httpx.ConnectError("connection refused")
    )

    check = _make_check()
    page_execution = _make_page_execution()

    await check_run_service._report_pr_notebook_timeout_errors(
        check, deque([page_execution])
    )

    assert len(check.annotations) == 1
    assert check.annotations[0].title == "Noteburst timeout"

    assert len(check.notebook_executions) == 1
    assert check.notebook_executions[0].runtime is None
