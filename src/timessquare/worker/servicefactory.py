from __future__ import annotations

import httpx
from safir.github import GitHubAppClientFactory
from safir.slack.blockkit import SlackException
from sqlalchemy.ext.asyncio import async_scoped_session
from structlog.stdlib import BoundLogger

from timessquare.config import config
from timessquare.dependencies.redis import redis_dependency
from timessquare.services.githubrepo import GitHubRepoService
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
    if not config.github_app_id or not config.github_app_private_key:
        raise SlackException(
            "github_app_id and github_app_private_key must be set to "
            "create the GitHubRepoService."
        )
    github_client_factory = GitHubAppClientFactory(
        http_client=http_client,
        id=config.github_app_id,
        key=config.github_app_private_key.get_secret_value(),
        name="lsst-sqre/times-square",
    )
    github_client = await github_client_factory.create_installation_client(
        installation_id=installation_id
    )

    page_service = await create_page_service(
        http_client=http_client, logger=logger, db_session=db_session
    )
    return GitHubRepoService(
        http_client=http_client,
        github_client=github_client,
        page_service=page_service,
        logger=logger,
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
