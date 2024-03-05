"""The main application factory for the times-square service.

Notes
-----
Be aware that, following the normal pattern for FastAPI services, the app is
constructed when this module is loaded and is not deferred until a function is
called.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from importlib.metadata import version
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from fastapi.responses import JSONResponse
from safir.dependencies.arq import arq_dependency
from safir.dependencies.db_session import db_session_dependency
from safir.dependencies.http_client import http_client_dependency
from safir.logging import configure_logging, configure_uvicorn_logging
from safir.middleware.x_forwarded import XForwardedMiddleware
from structlog import get_logger

from .config import config
from .dependencies.redis import redis_dependency
from .exceptions import TimesSquareError
from .handlers.external import external_router
from .handlers.internal import internal_router
from .handlers.v1 import v1_router

if TYPE_CHECKING:
    from fastapi import Request

__all__ = ["app", "config"]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator:
    """Context manager for the application lifespan."""
    logger = get_logger("ook")
    logger.debug("Times Square is starting up.")

    await db_session_dependency.initialize(
        str(config.database_url), config.database_password.get_secret_value()
    )
    await redis_dependency.initialize(str(config.redis_url))
    await arq_dependency.initialize(
        mode=config.arq_mode, redis_settings=config.arq_redis_settings
    )

    logger.info("Times Square started up.")

    yield

    # Shutdown phase:

    logger.debug("Times Square is shutting down.")

    await http_client_dependency.aclose()
    await db_session_dependency.aclose()
    await redis_dependency.close()

    logger.info("Times Square shut down complete.")


configure_logging(
    profile=config.profile,
    log_level=config.log_level,
    name=config.logger_name,
)
configure_uvicorn_logging(config.log_level)

app = FastAPI(
    title="Times Square",
    description=Path(__file__).parent.joinpath("description.md").read_text(),
    version=version("times-square"),
    openapi_url=f"{config.path_prefix}/openapi.json",
    docs_url=f"{config.path_prefix}/docs",
    redoc_url=f"{config.path_prefix}/redoc",
    openapi_tags=[{"name": "v1", "description": "Times Square v1 REST API"}],
    lifespan=lifespan,
)
"""The FastAPI application for times-square."""

# Add middleware
app.add_middleware(XForwardedMiddleware)

# Add routers
app.include_router(internal_router)
app.include_router(external_router, prefix=f"{config.path_prefix}")
app.include_router(v1_router, prefix=f"{config.path_prefix}/v1")


@app.exception_handler(TimesSquareError)
async def ts_exception_handler(
    request: Request, exc: TimesSquareError
) -> JSONResponse:
    """Handle Times Square errors."""
    return JSONResponse(
        status_code=exc.status_code, content={"detail": [exc.to_dict()]}
    )


def create_openapi() -> str:
    """Create the OpenAPI spec for static documentation."""
    spec = get_openapi(
        title=app.title,
        version=app.version,
        description=app.description,
        routes=app.routes,
    )
    return json.dumps(spec)
