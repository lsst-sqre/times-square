"""Factories for services in the worker context."""

from __future__ import annotations

import httpx
from safir.arq import ArqMode, ArqQueue, MockArqQueue, RedisArqQueue
from safir.github import GitHubAppClientFactory
from safir.slack.blockkit import SlackException
from sqlalchemy.ext.asyncio import async_scoped_session
from structlog.stdlib import BoundLogger

from timessquare.config import config
from timessquare.dependencies.redis import redis_dependency
from timessquare.services.backgroundpage import BackgroundPageService
from timessquare.services.githubcheckrun import GitHubCheckRunService
from timessquare.services.githubrepo import GitHubRepoService
from timessquare.storage.nbhtmlcache import NbHtmlCacheStore
from timessquare.storage.noteburstjobstore import NoteburstJobStore
from timessquare.storage.page import PageStore


async def create_github_check_run_service(
    *,
    http_client: httpx.AsyncClient,
    db_session: async_scoped_session,
    logger: BoundLogger,
    installation_id: int,
) -> GitHubCheckRunService:
    """Create a GitHubRepoService for arq tasks."""
    if not config.github_app_id or not config.github_app_private_key:
        raise SlackException(
            "github_app_id and github_app_private_key must be set to "
            "create the GitHubRepoService."
        )
    github_client_factory = GitHubAppClientFactory(
        http_client=http_client,
        id=config.github_app_id,
        key=config.github_app_private_key,
        name="lsst-sqre/times-square",
    )
    github_client = await github_client_factory.create_installation_client(
        installation_id=installation_id
    )

    page_service = await create_page_service(
        http_client=http_client, logger=logger, db_session=db_session
    )
    repo_service = await create_github_repo_service(
        http_client=http_client,
        db_session=db_session,
        logger=logger,
        installation_id=installation_id,
    )
    return GitHubCheckRunService(
        http_client=http_client,
        github_client=github_client,
        repo_service=repo_service,
        page_service=page_service,
        logger=logger,
    )


async def create_github_repo_service(
    *,
    http_client: httpx.AsyncClient,
    db_session: async_scoped_session,
    logger: BoundLogger,
    installation_id: int,
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
        key=config.github_app_private_key,
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
) -> BackgroundPageService:
    """Create a PageService for arq tasks."""
    redis = await redis_dependency()
    arq_queue = await create_arq_queue()

    return BackgroundPageService(
        page_store=PageStore(db_session),
        html_cache=NbHtmlCacheStore(redis),
        job_store=NoteburstJobStore(redis),
        http_client=http_client,
        logger=logger,
        arq_queue=arq_queue,
    )


async def create_arq_queue() -> ArqQueue:
    """Create an ArqQueue for arq tasks."""
    mode = config.arq_mode
    if mode == ArqMode.production:
        if not config.arq_redis_settings:
            raise RuntimeError(
                "The redis_settings argument must be set for arq in "
                "production."
            )
        return await RedisArqQueue.initialize(config.arq_redis_settings)
    else:
        return MockArqQueue()
