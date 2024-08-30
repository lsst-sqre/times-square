"""GitHub webhook handlers, registrered with the POST /github/webhooks
endpoint.
"""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any

from gidgethub.routing import Router
from gidgethub.sansio import Event
from safir.arq import ArqQueue
from safir.github import GitHubAppClientFactory
from safir.github.webhooks import (
    GitHubAppInstallationEventModel,
    GitHubAppInstallationRepositoriesEventModel,
    GitHubCheckRunEventModel,
    GitHubCheckSuiteEventModel,
    GitHubPullRequestEventModel,
    GitHubPushEventModel,
)
from structlog.stdlib import BoundLogger

from timessquare.config import config

__all__ = [
    "router",
    "handle_installation_created",
    "handle_installation_unsuspend",
    "handle_installation_deleted",
    "handle_installation_suspend",
    "handle_repositories_added",
    "handle_repositories_removed",
    "handle_check_run_created",
    "handle_check_run_rerequested",
    "handle_check_suite_request",
    "handle_pr_opened",
    "handle_pr_sync",
    "handle_push_event",
    "handle_ping",
]


router = Router()
"""GitHub webhook router."""


def filter_installation_owner(func: Callable) -> Callable:
    """Ignore GitHub events for owners that are not in the accepted orgs
    (webhook function decorator).
    """

    async def noop(
        event: Event,
        logger: BoundLogger,
        owner: str,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Log that we're ignoring the event."""
        logger.debug(
            "Ignoring GitHub event for unaccepted org",
            owner=owner,
            accepted_orgs=config.accepted_github_orgs,
        )

    @functools.wraps(func)
    async def wrapper_filter_installation_owner(
        event: Event,
        logger: BoundLogger,
        arq_queue: ArqQueue,
        github_client_factory: GitHubAppClientFactory,
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        installation_id = event.data["installation"]["id"]
        github_client = github_client_factory.create_anonymous_client()
        installation = await github_client.getitem(
            "/app/installations/{installation_id}",
            url_vars={"installation_id": installation_id},
            jwt=github_client_factory.get_app_jwt(),
        )
        owner = installation["account"]["login"]
        if owner not in config.accepted_github_orgs:
            return await noop(event, logger, owner)
        return await func(
            event, logger, arq_queue, github_client_factory, *args, **kwargs
        )

    return wrapper_filter_installation_owner


@router.register("installation", action="created")
@filter_installation_owner
async def handle_installation_created(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Handle the ``installation`` (created) webhook event from
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
    owner = event.data["installation"]["account"]["login"]

    logger.info(
        "GitHub installation created event",
        owner=owner,
        repos=event.data["repositories"],
    )

    payload = GitHubAppInstallationEventModel.model_validate(event.data)

    for repo in payload.repositories:
        await arq_queue.enqueue("repo_added", payload=payload, repo=repo)


@router.register("installation", action="unsuspend")
@filter_installation_owner
async def handle_installation_unsuspend(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Handle the ``installation`` (unsuspend) webhook event from
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
    owner = event.data["installation"]["account"]["login"]

    logger.info(
        "GitHub installation unsuspend event",
        owner=owner,
        repos=event.data["repositories"],
    )

    payload = GitHubAppInstallationEventModel.model_validate(event.data)

    for repo in payload.repositories:
        await arq_queue.enqueue("repo_added", payload=payload, repo=repo)


@router.register("installation", action="deleted")
async def handle_installation_deleted(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Handle the ``installation`` (deleted) webhook event from
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
    owner = event.data["installation"]["account"]["login"]

    logger.info(
        "GitHub installation deleted event",
        owner=owner,
    )

    payload = GitHubAppInstallationEventModel.model_validate(event.data)

    for repo in payload.repositories:
        await arq_queue.enqueue("repo_removed", payload=payload, repo=repo)


@router.register("installation", action="suspend")
async def handle_installation_suspend(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Handle the ``installation`` (suspend) webhook event from
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
    owner = event.data["installation"]["account"]["login"]

    logger.info(
        "GitHub installation suspended event",
        owner=owner,
    )

    payload = GitHubAppInstallationEventModel.model_validate(event.data)

    for repo in payload.repositories:
        await arq_queue.enqueue("repo_removed", payload=payload, repo=repo)


@router.register("installation_repositories", action="added")
@filter_installation_owner
async def handle_repositories_added(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
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
    owner = event.data["installation"]["account"]["login"]
    if owner not in config.accepted_github_orgs:
        logger.debug(
            "Ignoring GitHub installation suspend event for unaccepted org",
            owner=owner,
            accepted_orgs=config.accepted_github_orgs,
        )
        return

    logger.info(
        "GitHub installation_repositories added event",
        repos=event.data["repositories_added"],
    )

    payload = GitHubAppInstallationRepositoriesEventModel.model_validate(
        event.data
    )

    for repo in payload.repositories_added:
        await arq_queue.enqueue("repo_added", payload=payload, repo=repo)


@router.register("installation_repositories", action="removed")
async def handle_repositories_removed(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
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
    logger.info(
        "GitHub installation_repositories removed event",
        repos=event.data["repositories_removed"],
    )

    payload = GitHubAppInstallationRepositoriesEventModel.model_validate(
        event.data
    )

    for repo in payload.repositories_removed:
        await arq_queue.enqueue("repo_removed", payload=payload, repo=repo)


@router.register("push")
@filter_installation_owner
async def handle_push_event(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
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
    logger.info(
        "GitHub push event",
        git_ref=event.data["ref"],
        repo=event.data["repository"]["full_name"],
    )

    # Parse webhook payload
    payload = GitHubPushEventModel.model_validate(event.data)

    # Only process push events for the default branch
    if payload.ref == f"refs/heads/{payload.repository.default_branch}":
        await arq_queue.enqueue("repo_push", payload=payload)


@router.register("pull_request", action="opened")
@filter_installation_owner
async def handle_pr_opened(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
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
    logger.info(
        "GitHub pull_request opened event",
        number=event.data["number"],
        repo=event.data["repository"]["full_name"],
    )

    payload = GitHubPullRequestEventModel.model_validate(event.data)

    await arq_queue.enqueue(
        "pull_request_sync",
        payload=payload,
    )


@router.register("pull_request", action="synchronize")
@filter_installation_owner
async def handle_pr_sync(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Handle the ``pull_request`` (synchronize) webhook event from
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
    logger.info(
        "GitHub pull_request synchronize event",
        number=event.data["number"],
        repo=event.data["repository"]["full_name"],
    )

    payload = GitHubPullRequestEventModel.model_validate(event.data)

    await arq_queue.enqueue(
        "pull_request_sync",
        payload=payload,
    )


@router.register("check_suite")
@filter_installation_owner
async def handle_check_suite_request(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Handle the ``check_suite`` (requested and rerequested) webhook event
    from GitHub.

    This handler is responsible for creating a check run. Once GitHub creates
    the check run, GitHub sends a webhook handled by
    `handle_check_run_created`.

    The rerequested action occurs when a re-runs the entire check suite from
    the PR UI. Both "requested" and "rerequested" actions require Times Square
    to create a new check run.

    https://docs.github.com/en/developers/webhooks-and-events/webhooks/webhook-events-and-payloads#check_suite

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    logger
        The logger instance
    arq_queue : `safir.arq.ArqQueue`
        An arq queue client.

    """
    if event.data["action"] in ("requested", "rerequested"):
        logger.info(
            "GitHub check suite request event",
            repo=event.data["repository"]["full_name"],
        )
        payload = GitHubCheckSuiteEventModel.model_validate(event.data)
        logger.debug("GitHub check suite request payload", payload=payload)

        # Note that architecturally it might be possible to run this as part
        # of the webhook handler or a BackgroundTask; but for now it's
        # implemented as a queued task for uniformity with the other tasks
        await arq_queue.enqueue(
            "create_check_run",
            payload=payload,
        )


@router.register("check_run", action="created")
@filter_installation_owner
async def handle_check_run_created(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Handle the ``check_run`` (created) webhook event from GitHub.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    logger
        The logger instance
    arq_queue : `safir.arq.ArqQueue`
        An arq queue client.
    """
    # Note that GitHub sends this webhook to any app with permissions to watch
    # this event; Times Square needs to operate only on its own check run
    # created events.
    if (
        event.data["check_run"]["check_suite"]["app"]["id"]
        == config.github_app_id
    ):
        logger.info(
            "GitHub check run created event",
            repo=event.data["repository"]["full_name"],
        )
        payload = GitHubCheckRunEventModel.model_validate(event.data)
        logger.debug("GitHub check run request payload", payload=payload)

        await arq_queue.enqueue(
            "compute_check_run",
            payload=payload,
        )


@router.register("check_run", action="rerequested")
@filter_installation_owner
async def handle_check_run_rerequested(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Handle the ``check_run`` (rerequested) webhook event from GitHub.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    logger
        The logger instance
    arq_queue : `safir.arq.ArqQueue`
        An arq queue client.
    """
    # Note that GitHub only sends this webhook to the app that's being
    # re-requested.
    logger.info(
        "GitHub check run rerequested event",
        repo=event.data["repository"]["full_name"],
    )
    payload = GitHubCheckRunEventModel.model_validate(event.data)
    logger.debug("GitHub check run request payload", payload=payload)

    await arq_queue.enqueue(
        "create_rerequested_check_run",
        payload=payload,
    )


@router.register("ping")
async def handle_ping(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
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
