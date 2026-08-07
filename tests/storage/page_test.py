"""Tests for the PageStore's handling of GitHub identity columns."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime

import pytest
import pytest_asyncio
import structlog
from safir.database import (
    create_async_session,
    create_database_engine,
    initialize_database,
    stamp_database_async,
)
from sqlalchemy.ext.asyncio import AsyncSession

from timessquare.config import config
from timessquare.dbschema import Base
from timessquare.domain.page import PageModel
from timessquare.domain.pageparameters import PageParameters
from timessquare.storage.page import PageStore


@pytest_asyncio.fixture
async def session() -> AsyncIterator[AsyncSession]:
    """Return a database session against a freshly initialized schema."""
    logger = structlog.get_logger(config.logger_name)
    engine = create_database_engine(
        config.database_url, config.database_password.get_secret_value()
    )
    await initialize_database(engine, logger, schema=Base.metadata, reset=True)
    await stamp_database_async(engine)
    db_session = await create_async_session(engine)
    try:
        yield db_session
    finally:
        await db_session.aclose()
        await engine.dispose()


def _page(
    name: str,
    *,
    owner: str = "lsst-sqre",
    repo: str = "times-square-demo",
    repository_id: int | None = None,
    owner_id: int | None = None,
    installation_id: int | None = None,
) -> PageModel:
    return PageModel(
        name=name,
        ipynb="{}",
        parameters=PageParameters({}),
        title="Demo",
        date_added=datetime.now(UTC),
        github_owner=owner,
        github_repo=repo,
        github_repository_id=repository_id,
        github_owner_id=owner_id,
        github_installation_id=installation_id,
        repository_path_prefix="",
        repository_display_path_prefix="",
        repository_path_stem=name,
        repository_source_extension=".ipynb",
        repository_sidecar_extension=".yaml",
        repository_source_sha="1" * 40,
        repository_sidecar_sha="1" * 40,
    )


@pytest.mark.asyncio
async def test_add_round_trips_github_ids(session: AsyncSession) -> None:
    """A page added with numeric GitHub IDs reads them back."""
    store = PageStore(session=session)
    store.add(_page("ids", repository_id=42, owner_id=7, installation_id=1234))
    await session.commit()

    page = await store.get("ids")

    assert page is not None
    assert page.github_repository_id == 42
    assert page.github_owner_id == 7
    assert page.github_installation_id == 1234


@pytest.mark.asyncio
async def test_update_page_writes_ids_and_names(
    session: AsyncSession,
) -> None:
    """Updating a page persists the numeric GitHub IDs and refreshed
    owner/repo strings, which is how a missed rename self-heals.
    """
    store = PageStore(session=session)
    store.add(_page("heal", owner="lsst-sitcom", repo="old-name"))
    await session.commit()

    page = await store.get("heal")
    assert page is not None
    page.github_owner = "lsst-so"
    page.github_repo = "new-name"
    page.github_repository_id = 42
    page.github_owner_id = 7
    page.github_installation_id = 1234
    await store.update_page(page)
    await session.commit()

    updated = await store.get("heal")
    assert updated is not None
    assert updated.github_owner == "lsst-so"
    assert updated.github_repo == "new-name"
    assert updated.github_repository_id == 42
    assert updated.github_owner_id == 7
    assert updated.github_installation_id == 1234


@pytest.mark.asyncio
async def test_list_pages_for_repository_by_id(
    session: AsyncSession,
) -> None:
    """The repository listing matches on the stable repository ID even when
    the stored owner/repo strings are stale, and still falls back to the
    names for rows that have no ID yet.
    """
    store = PageStore(session=session)
    store.add(
        _page("stale", owner="lsst-sitcom", repo="old-name", repository_id=42)
    )
    store.add(_page("unbackfilled"))
    store.add(_page("other-repo", repo="other", repository_id=99))
    await session.commit()

    pages = await store.list_pages_for_repository(
        owner="lsst-sqre", name="times-square-demo", repository_id=42
    )

    assert sorted(page.name for page in pages) == ["stale", "unbackfilled"]


@pytest.mark.asyncio
async def test_list_pages_for_repository_name_fallback_is_id_gated(
    session: AsyncSession,
) -> None:
    """The name fallback only reaches un-backfilled rows: a row carrying a
    different repository ID under the same owner/repo names belongs to a
    different repository and is left alone.
    """
    store = PageStore(session=session)
    store.add(_page("unbackfilled"))
    store.add(_page("impostor", repository_id=99))
    await session.commit()

    pages = await store.list_pages_for_repository(
        owner="lsst-sqre", name="times-square-demo", repository_id=42
    )

    assert [page.name for page in pages] == ["unbackfilled"]


@pytest.mark.asyncio
async def test_list_conflicting_repository_ids(session: AsyncSession) -> None:
    """Pages holding an owner/repo name pair on behalf of a different
    repository ID are reported; the repository's own pages and
    un-backfilled pages are not.
    """
    store = PageStore(session=session)
    store.add(_page("own", repository_id=42))
    store.add(_page("unbackfilled"))
    store.add(_page("impostor", repository_id=99))
    store.add(_page("elsewhere", repo="other-name", repository_id=101))
    await session.commit()

    conflicts = await store.list_conflicting_repository_ids(
        owner="lsst-sqre", name="times-square-demo", repository_id=42
    )

    assert conflicts == [99]


@pytest.mark.asyncio
async def test_list_conflicting_repository_ids_ignores_deleted(
    session: AsyncSession,
) -> None:
    """Soft-deleted pages do not conflict, so a repository name freed up by
    an uninstall can be reused by a new repository.
    """
    store = PageStore(session=session)
    deleted = _page("retired", repository_id=99)
    deleted.date_deleted = datetime.now(UTC)
    store.add(deleted)
    await session.commit()

    conflicts = await store.list_conflicting_repository_ids(
        owner="lsst-sqre", name="times-square-demo", repository_id=42
    )

    assert conflicts == []
