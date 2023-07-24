"""Worker function that creates a GitHub check_run."""

from __future__ import annotations

from typing import Any

from safir.dependencies.db_session import db_session_dependency
from safir.github.webhooks import GitHubCheckSuiteEventModel

from timessquare.worker.servicefactory import create_github_repo_service


async def create_check_run(
    ctx: dict[Any, Any], *, payload: GitHubCheckSuiteEventModel
) -> str:
    """Process create_check_run queue tasks, triggered by check_suite created
    events on GitHub repositories.
    """
    logger = ctx["logger"].bind(
        task="create_check_run",
        github_owner=payload.repository.owner.login,
        github_repo=payload.repository.name,
    )
    logger.info("Running create_check_run", payload=payload.dict())

    async for db_session in db_session_dependency():
        github_repo_service = await create_github_repo_service(
            http_client=ctx["http_client"],
            logger=logger,
            installation_id=payload.installation.id,
            db_session=db_session,
        )
        async with db_session.begin():
            await github_repo_service.initiate_check_runs(payload=payload)
    return "done"
