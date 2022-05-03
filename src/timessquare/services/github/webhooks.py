"""GitHub webhook handlers, registrered with the POST /github/webhooks
endpoint.
"""

from __future__ import annotations

from gidgethub.routing import Router
from gidgethub.sansio import Event
from safir.dependencies.arq import ArqQueue
from structlog.stdlib import BoundLogger

from timessquare.domain.githubwebhook import (
    GitHubAppInstallationRepositoriesEventModel,
    GitHubPullRequestEventModel,
    GitHubPushEventModel,
)

__all__ = ["router"]


router = Router()
"""GitHub webhook router."""


@router.register("push")
async def handle_push_event(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
) -> None:
    """Handle the ``push`` webhook event from GitHub.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    logger
        The logger instance
    arq_queue : `safir.dependencies.arq.ArqQueue`
        An arq queue client.
    """
    logger.debug(
        "GitHub push event",
        git_ref=event.data["ref"],
        repo=event.data["repository"]["full_name"],
    )

    # Parse webhook payload
    payload = GitHubPushEventModel.parse_obj(event.data)

    # Only process push events for the default branch
    if payload.ref == f"refs/heads/{payload.repository.default_branch}":
        arq_queue.enqueue("repo_push", payload=payload)


@router.register("installation_repositories", action="added")
async def handle_repositories_added(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
) -> None:
    """Handle the ``installation_repositories`` (added) webhook event from
    GitHub.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    logger
        The logger instance
    arq_queue : `safir.dependencies.arq.ArqQueue`
        An arq queue client.
    """
    logger.debug(
        "GitHub installation_repositories added event",
        repos=event.data["repositories_added"],
    )

    payload = GitHubAppInstallationRepositoriesEventModel.parse_obj(event.data)

    for repo in payload.repositories_added:
        arq_queue.enqueue("repo_added", payload=payload, repo=repo)


@router.register("installation_repositories", action="removed")
async def handle_repositories_removed(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
) -> None:
    """Handle the ``installation_repositories`` (removed) webhook event from
    GitHub.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    logger
        The logger instance
    arq_queue : `safir.dependencies.arq.ArqQueue`
        An arq queue client.
    """
    logger.debug(
        "GitHub installation_repositories removed event",
        repos=event.data["repositories_removed"],
    )

    payload = GitHubAppInstallationRepositoriesEventModel.parse_obj(event.data)

    for repo in payload.repositories_removed:
        arq_queue.enqueue("repo_removed", payload=payload, repo=repo)


@router.register("pull_request", action="opened")
async def handle_pr_opened(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
) -> None:
    """Handle the ``pull_request`` (opened) webhook event from
    GitHub.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    logger
        The logger instance
    arq_queue : `safir.dependencies.arq.ArqQueue`
        An arq queue client.
    """
    logger.debug(
        "GitHub pull_request opened event",
        number=event.data["number"],
        repo=event.data["repository"]["full_name"],
    )

    payload = GitHubPullRequestEventModel.parse_obj(event.data)

    arq_queue.enqueue(
        "pull_request_sync",
        payload=payload,
    )


@router.register("pull_request", action="synchronized")
async def handle_pr_sync(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
) -> None:
    """Handle the ``pull_request`` (synchronized) webhook event from
    GitHub.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    logger
        The logger instance
    arq_queue : `safir.dependencies.arq.ArqQueue`
        An arq queue client.
    """
    logger.debug(
        "GitHub pull_request synchronized event",
        number=event.data["number"],
        repo=event.data["repository"]["full_name"],
    )

    payload = GitHubPullRequestEventModel.parse_obj(event.data)

    arq_queue.enqueue(
        "pull_request_sync",
        payload=payload,
    )


@router.register("ping")
async def handle_ping(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
) -> None:
    """Handle the ``ping` webhook event from GitHub to let us know we've
    set up the app properly.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    logger
        The logger instance
    arq_queue : `safir.dependencies.arq.ArqQueue`
        An arq queue client.
    """
    logger.info(
        "GitHub ping",
        hook=event.data["hook"],
    )
