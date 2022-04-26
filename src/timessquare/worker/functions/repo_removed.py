from __future__ import annotations

from typing import Any, Dict

from timessquare.domain.githubwebhook import (
    AppInstallationRepoModel,
    GitHubAppInstallationRepositoriesEventModel,
)


async def repo_removed(
    ctx: Dict[Any, Any],
    *,
    payload: GitHubAppInstallationRepositoriesEventModel,
    repo: AppInstallationRepoModel,
) -> str:
    """Process repo_removed queue tasks, triggered by Times Square app
    installation events on GitHub.

    When the Times Square app is uninstalled from a repository, Times Square
    drops its content.
    """
    logger = ctx["logger"].bind(task="repo_removed")
    logger.info("Running repo_removed")
    return "FIXME"
