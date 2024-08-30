"""Worker function for computing a GitHub check_run."""

from __future__ import annotations

from typing import Any

from safir.github.webhooks import GitHubCheckRunEventModel


async def compute_check_run(
    ctx: dict[Any, Any], *, payload: GitHubCheckRunEventModel
) -> str:
    """Process compute queue tasks, triggered by check_run requested
    events on GitHub repositories.
    """
    logger = ctx["logger"].bind(
        task="compute_check_run",
        github_owner=payload.repository.owner.login,
        github_repo=payload.repository.name,
    )
    logger.info(
        "Running compute_check_run", payload=payload.model_dump(mode="json")
    )
    logger.info("Skipping compute_check_run (not configured)")

    return "done"
