"""Tests for the org_renamed worker task."""

from __future__ import annotations

import json
from collections.abc import AsyncGenerator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock

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
from structlog.testing import capture_logs

from timessquare.config import config
from timessquare.dbschema import Base
from timessquare.domain.page import PageModel
from timessquare.domain.pageparameters import PageParameters
from timessquare.factory import ProcessContext, WorkerFactory
from timessquare.storage.github.apimodels import (
    GitHubOrganizationRenamedEventModel,
)
from timessquare.worker.functions.org_renamed import org_renamed

DATA = Path(__file__).parent / ".." / ".." / "data"

OLD_LOGIN = "lsst-sqre"
"""The fixture's old login, which is in the default ``TS_GITHUB_ORGS``."""

NEW_LOGIN = "lsst-so"
OWNER_ID = 30830384


@pytest_asyncio.fixture
async def worker_ctx() -> AsyncGenerator[dict[str, Any]]:
    """Return an arq worker ``ctx`` over a fresh database."""
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


def _payload() -> GitHubOrganizationRenamedEventModel:
    """Build the organization rename payload from the recorded GitHub
    fixture.
    """
    payload = json.loads(
        (DATA / "github_webhooks" / "organization_renamed.json").read_text()
    )
    return GitHubOrganizationRenamedEventModel.model_validate(payload)


def _page(
    name: str,
    *,
    owner: str = OLD_LOGIN,
    owner_id: int | None = None,
) -> PageModel:
    return PageModel(
        name=name,
        ipynb="{}",
        parameters=PageParameters({}),
        title="Demo",
        date_added=datetime.now(UTC),
        github_owner=owner,
        github_repo="times-square-demo",
        github_owner_id=owner_id,
        repository_path_prefix="",
        repository_display_path_prefix="",
        repository_path_stem=name,
        repository_source_extension=".ipynb",
        repository_sidecar_extension=".yaml",
        repository_source_sha="1" * 40,
        repository_sidecar_sha="1" * 40,
    )


async def _add_pages(
    process_context: ProcessContext, pages: list[PageModel]
) -> None:
    """Add pages directly through the page store."""
    logger = structlog.get_logger(config.logger_name)
    async for db_session in db_session_dependency():
        factory = WorkerFactory(
            logger=logger,
            session=db_session,
            process_context=process_context,
        )
        page_service = factory.create_page_service()
        for page in pages:
            await page_service.add_page_to_store(page)
        await db_session.commit()


async def _stored_page(
    process_context: ProcessContext, page_name: str
) -> PageModel:
    """Read a page back from the database."""
    logger = structlog.get_logger(config.logger_name)
    async for db_session in db_session_dependency():
        factory = WorkerFactory(
            logger=logger,
            session=db_session,
            process_context=process_context,
        )
        return await factory.create_page_service().get_page(page_name)
    raise AssertionError("No database session")


@pytest.mark.asyncio
async def test_org_renamed_flips_owner_by_id(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """A rename keyed on the stable owner ID flips the owner login on the
    organization's pages, whatever login they are stored under.

    ``respx_mock`` with no routes registered means any outbound HTTP call —
    a Noteburst execution or a GitHub content fetch — fails the test.
    """
    process_context = worker_ctx["process_context"]
    await _add_pages(
        process_context,
        [
            _page("stale", owner="ancient-org", owner_id=OWNER_ID),
            _page("current", owner_id=OWNER_ID),
            _page("elsewhere", owner="other-org", owner_id=99),
        ],
    )

    await org_renamed(worker_ctx, payload=_payload())

    for name in ("stale", "current"):
        page = await _stored_page(process_context, name)
        assert page.github_owner == NEW_LOGIN

    other = await _stored_page(process_context, "elsewhere")
    assert other.github_owner == "other-org"

    assert respx_mock.calls.call_count == 0
    worker_ctx["slack"].post.assert_not_called()


@pytest.mark.asyncio
async def test_org_renamed_null_id_fallback(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """Pages that predate owner-ID capture are flipped through the old login,
    and the fallback is ID-gated so another owner's pages are left alone.
    """
    process_context = worker_ctx["process_context"]
    await _add_pages(
        process_context,
        [
            _page("unbackfilled"),
            _page("impostor", owner_id=99),
        ],
    )

    await org_renamed(worker_ctx, payload=_payload())

    page = await _stored_page(process_context, "unbackfilled")
    assert page.github_owner == NEW_LOGIN

    impostor = await _stored_page(process_context, "impostor")
    assert impostor.github_owner == OLD_LOGIN

    assert respx_mock.calls.call_count == 0


@pytest.mark.asyncio
async def test_org_renamed_warns_to_update_config(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """The task warns the operator that ``TS_GITHUB_ORGS`` still names the
    organization's old login, so its future events would be dropped.
    """
    await _add_pages(
        worker_ctx["process_context"], [_page("page", owner_id=OWNER_ID)]
    )

    with capture_logs() as logs:
        await org_renamed(worker_ctx, payload=_payload())

    warnings = [entry for entry in logs if entry.get("log_level") == "warning"]
    assert len(warnings) == 1
    assert "TS_GITHUB_ORGS" in warnings[0]["event"]
    assert warnings[0]["accepted_orgs"] == config.accepted_github_orgs


@pytest.mark.asyncio
async def test_org_renamed_logs_affected_count(
    worker_ctx: dict[str, Any], respx_mock: respx.Router
) -> None:
    """The task logs how many pages the rename affected."""
    await _add_pages(
        worker_ctx["process_context"],
        [
            _page("first", owner_id=OWNER_ID),
            _page("second", owner_id=OWNER_ID),
        ],
    )

    with capture_logs() as logs:
        await org_renamed(worker_ctx, payload=_payload())

    assert any(entry.get("page_count") == 2 for entry in logs), json.dumps(
        [entry.get("event") for entry in logs]
    )
