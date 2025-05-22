"""Tests for the BackgroundPageService."""

from __future__ import annotations

import json
from base64 import b64encode
from collections.abc import AsyncGenerator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
import respx
import structlog
from safir.arq import MockArqQueue
from safir.database import (
    create_database_engine,
    initialize_database,
    stamp_database_async,
)
from safir.dependencies.db_session import db_session_dependency

from timessquare.config import config
from timessquare.dbschema import Base
from timessquare.dependencies.redis import redis_dependency
from timessquare.domain.nbhtml import NbDisplaySettings, NbHtmlKey
from timessquare.domain.page import PageInstanceIdModel, PageModel
from timessquare.services.backgroundpage import BackgroundPageService
from timessquare.storage.nbhtmlcache import NbHtmlCacheStore
from timessquare.storage.noteburstjobstore import NoteburstJobStore
from timessquare.storage.page import PageStore


@pytest_asyncio.fixture
async def page_service() -> AsyncGenerator[BackgroundPageService]:
    """Return a BackgroundPageService."""
    logger = structlog.get_logger(config.logger_name)

    http_client = httpx.AsyncClient()
    engine = create_database_engine(
        config.database_url, config.database_password.get_secret_value()
    )
    await initialize_database(engine, logger, schema=Base.metadata, reset=True)
    await stamp_database_async(engine)
    await engine.dispose()

    await db_session_dependency.initialize(
        str(config.database_url), config.database_password.get_secret_value()
    )
    await redis_dependency.initialize(str(config.redis_url))

    async for db_session in db_session_dependency():
        redis = await redis_dependency()
        yield BackgroundPageService(
            page_store=PageStore(db_session),
            html_cache=NbHtmlCacheStore(redis),
            job_store=NoteburstJobStore(redis),
            http_client=http_client,
            logger=logger,
            arq_queue=MockArqQueue(),
        )


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
