"""Tests for the BackgroundPageService."""

from __future__ import annotations

import json
from base64 import b64encode
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path

import pytest
import pytest_asyncio
import respx
import structlog
from safir.database import (
    create_database_engine,
    initialize_database,
    stamp_database_async,
)
from safir.dependencies.db_session import db_session_dependency

from timessquare.config import config
from timessquare.dbschema import Base
from timessquare.domain.nbhtml import NbDisplaySettings, NbHtmlKey
from timessquare.domain.page import (
    PageInstanceIdModel,
    PageInstanceModel,
    PageModel,
)
from timessquare.factory import ProcessContext, WorkerFactory
from timessquare.services.backgroundpage import BackgroundPageService
from timessquare.storage.noteburst import (
    NoteburstJobModel,
    NoteburstJobResponseModel,
)

JOB_URL = "https://test.example.com/noteburst/v1/notebooks/xyz"


def _failed_noteburst_response() -> NoteburstJobResponseModel:
    """Return a completed Noteburst response reporting a timeout execution
    failure (``ipynb=None``, ``success=False``).
    """
    return NoteburstJobResponseModel.model_validate(
        {
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
        }
    )


def _contract_violation_noteburst_response() -> NoteburstJobResponseModel:
    """Return the impossible ``success=True`` + ``ipynb=None`` state."""
    return NoteburstJobResponseModel.model_validate(
        {
            "job_id": "xyz",
            "kernel_name": "",
            "enqueue_time": "2022-03-15T04:12:00Z",
            "status": "complete",
            "self_url": JOB_URL,
            "start_time": "2022-03-15T04:13:00Z",
            "finish_time": "2022-03-15T04:13:10Z",
            "success": True,
            "ipynb": None,
        }
    )


@pytest_asyncio.fixture
async def page_service() -> AsyncGenerator[BackgroundPageService]:
    """Return a BackgroundPageService."""
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


@pytest.mark.asyncio
async def test_page_service_migrate_html_cache_keys(
    page_service: BackgroundPageService, respx_mock: respx.Router
) -> None:
    """Test the migration of HTML cache keys from the 0.17 format to the
    0.18 format.
    """
    # Add a page to the database
    ipynb_path = Path(__file__).parent.parent / "data" / "demo.ipynb"
    ipynb = ipynb_path.read_text()
    page = PageModel.create_from_api_upload(
        ipynb=ipynb,
        title="Demo",
        uploader_username="testuser",
    )
    await page_service.add_page_to_store(page)

    # Add a mock html page to the nbhtmlstore using the old key format
    values = {
        "A": "2",
        "y0": "1.0",
        "lambd": "0.5",
        "title": "Demo",
        "boolflag": "true",
        "mydate": "2021-01-01",
        "mydatetime": "2021-01-01T12:00:00+00:00",
    }
    display_settings_values = {"ts_hide_code": 1}
    encoded_values_key = b64encode(
        json.dumps(dict(values.items()), sort_keys=True).encode("utf-8")
    ).decode("utf-8")
    display_settings_key = b64encode(
        json.dumps(display_settings_values).encode("utf-8")
    ).decode("utf-8")
    old_key = f"nbhtml/{page.name}/{encoded_values_key}/{display_settings_key}"
    await page_service._html_store._redis.set(old_key, "some html", ex=3600)

    # Run the migration
    await page_service.migrate_html_cache_keys(
        dry_run=False, for_page_id=page.name
    )

    # Create the new key
    display_settings = NbDisplaySettings(
        hide_code=display_settings_values["ts_hide_code"] == 1
    )
    page_instance_id = PageInstanceIdModel(
        name=page.name, parameter_values=values
    )
    nb_html_key = NbHtmlKey(
        page_instance_id=page_instance_id, display_settings=display_settings
    )
    new_key = f"nbhtml/{nb_html_key.cache_key}"
    print(new_key)

    # Check that the old key was deleted and the new key was created
    assert not await page_service._html_store._redis.exists(old_key)
    assert await page_service._html_store._redis.exists(new_key)
    assert await page_service._html_store._redis.get(new_key) == b"some html"


@pytest.mark.asyncio
async def test_update_nbhtml_execution_failure_logs_and_skips(
    page_service: BackgroundPageService,
) -> None:
    """A terminal Noteburst execution failure is logged and skipped: no
    raise, no HTML rendered, the failure is cached, and the stale job record
    is cleaned up.
    """
    ipynb_path = Path(__file__).parent.parent / "data" / "demo.ipynb"
    page = PageModel.create_from_api_upload(
        ipynb=ipynb_path.read_text(),
        title="Demo",
        uploader_username="testuser",
    )
    await page_service.add_page_to_store(page)

    page_instance = PageInstanceModel(page=page, values={})
    # Simulate a stale Noteburst job record that should be cleaned up.
    await page_service._job_store.store_job(
        job=NoteburstJobModel(
            date_submitted=datetime(2022, 3, 15, 4, 12, tzinfo=UTC),
            job_url=JOB_URL,  # type: ignore[arg-type]
        ),
        page_id=page_instance.id,
    )
    assert await page_service._job_store.get_instance(page_instance.id)

    # Must not raise.
    await page_service.update_nbhtml(
        page_name=page.name,
        parameter_values={},
        noteburst_response=_failed_noteburst_response(),
    )

    # No HTML was rendered.
    for display_settings in NbDisplaySettings.create_settings_matrix():
        html_key = NbHtmlKey(
            display_settings=display_settings,
            page_instance_id=page_instance.id,
        )
        assert await page_service._html_store.get_instance(html_key) is None

    # The failure was cached.
    failure = await page_service._execution_failure_store.get_instance(
        page_instance.id
    )
    assert failure is not None
    assert failure.code == "timeout"

    # The stale job record was cleaned up.
    assert await page_service._job_store.get_instance(page_instance.id) is None


@pytest.mark.asyncio
async def test_update_nbhtml_contract_violation_raises(
    page_service: BackgroundPageService,
) -> None:
    """The impossible success=true + ipynb=None state still raises."""
    ipynb_path = Path(__file__).parent.parent / "data" / "demo.ipynb"
    page = PageModel.create_from_api_upload(
        ipynb=ipynb_path.read_text(),
        title="Demo",
        uploader_username="testuser",
    )
    await page_service.add_page_to_store(page)

    with pytest.raises(RuntimeError):
        await page_service.update_nbhtml(
            page_name=page.name,
            parameter_values={},
            noteburst_response=_contract_violation_noteburst_response(),
        )
