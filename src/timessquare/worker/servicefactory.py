from __future__ import annotations

import httpx
from sqlalchemy.ext.asyncio import async_scoped_session
from structlog.stdlib import BoundLogger

from timessquare.dependencies.redis import redis_dependency
from timessquare.services.github.client import (
    create_github_installation_client,
)
from timessquare.services.github.repo import GitHubRepoService
from timessquare.services.page import PageService
from timessquare.storage.nbhtmlcache import NbHtmlCacheStore
from timessquare.storage.noteburstjobstore import NoteburstJobStore
from timessquare.storage.page import PageStore


async def create_github_repo_service(
    *,
    http_client: httpx.AsyncClient,
    db_session: async_scoped_session,
    logger: BoundLogger,
    installation_id: str,
) -> GitHubRepoService:
    """Create a GitHubRepoService for arq tasks."""
    github_client = await create_github_installation_client(
        http_client=http_client,
        installation_id=installation_id,
    )

    page_service = await create_page_service(
        http_client=http_client, logger=logger, db_session=db_session
    )
    return GitHubRepoService(
        github_client=github_client, page_service=page_service, logger=logger
    )


async def create_page_service(
    *,
    http_client: httpx.AsyncClient,
    logger: BoundLogger,
    db_session: async_scoped_session,
) -> PageService:
    """Create a PageService for arq tasks."""
    redis = await redis_dependency()

    return PageService(
        page_store=PageStore(db_session),
        html_cache=NbHtmlCacheStore(redis),
        job_store=NoteburstJobStore(redis),
        http_client=http_client,
        logger=logger,
    )
