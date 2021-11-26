"""A FastAPI dependency that wraps multiple common dependencies."""

from dataclasses import dataclass
from typing import Optional

from fastapi import Depends, Request, Response
from httpx import AsyncClient
from safir.dependencies.http_client import http_client_dependency
from safir.dependencies.logger import logger_dependency
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.stdlib import BoundLogger

from timessquare.config import Config, config
from timessquare.services.page import PageService
from timessquare.storage.page import PageStore

from .dbsession import db_session_dependency

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

    session: AsyncSession
    """The database session."""

    http_client: AsyncClient
    """Shared HTTP client."""

    @property
    def page_service(self) -> PageService:
        return PageService(
            page_store=PageStore(self.session), logger=self.logger
        )

    def rebind_logger(self, **values: Optional[str]) -> None:
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
    session: AsyncSession = Depends(db_session_dependency),
    http_client: AsyncClient = Depends(http_client_dependency),
) -> RequestContext:
    """Provides a RequestContext as a dependency."""
    return RequestContext(
        request=request,
        response=response,
        config=config,
        logger=logger,
        session=session,
        http_client=http_client,
    )
