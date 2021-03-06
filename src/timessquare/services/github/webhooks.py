"""GitHub webhook handlers, registrered with the POST /github/webhooks
endpoint.
"""

from __future__ import annotations

from gidgethub.routing import Router
from gidgethub.sansio import Event
from safir.arq import ArqQueue
from structlog.stdlib import BoundLogger

from timessquare.config import config
from timessquare.domain.githubwebhook import (
    GitHubAppInstallationEventModel,
    GitHubAppInstallationRepositoriesEventModel,
    GitHubCheckRunEventModel,
    GitHubCheckSuiteEventModel,
    GitHubPullRequestEventModel,
    GitHubPushEventModel,
)

__all__ = ["router"]


router = Router()
"""GitHub webhook router."""


@router.register("installation", action="created")
async def handle_installation_created(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
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
    logger.info(
        "GitHub installation created event",
        owner=event.data["installation"]["account"]["login"],
        repos=event.data["repositories"],
    )

    payload = GitHubAppInstallationEventModel.parse_obj(event.data)

    for repo in payload.repositories:
        await arq_queue.enqueue("repo_added", payload=payload, repo=repo)


@router.register("installation", action="unsuspend")
async def handle_installation_unsuspend(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
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
    logger.info(
        "GitHub installation unsuspend event",
        owner=event.data["installation"]["account"]["login"],
        repos=event.data["repositories"],
    )

    payload = GitHubAppInstallationEventModel.parse_obj(event.data)

    for repo in payload.repositories:
        await arq_queue.enqueue("repo_added", payload=payload, repo=repo)


@router.register("installation", action="deleted")
async def handle_installation_deleted(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
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
    logger.info(
        "GitHub installation deleted event",
        owner=event.data["installation"]["account"]["login"],
    )

    payload = GitHubAppInstallationEventModel.parse_obj(event.data)

    for repo in payload.repositories:
        await arq_queue.enqueue("repo_removed", payload=payload, repo=repo)


@router.register("installation", action="suspend")
async def handle_installation_suspend(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
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
    logger.info(
        "GitHub installation suspended event",
        owner=event.data["installation"]["account"]["login"],
    )

    payload = GitHubAppInstallationEventModel.parse_obj(event.data)

    for repo in payload.repositories:
        await arq_queue.enqueue("repo_removed", payload=payload, repo=repo)


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
    logger.info(
        "GitHub installation_repositories added event",
        repos=event.data["repositories_added"],
    )

    payload = GitHubAppInstallationRepositoriesEventModel.parse_obj(event.data)

    for repo in payload.repositories_added:
        await arq_queue.enqueue("repo_added", payload=payload, repo=repo)


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
    logger.info(
        "GitHub installation_repositories removed event",
        repos=event.data["repositories_removed"],
    )

    payload = GitHubAppInstallationRepositoriesEventModel.parse_obj(event.data)

    for repo in payload.repositories_removed:
        await arq_queue.enqueue("repo_removed", payload=payload, repo=repo)


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
    logger.info(
        "GitHub push event",
        git_ref=event.data["ref"],
        repo=event.data["repository"]["full_name"],
    )

    # Parse webhook payload
    payload = GitHubPushEventModel.parse_obj(event.data)

    # Only process push events for the default branch
    if payload.ref == f"refs/heads/{payload.repository.default_branch}":
        await arq_queue.enqueue("repo_push", payload=payload)


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
    logger.info(
        "GitHub pull_request opened event",
        number=event.data["number"],
        repo=event.data["repository"]["full_name"],
    )

    payload = GitHubPullRequestEventModel.parse_obj(event.data)

    await arq_queue.enqueue(
        "pull_request_sync",
        payload=payload,
    )


@router.register("pull_request", action="synchronize")
async def handle_pr_sync(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
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

    payload = GitHubPullRequestEventModel.parse_obj(event.data)

    await arq_queue.enqueue(
        "pull_request_sync",
        payload=payload,
    )


@router.register("check_suite")
async def handle_check_suite_request(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
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
        payload = GitHubCheckSuiteEventModel.parse_obj(event.data)
        logger.debug("GitHub check suite request payload", payload=payload)

        # Note that architecturally it might be possible to run this as part
        # of the webhook handler or a BackgroundTask; but for now it's
        # implemented as a queued task for uniformity with the other tasks
        await arq_queue.enqueue(
            "create_check_run",
            payload=payload,
        )


@router.register("check_run", action="created")
async def handle_check_run_created(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
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
        payload = GitHubCheckRunEventModel.parse_obj(event.data)
        logger.debug("GitHub check run request payload", payload=payload)

        await arq_queue.enqueue(
            "compute_check_run",
            payload=payload,
        )


@router.register("check_run", action="rerequested")
async def handle_check_run_rerequested(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
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
    payload = GitHubCheckRunEventModel.parse_obj(event.data)
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
