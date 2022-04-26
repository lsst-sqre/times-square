from __future__ import annotations

from typing import Any, Dict

from timessquare.domain.githubwebhook import (
    AppInstallationRepoModel,
    GitHubAppInstallationRepositoriesEventModel,
)


async def repo_added(
    ctx: Dict[Any, Any],
    *,
    payload: GitHubAppInstallationRepositoriesEventModel,
    repo: AppInstallationRepoModel,
) -> str:
    """Process repo_added queue tasks, triggered by Times Square app
    installation events on GitHub.

    When Times Square is "installed" on a repository, Times Square displays
    its notebook content.
    """
    logger = ctx["logger"].bind(task="repo_added")
    logger.info("Running repo_added")
    return "FIXME"
