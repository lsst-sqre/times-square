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
)
from structlog.stdlib import BoundLogger

from timessquare.config import config
from timessquare.storage.github.apimodels import (
    GitHubInstallationTargetRenamedEventModel,
    GitHubPushEventWithIdModel,
    GitHubRepositoryRenamedEventModel,
    GitHubRepositoryTransferredEventModel,
)

__all__ = [
    "handle_check_run_created",
    "handle_check_run_rerequested",
    "handle_check_suite_request",
    "handle_installation_created",
    "handle_installation_deleted",
    "handle_installation_suspend",
    "handle_installation_target_renamed",
    "handle_installation_unsuspend",
    "handle_ping",
    "handle_pr_opened",
    "handle_pr_sync",
    "handle_push_event",
    "handle_repositories_added",
    "handle_repositories_removed",
    "handle_repository_renamed",
    "handle_repository_transferred",
    "router",
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
    payload = GitHubPushEventWithIdModel.model_validate(event.data)

    # Only process push events for the default branch
    if payload.ref == f"refs/heads/{payload.repository.default_branch}":
        await arq_queue.enqueue("repo_push", payload=payload)


@router.register("repository", action="renamed")
@filter_installation_owner
async def handle_repository_renamed(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Handle the ``repository`` (renamed) webhook event from GitHub.

    Renaming a repository does not change its content, so this only queues a
    task that flips the repository name stored on the repository's pages.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    logger
        The logger instance
    arq_queue : `safir.dependencies.arq.ArqQueue`
        An arq queue client.
    """
    payload = GitHubRepositoryRenamedEventModel.model_validate(event.data)

    logger.info(
        "GitHub repository renamed event",
        github_owner=payload.repository.owner.login,
        old_github_repo=payload.old_repo_name,
        github_repo=payload.repository.name,
        github_repository_id=payload.repository.id,
    )

    await arq_queue.enqueue("repo_renamed", payload=payload)


@router.register("repository", action="transferred")
async def handle_repository_transferred(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Handle the ``repository`` (transferred) webhook event from GitHub.

    Transferring a repository does not change its content, so this only
    queues a task that updates the owner and repository name stored on the
    repository's pages — or, if the new owner is not one Times Square syncs
    from, soft-deletes them.

    Unlike the other repository handlers this is deliberately *not* gated on
    `~timessquare.config.Config.accepted_github_orgs`: a repository
    transferred out of an accepted org is precisely the case whose pages have
    to be retired, and gating here would drop that event. The task decides
    which of the two outcomes applies, and no-ops when it turns out Times
    Square has no pages for the repository.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    logger
        The logger instance
    arq_queue : `safir.dependencies.arq.ArqQueue`
        An arq queue client.
    """
    payload = GitHubRepositoryTransferredEventModel.model_validate(event.data)

    logger.info(
        "GitHub repository transferred event",
        old_github_owner=payload.old_owner_login,
        github_owner=payload.repository.owner.login,
        github_repo=payload.repository.name,
        github_repository_id=payload.repository.id,
    )

    await arq_queue.enqueue("repo_transferred", payload=payload)


@router.register("installation_target", action="renamed")
async def handle_installation_target_renamed(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Handle the ``installation_target`` (renamed) webhook event from GitHub.

    GitHub sends this event when the account a Times Square installation sits
    on — an organization or a personal account — is renamed. Renaming an
    account does not change any repository's content, so this only queues a
    task that flips the owner login stored on that account's pages.

    This event is used in preference to ``organization`` (renamed), which
    reports the same rename for organizations only and is gated behind the
    Members organization permission.

    `~timessquare.config.Config.accepted_github_orgs` is keyed on login names,
    so gating this event on the *new* login alone would drop the very event
    that heals the rename: when an account is renamed, the allowlist still
    names it by its old login. The event is therefore accepted when *either*
    login is allowlisted, and the task warns the operator to update
    ``TS_GITHUB_ORGS``.

    Parameters
    ----------
    event : `gidgethub.sansio.Event`
         The parsed event payload.
    logger
        The logger instance
    arq_queue : `safir.dependencies.arq.ArqQueue`
        An arq queue client.
    """
    payload = GitHubInstallationTargetRenamedEventModel.model_validate(
        event.data
    )

    old_login = payload.old_login
    if old_login is None:
        # GitHub does not require changes.login, and without the old login
        # there is nothing to rename the pages from.
        logger.debug(
            "Ignoring GitHub installation target renamed event with no "
            "login change",
            github_owner=payload.new_login,
        )
        return

    accepted_orgs = config.accepted_github_orgs
    if old_login not in accepted_orgs and payload.new_login not in (
        accepted_orgs
    ):
        logger.debug(
            "Ignoring GitHub installation target renamed event for "
            "unaccepted org",
            old_github_owner=old_login,
            github_owner=payload.new_login,
            accepted_orgs=accepted_orgs,
        )
        return

    logger.info(
        "GitHub installation target renamed event",
        old_github_owner=old_login,
        github_owner=payload.new_login,
        github_owner_id=payload.account.id,
        target_type=payload.target_type,
    )

    await arq_queue.enqueue("owner_renamed", payload=payload)


@router.register("pull_request", action="opened")
async def handle_pr_opened(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Handle the ``pull_request`` (opened) webhook event from GitHub by
    ignoring it.

    The event is received and logged, and nothing else: no task is queued
    and no GitHub API request is made. That is also why this handler is not
    gated by `filter_installation_owner`, whose installation lookup would be
    a GitHub API request made only to decide whether to ignore the event.

    .. warning::

       Do not use ``pull_request`` events to trigger notebook checks. GitHub
       delivers this event for pull requests from forks, with a head commit
       that anyone can author, so acting on it would execute untrusted
       notebooks with Times Square's credentials. Checks are triggered by
       ``check_suite`` events instead (see `handle_check_suite_request`),
       which GitHub only sends for commits pushed to the repository where
       the app is installed.

    Parameters
    ----------
    event
        The parsed event payload.
    logger
        The logger instance.
    arq_queue
        An arq queue client, which is not used.
    """
    logger.debug(
        "Ignoring GitHub pull_request opened event",
        number=event.data["number"],
        repo=event.data["repository"]["full_name"],
    )


@router.register("pull_request", action="synchronize")
async def handle_pr_sync(
    event: Event,
    logger: BoundLogger,
    arq_queue: ArqQueue,
    *args: Any,
    **kwargs: Any,
) -> None:
    """Handle the ``pull_request`` (synchronize) webhook event from GitHub by
    ignoring it.

    The event is received and logged, and nothing else: no task is queued
    and no GitHub API request is made. That is also why this handler is not
    gated by `filter_installation_owner`, whose installation lookup would be
    a GitHub API request made only to decide whether to ignore the event.

    .. warning::

       Do not use ``pull_request`` events to trigger notebook checks. GitHub
       delivers this event for pull requests from forks, with a head commit
       that anyone can author, so acting on it would execute untrusted
       notebooks with Times Square's credentials. Checks are triggered by
       ``check_suite`` events instead (see `handle_check_suite_request`),
       which GitHub only sends for commits pushed to the repository where
       the app is installed.

    Parameters
    ----------
    event
        The parsed event payload.
    logger
        The logger instance.
    arq_queue
        An arq queue client, which is not used.
    """
    logger.debug(
        "Ignoring GitHub pull_request synchronize event",
        number=event.data["number"],
        repo=event.data["repository"]["full_name"],
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

    This event and ``check_run`` (rerequested), handled by
    `handle_check_run_rerequested`, are the events that start a check of a
    commit's notebooks. GitHub sends ``check_suite`` (requested) only for
    commits pushed to the repository where the app is installed, never for a
    fork's commits, and re-requesting a check requires write access. The
    queued task does not rely on that alone: the check run service
    independently verifies that the commit is on a branch of the repository,
    which a fork's commits never are, and skips the check otherwise. That
    also skips a commit that is no longer on any branch, such as one whose
    branch was deleted after a squash or rebase merge.

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

    Like ``check_suite`` (see `handle_check_suite_request`), this event
    starts a check of a commit's notebooks: the queued task re-runs the
    check run, executing the notebooks for a notebook check. The check run
    service applies the same guard first, verifying that the commit is on a
    branch of the repository. A commit from a fork, or one that is no longer
    on any branch, such as one whose branch was deleted after a squash or
    rebase merge, has its check run concluded as skipped instead.

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
