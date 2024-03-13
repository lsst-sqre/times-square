"""Arq-based queue worker lifecycle configuration."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import Any, ClassVar

import httpx
import structlog
from safir.dependencies.db_session import db_session_dependency
from safir.logging import configure_logging
from safir.slack.blockkit import SlackMessage, SlackTextField
from safir.slack.webhook import SlackWebhookClient

from timessquare import __version__
from timessquare.config import config
from timessquare.dependencies.redis import redis_dependency

from .functions import (
    compute_check_run,
    create_check_run,
    create_rerequested_check_run,
    ping,
    pull_request_sync,
    repo_added,
    repo_push,
    repo_removed,
)


async def startup(ctx: dict[Any, Any]) -> None:
    """Set up the worker context."""
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

    if config.slack_webhook_url:
        slack_client = SlackWebhookClient(
            str(config.slack_webhook_url),
            "Times Square worker",
            logger=logger,
        )
        ctx["slack"] = slack_client

    ctx["logger"] = logger

    # Set up FastAPI dependencies; we can use them "manually" with
    # arq to provide resources similarly to FastAPI endpoints
    await db_session_dependency.initialize(
        str(config.database_url), config.database_password.get_secret_value()
    )
    await redis_dependency.initialize(str(config.redis_url))

    logger.info("Start up complete")

    if "slack" in ctx:
        await ctx["slack"].post(
            SlackMessage(
                message="Times Square worker started up.",
                fields=[
                    SlackTextField(
                        heading="Version",
                        text=__version__,
                    ),
                ],
            )
        )


async def shutdown(ctx: dict[Any, Any]) -> None:
    """Shut-down resources."""
    if "logger" in ctx:
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

    if "slack" in ctx:
        await ctx["slack"].post(
            SlackMessage(
                message="Times Square worker shut down.",
                fields=[
                    SlackTextField(
                        heading="Version",
                        text=__version__,
                    ),
                ],
            )
        )


class WorkerSettings:
    """Configuration for a Times Square arq worker.

    See `arq.worker.Worker` for details on these attributes.
    """

    functions: ClassVar[list[Callable]] = [
        ping,
        repo_push,
        repo_added,
        repo_removed,
        pull_request_sync,
        compute_check_run,
        create_check_run,
        create_rerequested_check_run,
    ]

    redis_settings = config.arq_redis_settings

    queue_name = config.queue_name

    on_startup = startup

    on_shutdown = shutdown
