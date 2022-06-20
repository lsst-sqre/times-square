from __future__ import annotations

from typing import Any, Dict

from timessquare.domain.githubwebhook import GitHubCheckRunEventModel


async def compute_check_run(
    ctx: Dict[Any, Any], *, payload: GitHubCheckRunEventModel
) -> str:
    """Process compute queue tasks, triggered by check_run requested
    events on GitHub repositories.
    """
    logger = ctx["logger"].bind(
        task="compute_check_run",
        github_owner=payload.repository.owner.login,
        github_repo=payload.repository.name,
    )
    logger.info("Running compute_check_run", payload=payload.dict())
    logger.info("Skipping compute_check_run (not configured)")

    return "done"
