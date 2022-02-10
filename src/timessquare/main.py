"""The main application factory for the times-square service.

Notes
-----
Be aware that, following the normal pattern for FastAPI services, the app is
constructed when this module is loaded and is not deferred until a function is
called.
"""

from __future__ import annotations

from importlib.metadata import metadata
from typing import TYPE_CHECKING

import structlog
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from safir.dependencies.http_client import http_client_dependency
from safir.logging import configure_logging
from safir.middleware.x_forwarded import XForwardedMiddleware

from .config import config
from .database import check_database
from .dependencies.dbsession import db_session_dependency
from .exceptions import TimesSquareError
from .handlers.external import external_router
from .handlers.internal import internal_router
from .handlers.v1 import v1_router

if TYPE_CHECKING:
    from fastapi import Request

__all__ = ["app", "config"]


configure_logging(
    profile=config.profile,
    log_level=config.log_level,
    name=config.logger_name,
)

app = FastAPI(
    title="times-square",
    description=metadata("times-square").get("Summary", ""),
    version=metadata("times-square").get("Version", "0.0.0"),
    openapi_url=f"/{config.name}/openapi.json",
    docs_url=f"/{config.name}/docs",
    redoc_url=None,
)
"""The FastAPI application for times-square."""

app.include_router(internal_router)
app.include_router(external_router, prefix=f"/{config.name}")
app.include_router(v1_router, prefix=f"/{config.name}/v1")


@app.on_event("startup")
async def startup_event() -> None:
    logger = structlog.get_logger(config.logger_name)
    await check_database(config.asyncpg_database_url, logger)
    await db_session_dependency.initialize(config.asyncpg_database_url)
    app.add_middleware(XForwardedMiddleware)


@app.on_event("shutdown")
async def shutdown_event() -> None:
    await http_client_dependency.aclose()
    await db_session_dependency.aclose()


@app.exception_handler(TimesSquareError)
async def ts_exception_handler(
    request: Request, exc: TimesSquareError
) -> JSONResponse:
    """Custom handler for Times Square error."""
    return JSONResponse(
        status_code=exc.status_code, content={"detail": [exc.to_dict()]}
    )
