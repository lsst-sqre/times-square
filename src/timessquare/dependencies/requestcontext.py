"""A FastAPI dependency that wraps multiple common dependencies."""

from dataclasses import dataclass

from fastapi import Depends, Request, Response
from httpx import AsyncClient
from redis.asyncio import Redis
from safir.dependencies.db_session import db_session_dependency
from safir.dependencies.http_client import http_client_dependency
from safir.dependencies.logger import logger_dependency
from safir.github import GitHubAppClientFactory
from sqlalchemy.ext.asyncio import async_scoped_session
from structlog.stdlib import BoundLogger

from timessquare.config import Config, config
from timessquare.dependencies.redis import redis_dependency
from timessquare.services.githubrepo import GitHubRepoService
from timessquare.services.page import PageService
from timessquare.storage.nbhtmlcache import NbHtmlCacheStore
from timessquare.storage.noteburstjobstore import NoteburstJobStore
from timessquare.storage.page import PageStore

__all__ = ["RequestContext", "context_dependency"]


@dataclass
class RequestContext:
    """Holds the incoming request and its surrounding context.

    The primary reason for the existence of this class is to allow the
    functions involved in request processing to repeatedly rebind the request
    logger to include more information, without having to pass both the
    request and the logger separately to every function.
    """

    request: Request
    """The incoming request."""

    response: Response
    """The response (useful for setting response headers)."""

    config: Config
    """Times Square's configuration."""

    logger: BoundLogger
    """The request logger, rebound with discovered context."""

    session: async_scoped_session
    """The database session."""

    redis: Redis
    """Redis connection pool."""

    http_client: AsyncClient
    """Shared HTTP client."""

    @property
    def page_service(self) -> PageService:
        """An instance of the page service."""
        return PageService(
            page_store=PageStore(self.session),
            html_cache=NbHtmlCacheStore(self.redis),
            job_store=NoteburstJobStore(self.redis),
            http_client=self.http_client,
            logger=self.logger,
        )

    async def create_github_repo_service(
        self, owner: str, repo: str
    ) -> GitHubRepoService:
        """Create an instance of the GitHub repository service for manging
        GitHub-backed pages and accessing GitHub's API.
        """
        return await GitHubRepoService.create_for_repo(
            owner=owner,
            repo=repo,
            http_client=self.http_client,
            page_service=self.page_service,
            logger=self.logger,
        )

    def create_github_client_factory(self) -> GitHubAppClientFactory:
        """Create a GitHub client factory for accessing GitHub's API."""
        if (
            config.github_app_id is None
            or config.github_app_private_key is None
        ):
            raise RuntimeError(
                "GitHub App is not configured; "
                "set GITHUB_APP_ID and GITHUB_APP_PRIVATE_KEY, "
            )
        return GitHubAppClientFactory(
            id=config.github_app_id,
            key=config.github_app_private_key.get_secret_value(),
            name="lsst-sqre/times-square",
            http_client=self.http_client,
        )

    def get_request_username(self) -> str | None:
        """Get the username who made the request.

        Uses the X-Auth-Request-Username header passed by Gafaelfawr.
        """
        return self.request.headers.get("X-Auth-Request-User")

    def rebind_logger(self, **values: str | None) -> None:
        """Add the given values to the logging context.

        Also updates the logging context stored in the request object in case
        the request context later needs to be recreated from the request.

        Parameters
        ----------
        **values : `str` or `None`
            Additional values that should be added to the logging context.
        """
        self.logger = self.logger.bind(**values)


async def context_dependency(
    request: Request,
    response: Response,
    logger: BoundLogger = Depends(logger_dependency),
    session: async_scoped_session = Depends(db_session_dependency),
    redis: Redis = Depends(redis_dependency),
    http_client: AsyncClient = Depends(http_client_dependency),
) -> RequestContext:
    """Provide a RequestContext as a dependency."""
    return RequestContext(
        request=request,
        response=response,
        config=config,
        logger=logger,
        session=session,
        redis=redis,
        http_client=http_client,
    )
