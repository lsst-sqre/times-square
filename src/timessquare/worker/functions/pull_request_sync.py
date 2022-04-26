from __future__ import annotations

from typing import Any, Dict

from timessquare.domain.githubwebhook import GitHubPullRequestModel


async def pull_request_sync(
    ctx: Dict[Any, Any],
    *,
    payload: GitHubPullRequestModel,
) -> str:
    """Process pull_requet_sync tasks, triggered by GitHub Pull Request
    events.

    This function runs a CI testing service for Times Square content and
    configuration.
    """
    logger = ctx["logger"].bind(task="pull_request_sync")
    logger.info("Running pull_request_sync")
    return "FIXME"
