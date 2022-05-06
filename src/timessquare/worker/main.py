"""Arq-based queue worker lifecycle configuration."""

from __future__ import annotations

import uuid
from typing import Any, Dict

import httpx
import structlog
from safir.dependencies.db_session import db_session_dependency
from safir.logging import configure_logging

from timessquare.config import config
from timessquare.dependencies.redis import redis_dependency

from .functions import (
    ping,
    pull_request_sync,
    repo_added,
    repo_push,
    repo_removed,
)


async def startup(ctx: Dict[Any, Any]) -> None:
    """Runs during working start-up to set up the worker context."""
    configure_logging(
        profile=config.profile,
        log_level=config.log_level,
        name="timessquare",
    )
    logger = structlog.get_logger("timessquare")
    # The instance key uniquely identifies this worker in logs
    instance_key = uuid.uuid4().hex
    logger = logger.bind(worker_instance=instance_key)

    logger.info("Starting up worker")

    http_client = httpx.AsyncClient()
    ctx["http_client"] = http_client

    ctx["logger"] = logger
    logger.info("Start up complete")

    # Set up FastAPI dependencies; we can use them "manually" with
    # arq to provide resources similarly to FastAPI endpoints
    await db_session_dependency.initialize(
        config.database_url, config.database_password.get_secret_value()
    )
    await redis_dependency.initialize(config.redis_url)


async def shutdown(ctx: Dict[Any, Any]) -> None:
    """Runs during worker shut-down to resources."""
    if "logger" in ctx.keys():
        logger = ctx["logger"]
    else:
        logger = structlog.get_logger("timessquare")
    logger.info("Running worker shutdown.")

    await db_session_dependency.aclose()
    await redis_dependency.close()

    try:
        await ctx["http_client"].aclose()
    except Exception as e:
        logger.warning("Issue closing the http_client: %s", str(e))

    logger.info("Worker shutdown complete.")


class WorkerSettings:
    """Configuration for a Times Square arq worker.

    See `arq.worker.Worker` for details on these attributes.
    """

    functions = [ping, repo_push, repo_added, repo_removed, pull_request_sync]

    redis_settings = config.arq_redis_settings

    queue_name = config.queue_name

    on_startup = startup

    on_shutdown = shutdown
