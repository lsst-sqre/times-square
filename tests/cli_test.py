"""Tests for the Times Square CLI."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
import structlog
from safir.database import (
    create_database_engine,
    initialize_database,
    stamp_database_async,
)
from safir.dependencies.db_session import db_session_dependency
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from timessquare.cli import _rename_github_owner_in_db
from timessquare.config import config
from timessquare.dbschema import Base
from timessquare.dbschema.page import SqlPage
from timessquare.domain.page import PageModel
from timessquare.domain.pageparameters import PageParameters
from timessquare.storage.page import PageStore


def _make_github_page(
    *, name: str, github_owner: str, github_repo: str
) -> PageModel:
    return PageModel(
        name=name,
        ipynb="{}",
        parameters=PageParameters({}),
        title=name,
        date_added=datetime.now(UTC),
        date_deleted=None,
        github_owner=github_owner,
        github_repo=github_repo,
        repository_path_prefix="",
        repository_display_path_prefix="",
        repository_path_stem=name,
        repository_sidecar_extension=".yaml",
        repository_source_extension=".ipynb",
        repository_source_sha="1" * 40,
        repository_sidecar_sha="1" * 40,
    )


async def _owner_by_name(session: AsyncSession, name: str) -> str | None:
    statement = select(SqlPage.github_owner).where(SqlPage.name == name)
    return await session.scalar(statement)


@pytest.mark.asyncio
async def test_rename_github_owner() -> None:
    """Renaming rewrites matching rows only; a rollback reverts changes."""
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
    try:
        async for session in db_session_dependency():
            store = PageStore(session)
            store.add(
                _make_github_page(
                    name="page-a",
                    github_owner="lsst-sitcom",
                    github_repo="foo",
                )
            )
            store.add(
                _make_github_page(
                    name="page-b", github_owner="other", github_repo="bar"
                )
            )
            await session.commit()

            # Dry-run path: update then rollback leaves rows untouched.
            dry_count = await _rename_github_owner_in_db(
                session, old_owner="lsst-sitcom", new_owner="lsst-so"
            )
            await session.rollback()
            assert dry_count == 1
            assert await _owner_by_name(session, "page-a") == "lsst-sitcom"

            # Real run: update then commit rewrites only the matching row.
            count = await _rename_github_owner_in_db(
                session, old_owner="lsst-sitcom", new_owner="lsst-so"
            )
            await session.commit()
            assert count == 1
            assert await _owner_by_name(session, "page-a") == "lsst-so"
            assert await _owner_by_name(session, "page-b") == "other"
    finally:
        await db_session_dependency.aclose()
