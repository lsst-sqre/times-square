"""Request context dependency for FastAPI.

This dependency gathers a variety of information into a single object for
the convenience of writing request handlers. It also provides a place to
store a `structlog.BoundLogger` that can gather additional context during
processing, including from dependencies.
"""

from dataclasses import dataclass
from typing import Annotated, Any

from fastapi import Depends, Request, Response
from safir.dependencies.db_session import db_session_dependency
from safir.dependencies.logger import logger_dependency
from sqlalchemy.ext.asyncio import AsyncSession
from structlog.stdlib import BoundLogger

from timessquare.factory import Factory, ProcessContext

__all__ = [
    "ContextDependency",
    "RequestContext",
    "context_dependency",
]


@dataclass(slots=True)
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

    logger: BoundLogger
    """The request logger, rebound with discovered context."""

    session: AsyncSession
    """The database session."""

    factory: Factory
    """The component factory."""

    def get_request_username(self) -> str | None:
        """Get the username who made the request.

        Uses the X-Auth-Request-Username header passed by Gafaelfawr.
        """
        return self.request.headers.get("X-Auth-Request-User")

    def rebind_logger(self, **values: Any) -> None:
        """Add the given values to the logging context.

        Parameters
        ----------
        **values
            Additional values that should be added to the logging context.
        """
        self.logger = self.logger.bind(**values)
        self.factory.set_logger(self.logger)


class ContextDependency:
    """Provide a per-request context as a FastAPI dependency.

    Each request gets a `RequestContext`. To save overhead, the portions of
    the context that are shared by all requests are collected into the single
    process-global `~timessquare.factory.ProcessContext` and reused with each
    request.
    """

    def __init__(self) -> None:
        self._process_context: ProcessContext | None = None

    async def __call__(
        self,
        request: Request,
        response: Response,
        session: Annotated[AsyncSession, Depends(db_session_dependency)],
        logger: Annotated[BoundLogger, Depends(logger_dependency)],
    ) -> RequestContext:
        """Create a per-request context and return it."""
        return RequestContext(
            request=request,
            response=response,
            logger=logger,
            session=session,
            factory=Factory(
                logger=logger,
                session=session,
                process_context=self.process_context,
            ),
        )

    @property
    def process_context(self) -> ProcessContext:
        """The underlying process context, primarily for use in tests."""
        if not self._process_context:
            raise RuntimeError("ContextDependency not initialized")
        return self._process_context

    async def initialize(self) -> None:
        """Initialize the process-wide shared context."""
        if self._process_context:
            await self._process_context.aclose()
        self._process_context = await ProcessContext.create()

    async def aclose(self) -> None:
        """Clean up the per-process context."""
        if self._process_context:
            await self._process_context.aclose()
        self._process_context = None


context_dependency = ContextDependency()
"""The dependency that will return the per-request context."""
