"""GitHub webhook handlers, registrered with the POST /github/webhooks
endpoint.
"""

from __future__ import annotations

from gidgethub.httpx import GitHubAPI
from gidgethub.routing import Router
from gidgethub.sansio import Event
from structlog.stdlib import BoundLogger

__all__ = ["router"]


router = Router()
"""GitHub webhook router."""


@router.register("push")
async def handle_push_event(
    event: Event,
    github_client: GitHubAPI,
    logger: BoundLogger,
) -> None:
    """Handle the ``push`` webhook event from GitHub.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    github_client : `gidgethub.httpx.GitHubAPI`
        The GitHub API client, pre-authorized as an app installation.
    logger
        The logger instance
    """
    logger.debug(
        "GitHub push event",
        git_ref=event.data["ref"],
        repo=event.data["repository"]["full_name"],
    )


@router.register("installation_repositories", action="added")
async def handle_repositories_added(
    event: Event,
    github_client: GitHubAPI,
    logger: BoundLogger,
) -> None:
    """Handle the ``installation_repositories`` (added) webhook event from
    GitHub.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    github_client : `gidgethub.httpx.GitHubAPI`
        The GitHub API client, pre-authorized as an app installation.
    logger
        The logger instance
    """
    logger.debug(
        "GitHub installation_repositories added event",
        repos=event.data["repositories_added"],
    )


@router.register("installation_repositories", action="removed")
async def handle_repositories_removed(
    event: Event,
    github_client: GitHubAPI,
    logger: BoundLogger,
) -> None:
    """Handle the ``installation_repositories`` (removed) webhook event from
    GitHub.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    github_client : `gidgethub.httpx.GitHubAPI`
        The GitHub API client, pre-authorized as an app installation.
    logger
        The logger instance
    """
    logger.debug(
        "GitHub installation_repositories removed event",
        repos=event.data["repositories_removed"],
    )


@router.register("pull_request", action="opened")
async def handle_pr_opened(
    event: Event,
    github_client: GitHubAPI,
    logger: BoundLogger,
) -> None:
    """Handle the ``pull_request`` (opened) webhook event from
    GitHub.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    github_client : `gidgethub.httpx.GitHubAPI`
        The GitHub API client, pre-authorized as an app installation.
    logger
        The logger instance
    """
    logger.debug(
        "GitHub pull_request opened event",
        number=event.data["number"],
        repo=event.data["repository"]["full_name"],
    )


@router.register("pull_request", action="synchronized")
async def handle_pr_sync(
    event: Event,
    github_client: GitHubAPI,
    logger: BoundLogger,
) -> None:
    """Handle the ``pull_request`` (synchronized) webhook event from
    GitHub.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    github_client : `gidgethub.httpx.GitHubAPI`
        The GitHub API client, pre-authorized as an app installation.
    logger
        The logger instance
    """
    logger.debug(
        "GitHub pull_request synchronized event",
        number=event.data["number"],
        repo=event.data["repository"]["full_name"],
    )


@router.register("ping")
async def handle_ping(
    event: Event,
    github_client: GitHubAPI,
    logger: BoundLogger,
) -> None:
    """Handle the ``ping` webhook event from GitHub to let us know we've
    set up the app properly.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    github_client : `gidgethub.httpx.GitHubAPI`
        The GitHub API client, pre-authorized as an app installation.
    logger
        The logger instance
    """
    logger.info(
        "GitHub ping",
        hook=event.data["hook"],
    )
