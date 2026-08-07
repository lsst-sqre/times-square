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


@pytest.mark.asyncio
async def test_rename_repository_by_id(session: AsyncSession) -> None:
    """A rename keyed on the stable repository ID flips every one of the
    repository's pages, whatever name they are currently stored under.
    """
    store = PageStore(session=session)
    store.add(_page("stale", repo="ancient-name", repository_id=42))
    store.add(_page("current", repo="old-name", repository_id=42))
    await session.commit()

    renamed = await store.rename_repository(
        owner="lsst-sqre",
        old_name="old-name",
        new_name="new-name",
        repository_id=42,
    )
    await session.commit()

    assert sorted(renamed) == ["current", "stale"]
    for name in ("stale", "current"):
        page = await store.get(name)
        assert page is not None
        assert page.github_repo == "new-name"


@pytest.mark.asyncio
async def test_rename_repository_null_id_fallback(
    session: AsyncSession,
) -> None:
    """Pages that predate ID capture are renamed through the old name, and
    the fallback is ID-gated so another repository's pages are left alone.
    """
    store = PageStore(session=session)
    store.add(_page("unbackfilled", repo="old-name"))
    store.add(_page("impostor", repo="old-name", repository_id=99))
    await session.commit()

    renamed = await store.rename_repository(
        owner="lsst-sqre",
        old_name="old-name",
        new_name="new-name",
        repository_id=42,
    )
    await session.commit()

    assert renamed == ["unbackfilled"]
    impostor = await store.get("impostor")
    assert impostor is not None
    assert impostor.github_repo == "old-name"


@pytest.mark.asyncio
async def test_transfer_repository_by_id(session: AsyncSession) -> None:
    """A transfer keyed on the stable repository ID rewrites the owner, the
    owner ID, and the repository name on every one of the repository's pages.
    """
    store = PageStore(session=session)
    store.add(
        _page("first", owner="lsst-sitcom", repository_id=42, owner_id=7)
    )
    store.add(
        _page(
            "second",
            owner="lsst-sitcom",
            repo="ancient-name",
            repository_id=42,
        )
    )
    store.add(_page("elsewhere", owner="lsst-sitcom", repository_id=99))
    await session.commit()

    transferred = await store.transfer_repository(
        repository_id=42,
        new_owner="lsst-so",
        new_owner_id=8,
        new_name="new-name",
    )
    await session.commit()

    assert sorted(transferred) == ["first", "second"]
    for name in ("first", "second"):
        page = await store.get(name)
        assert page is not None
        assert page.github_owner == "lsst-so"
        assert page.github_owner_id == 8
        assert page.github_repo == "new-name"
    untouched = await store.get("elsewhere")
    assert untouched is not None
    assert untouched.github_owner == "lsst-sitcom"


@pytest.mark.asyncio
async def test_transfer_repository_has_no_name_fallback(
    session: AsyncSession,
) -> None:
    """A transfer never matches pages by name. A transfer frees the old
    ``owner/repo`` name pair on GitHub immediately, so a name-keyed match
    could sweep up a different repository's pages.
    """
    store = PageStore(session=session)
    store.add(_page("unbackfilled", owner="lsst-sitcom", repo="old-name"))
    await session.commit()

    transferred = await store.transfer_repository(
        repository_id=42,
        new_owner="lsst-so",
        new_owner_id=8,
        new_name="old-name",
    )
    await session.commit()

    assert transferred == []
    page = await store.get("unbackfilled")
    assert page is not None
    assert page.github_owner == "lsst-sitcom"


@pytest.mark.asyncio
async def test_transfer_repository_is_idempotent(
    session: AsyncSession,
) -> None:
    """A redelivered transfer webhook reports no affected pages, because
    pages already stored under the new identity are not matched.
    """
    store = PageStore(session=session)
    store.add(
        _page(
            "healed",
            owner="lsst-so",
            repo="new-name",
            repository_id=42,
            owner_id=8,
        )
    )
    await session.commit()

    transferred = await store.transfer_repository(
        repository_id=42,
        new_owner="lsst-so",
        new_owner_id=8,
        new_name="new-name",
    )
    await session.commit()

    assert transferred == []


@pytest.mark.asyncio
async def test_transfer_repository_fills_null_owner_id(
    session: AsyncSession,
) -> None:
    """A page whose owner strings already match but that predates owner-ID
    capture is still updated, so the ID is recorded rather than skipped.
    """
    store = PageStore(session=session)
    store.add(_page("no-owner-id", owner="lsst-so", repository_id=42))
    await session.commit()

    transferred = await store.transfer_repository(
        repository_id=42,
        new_owner="lsst-so",
        new_owner_id=8,
        new_name="times-square-demo",
    )
    await session.commit()

    assert transferred == ["no-owner-id"]
    page = await store.get("no-owner-id")
    assert page is not None
    assert page.github_owner_id == 8


@pytest.mark.asyncio
async def test_list_pages_for_repository_id(session: AsyncSession) -> None:
    """Listing by repository ID alone matches the repository's live pages
    whatever names they are stored under, and never matches by name.
    """
    store = PageStore(session=session)
    store.add(_page("stale", owner="lsst-sitcom", repository_id=42))
    store.add(_page("unbackfilled"))
    store.add(_page("elsewhere", repository_id=99))
    deleted = _page("retired", repository_id=42)
    deleted.date_deleted = datetime.now(UTC)
    store.add(deleted)
    await session.commit()

    pages = await store.list_pages_for_repository_id(repository_id=42)

    assert [page.name for page in pages] == ["stale"]


