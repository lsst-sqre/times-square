from __future__ import annotations

from typing import Any, Dict

from timessquare.domain.githubwebhook import GitHubPushEventModel


async def repo_push(
    ctx: Dict[Any, Any], *, payload: GitHubPushEventModel
) -> str:
    """Process repo_push queue tasks, triggered by push events on GitHub
    repositories.
    """
    logger = ctx["logger"].bind(task="repo_push")
    logger.info("Running repo_push")
    return "FIXME"
