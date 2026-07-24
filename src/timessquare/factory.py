"""Component factory and process-wide shared resources for Times Square."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import aclosing, asynccontextmanager
from dataclasses import dataclass
from typing import Self

from gidgethub.httpx import GitHubAPI
from httpx import AsyncClient
from redis.asyncio import BlockingConnectionPool, Redis
from redis.asyncio.retry import Retry
from redis.backoff import ExponentialBackoff
from safir.arq import ArqMode, ArqQueue, MockArqQueue, RedisArqQueue
from safir.database import create_async_session
from safir.github import GitHubAppClientFactory
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession
from structlog.stdlib import BoundLogger

from .config import config
from .services.backgroundpage import BackgroundPageService
from .services.githubcheckrun import GitHubCheckRunService
from .services.githubrepo import GitHubRepoService
from .services.page import PageService
from .services.runscheduler import RunSchedulerService
from .storage.nbhtmlcache import NbHtmlCacheStore
from .storage.noteburst import NoteburstApi
from .storage.noteburstjobstore import NoteburstJobStore
from .storage.page import PageStore
from .storage.scheduledrunstore import ScheduledRunStore

__all__ = ["Factory", "ProcessContext", "WorkerFactory"]


@dataclass(kw_only=True, frozen=True, slots=True)
class ProcessContext:
    """Holds singletons in the context of a Times Square process, which
    might be a FastAPI app, an arq worker, or a CLI command.
    """

    http_client: AsyncClient
    """Shared HTTP client."""

    redis: Redis
    """Redis client for the HTML cache and Noteburst job store."""

    arq_queue: ArqQueue
    """Client to the arq task queue."""

    @classmethod
    async def create(cls) -> Self:
        """Create a ProcessContext from the application configuration."""
        http_client = AsyncClient(timeout=config.http_client_timeout)

        redis_pool = BlockingConnectionPool.from_url(
            str(config.redis_url),
            max_connections=25,
            retry=Retry(
                ExponentialBackoff(base=0.2, cap=1.0),
                10,
            ),
            retry_on_timeout=True,
            socket_keepalive=True,
            socket_timeout=5,
            timeout=30,
        )
        redis = Redis.from_pool(redis_pool)

        arq_queue: ArqQueue
        if config.arq_mode == ArqMode.production:
            arq_queue = await RedisArqQueue.initialize(
                config.arq_redis_settings
            )
        else:
            arq_queue = MockArqQueue()

        return cls(
            http_client=http_client,
            redis=redis,
            arq_queue=arq_queue,
        )

    async def aclose(self) -> None:
        """Clean up a process context.

        Called during shutdown, or before recreating the process context
        using a different configuration.
        """
        await self.redis.aclose()
        await self.http_client.aclose()


class Factory:
    """A factory for creating Times Square services and storage interfaces.

    Parameters
    ----------
    logger
        A logger, bound with request or task context.
    session
        A database session.
    process_context
        The shared process resources.
    """

    def __init__(
        self,
        *,
        logger: BoundLogger,
        session: AsyncSession,
        process_context: ProcessContext,
    ) -> None:
        self._process_context = process_context
        self._session = session
        self._logger = logger

    @classmethod
    async def create(
        cls,
        *,
        logger: BoundLogger,
        engine: AsyncEngine,
    ) -> Self:
        """Create a Factory (for use outside a request or task context)."""
        context = await ProcessContext.create()
        session = await create_async_session(engine)
        return cls(
            logger=logger,
            session=session,
            process_context=context,
        )

    @classmethod
    @asynccontextmanager
    async def create_standalone(
        cls,
        *,
        logger: BoundLogger,
        engine: AsyncEngine,
    ) -> AsyncIterator[Self]:
        """Create a standalone factory, outside the FastAPI or worker
        processes, as a context manager.

        Use this for creating a factory in CLI commands.
        """
        factory = await cls.create(logger=logger, engine=engine)
        async with aclosing(factory):
            yield factory

    async def aclose(self) -> None:
        """Shut down the factory and the internal process context."""
        try:
            await self._process_context.aclose()
        finally:
            await self._session.close()

    def set_logger(self, logger: BoundLogger) -> None:
        """Set the logger for the factory."""
        self._logger = logger

    @property
    def http_client(self) -> AsyncClient:
        """The shared HTTP client."""
        return self._process_context.http_client

    @property
    def db_session(self) -> AsyncSession:
        """The database session."""
        return self._session

    @property
    def redis(self) -> Redis:
        """The shared Redis client."""
        return self._process_context.redis

    @property
    def arq_queue(self) -> ArqQueue:
        """The client to the arq task queue."""
        return self._process_context.arq_queue

    def create_github_client_factory(self) -> GitHubAppClientFactory:
        """Create a GitHub client factory.

        From the client factory, you can create clients for installations
        in specific repositories.
        """
        if not config.github_app_id or not config.github_app_private_key:
            raise RuntimeError(
                "GitHub App is not configured; set TS_GITHUB_APP_ID and "
                "TS_GITHUB_APP_PRIVATE_KEY."
            )
        return GitHubAppClientFactory(
            id=config.github_app_id,
            key=config.github_app_private_key,
            name="lsst-sqre/times-square",
            http_client=self.http_client,
        )

    async def create_github_installation_client(
        self, *, installation_id: int
    ) -> GitHubAPI:
        """Create a GitHub client authenticated as an app installation."""
        client_factory = self.create_github_client_factory()
        return await client_factory.create_installation_client(
            installation_id=installation_id
        )

    def create_page_store(self) -> PageStore:
        """Create a PageStore (Postgres storage of pages)."""
        return PageStore(self._session)

    def create_nbhtml_cache_store(self) -> NbHtmlCacheStore:
        """Create an NbHtmlCacheStore (Redis cache of rendered HTML)."""
        return NbHtmlCacheStore(self.redis)

    def create_noteburst_job_store(self) -> NoteburstJobStore:
        """Create a NoteburstJobStore (Redis storage of pending noteburst
        jobs).
        """
        return NoteburstJobStore(self.redis)

    def create_scheduled_run_store(self) -> ScheduledRunStore:
        """Create a ScheduledRunStore (Postgres storage of scheduled runs)."""
        return ScheduledRunStore(self._session)

    def create_noteburst_api(self) -> NoteburstApi:
        """Create a client for the Noteburst API."""
        return NoteburstApi(http_client=self.http_client)

    def create_page_service(self) -> PageService:
        """Create a PageService."""
        return PageService(
            page_store=self.create_page_store(),
            html_cache=self.create_nbhtml_cache_store(),
            job_store=self.create_noteburst_job_store(),
            http_client=self.http_client,
            logger=self._logger,
            arq_queue=self.arq_queue,
        )

    def create_background_page_service(self) -> BackgroundPageService:
        """Create a BackgroundPageService, which includes page methods only
        suitable for background tasks (arq workers and CLI commands).
        """
        return BackgroundPageService(
            page_store=self.create_page_store(),
            html_cache=self.create_nbhtml_cache_store(),
            job_store=self.create_noteburst_job_store(),
            http_client=self.http_client,
            logger=self._logger,
            arq_queue=self.arq_queue,
        )

    async def create_github_repo_service(
        self, *, owner: str, repo: str
    ) -> GitHubRepoService:
        """Create a GitHubRepoService for a specific repository, resolving
        the GitHub App installation for that repository.
        """
        return await GitHubRepoService.create_for_repo(
            owner=owner,
            repo=repo,
            http_client=self.http_client,
            page_service=self.create_page_service(),
            logger=self._logger,
        )

    async def create_github_repo_service_for_installation(
        self, *, installation_id: int
    ) -> GitHubRepoService:
        """Create a GitHubRepoService authenticated as a known GitHub App
        installation (e.g. from a webhook payload).
        """
        github_client = await self.create_github_installation_client(
            installation_id=installation_id
        )
        return GitHubRepoService(
            http_client=self.http_client,
            github_client=github_client,
            page_service=self.create_page_service(),
            logger=self._logger,
        )

    async def create_github_check_run_service(
        self, *, installation_id: int
    ) -> GitHubCheckRunService:
        """Create a GitHubCheckRunService for running notebook checks on
        pull requests.
        """
        github_client = await self.create_github_installation_client(
            installation_id=installation_id
        )
        repo_service = await self.create_github_repo_service_for_installation(
            installation_id=installation_id
        )
        return GitHubCheckRunService(
            http_client=self.http_client,
            github_client=github_client,
            repo_service=repo_service,
            page_service=self.create_page_service(),
            logger=self._logger,
        )

    def create_run_scheduler_service(self) -> RunSchedulerService:
        """Create a RunSchedulerService for scheduling page runs."""
        return RunSchedulerService(
            scheduled_run_store=self.create_scheduled_run_store(),
            page_store=self.create_page_store(),
            arq_queue=self.arq_queue,
            logger=self._logger,
        )


class WorkerFactory(Factory):
    """A Factory variant for arq worker tasks.

    Page services created by this factory (including those embedded in the
    GitHub services) are `BackgroundPageService` instances, which include
    methods only suitable for background execution.
    """

    def create_page_service(self) -> BackgroundPageService:
        """Create a BackgroundPageService."""
        return self.create_background_page_service()