@pytest.mark.asyncio
async def test_rename_repository_is_idempotent(session: AsyncSession) -> None:
    """A redelivered rename webhook reports no affected pages, because pages
    already stored under the new name are not matched.
    """
    store = PageStore(session=session)
    store.add(_page("healed", repo="new-name", repository_id=42))
    await session.commit()

    renamed = await store.rename_repository(
        owner="lsst-sqre",
        old_name="old-name",
        new_name="new-name",
        repository_id=42,
    )
    await session.commit()

    assert renamed == []


@pytest.mark.asyncio
async def test_rename_owner_by_id(session: AsyncSession) -> None:
    """An owner rename keyed on the stable owner ID flips every one of the
    owner's pages, whatever login they are currently stored under.
    """
    store = PageStore(session=session)
    store.add(_page("stale", owner="ancient-org", owner_id=7))
    store.add(_page("current", owner="lsst-sitcom", owner_id=7))
    store.add(_page("elsewhere", owner="other-org", owner_id=99))
    await session.commit()

    renamed = await store.rename_owner(
        old_login="lsst-sitcom", new_login="lsst-so", owner_id=7
    )
    await session.commit()

    assert sorted(renamed) == ["current", "stale"]
    for name in ("stale", "current"):
        page = await store.get(name)
        assert page is not None
        assert page.github_owner == "lsst-so"
    untouched = await store.get("elsewhere")
    assert untouched is not None
    assert untouched.github_owner == "other-org"


@pytest.mark.asyncio
async def test_rename_owner_null_id_fallback(session: AsyncSession) -> None:
    """Pages that predate owner-ID capture are renamed through the old login,
    and the fallback is ID-gated so another owner's pages are left alone.
    """
    store = PageStore(session=session)
    store.add(_page("unbackfilled", owner="lsst-sitcom"))
    store.add(_page("impostor", owner="lsst-sitcom", owner_id=99))
    await session.commit()

    renamed = await store.rename_owner(
        old_login="lsst-sitcom", new_login="lsst-so", owner_id=7
    )
    await session.commit()

    assert renamed == ["unbackfilled"]
    impostor = await store.get("impostor")
    assert impostor is not None
    assert impostor.github_owner == "lsst-sitcom"


@pytest.mark.asyncio
async def test_rename_owner_is_idempotent(session: AsyncSession) -> None:
    """A redelivered organization rename webhook reports no affected pages,
    because pages already stored under the new login are not matched.
    """
    store = PageStore(session=session)
    store.add(_page("healed", owner="lsst-so", owner_id=7))
    await session.commit()

    renamed = await store.rename_owner(
        old_login="lsst-sitcom", new_login="lsst-so", owner_id=7
    )
    await session.commit()

    assert renamed == []


@pytest.mark.asyncio
async def test_count_pages_missing_github_ids(session: AsyncSession) -> None:
    """The backfill tally groups pages by their stored owner/repository names,
    counting only pages that have no repository ID recorded yet.
    """
    store = PageStore(session=session)
    store.add(_page("a", owner="lsst-sqre", repo="demo"))
    store.add(_page("b", owner="lsst-sqre", repo="demo"))
    store.add(_page("c", owner="lsst-sitcom", repo="notebooks"))
    store.add(
        _page("filled", owner="lsst-sqre", repo="other", repository_id=1)
    )
    await session.commit()

    tally = await store.count_pages_missing_github_ids()

    assert tally == {
        ("lsst-sitcom", "notebooks"): 1,
        ("lsst-sqre", "demo"): 2,
    }


@pytest.mark.asyncio
async def test_count_pages_missing_github_ids_skips_uploads(
    session: AsyncSession,
) -> None:
    """Pages uploaded through the API are not GitHub-backed, so they are not
    backfill targets even though their ID columns are null.
    """
    store = PageStore(session=session)
    store.add(
        PageModel(
            name="upload",
            ipynb="{}",
            parameters=PageParameters({}),
            title="Upload",
            date_added=datetime.now(UTC),
            uploader_username="someuser",
        )
    )
    await session.commit()

    assert await store.count_pages_missing_github_ids() == {}


@pytest.mark.asyncio
async def test_backfill_github_ids(session: AsyncSession) -> None:
    """The backfill fills all three numeric IDs on the pages stored under an
    owner/repository name pair, leaving pages that already have an ID alone.
    """
    store = PageStore(session=session)
    store.add(_page("target", owner="lsst-sqre", repo="demo"))
    store.add(
        _page(
            "filled",
            owner="lsst-sqre",
            repo="demo",
            repository_id=1,
            owner_id=2,
            installation_id=3,
        )
    )
    await session.commit()

    backfilled = await store.backfill_github_ids(
        owner="lsst-sqre",
        name="demo",
        repository_id=42,
        owner_id=7,
        installation_id=1234,
    )
    await session.commit()

    assert backfilled == ["target"]
    target = await store.get("target")
    assert target is not None
    assert target.github_repository_id == 42
    assert target.github_owner_id == 7
    assert target.github_installation_id == 1234
    filled = await store.get("filled")
    assert filled is not None
    assert filled.github_repository_id == 1
    assert filled.github_owner_id == 2
    assert filled.github_installation_id == 3
