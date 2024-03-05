"""Handlers for the app's external root, ``/times-square/``."""

from __future__ import annotations

import asyncio
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
from gidgethub.sansio import Event
from pydantic import AnyHttpUrl
from safir.arq import ArqQueue
from safir.dependencies.arq import arq_dependency
from safir.dependencies.logger import logger_dependency
from safir.metadata import get_metadata
from structlog.stdlib import BoundLogger

from timessquare.config import config
from timessquare.dependencies.requestcontext import (
    RequestContext,
    context_dependency,
)

from .githubwebhooks import router as webhook_router
from .models import Index

__all__ = ["get_index", "external_router", "post_github_webhook"]

external_router = APIRouter()
"""FastAPI router for all external handlers."""


@external_router.get(
    "/",
    response_model=Index,
    response_model_exclude_none=True,
    summary="Application metadata",
)
async def get_index(
    request: Request,
    logger: Annotated[BoundLogger, Depends(logger_dependency)],
) -> Index:
    """GET metadata about the application."""
    # There is no need to log simple requests since uvicorn will do this
    # automatically, but this is included as an example of how to use the
    # logger for more complex logging.
    logger.info("Request for application metadata")

    metadata = get_metadata(
        package_name="times-square",
        application_name=config.name,
    )
    # Construct these URLs; this doesn't use request.url_for because the
    # endpoints are in other FastAPI "apps".
    v1_api_url = f"{request.url}v1"
    doc_url = request.url.replace(path=f"/{config.name}/redoc")
    return Index(
        metadata=metadata,
        v1_api_base=AnyHttpUrl(v1_api_url),
        api_docs=AnyHttpUrl(str(doc_url)),
    )


@external_router.post(
    "/github/webhook",
    summary="GitHub App webhook",
    description=("This endpoint receives webhook events from GitHub"),
    status_code=status.HTTP_200_OK,
)
async def post_github_webhook(
    context: Annotated[RequestContext, Depends(context_dependency)],
    logger: Annotated[BoundLogger, Depends(logger_dependency)],
    arq_queue: Annotated[ArqQueue, Depends(arq_dependency)],
) -> Response:
    """Process GitHub webhook events."""
    if not config.enable_github_app:
        return Response(
            "GitHub App is not enabled",
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
        )

    body = await context.request.body()

    if config.github_webhook_secret is None:
        return Response(
            "The webhook secret is not configured",
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
        )

    webhook_secret = config.github_webhook_secret.get_secret_value()
    event = Event.from_http(
        context.request.headers, body, secret=webhook_secret
    )

    github_client_factory = context.create_github_client_factory()

    # Bind the X-GitHub-Delivery header to the logger context; this identifies
    # the webhook request in GitHub's API and UI for diagnostics
    logger = logger.bind(
        github_delivery_id=event.delivery_id, github_event=event.event
    )

    logger.debug("Received GitHub webhook", payload=event.data)

    # Give GitHub some time to reach internal consistency.
    await asyncio.sleep(1)
    await webhook_router.dispatch(
        event, logger, arq_queue, github_client_factory
    )

    return Response(status_code=status.HTTP_202_ACCEPTED)
