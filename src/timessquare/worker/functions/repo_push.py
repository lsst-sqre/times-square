from __future__ import annotations

from typing import Any, Dict

from safir.dependencies.db_session import db_session_dependency

from timessquare.domain.githubwebhook import GitHubPushEventModel
from timessquare.worker.servicefactory import create_github_repo_service


async def repo_push(
    ctx: Dict[Any, Any], *, payload: GitHubPushEventModel
) -> str:
    """Process repo_push queue tasks, triggered by push events on GitHub
    repositories.
    """
    logger = ctx["logger"].bind(task="repo_push")
    logger.info("Running repo_push")

    async for db_session in db_session_dependency():
        github_repo_service = await create_github_repo_service(
            http_client=ctx["http_client"],
            logger=logger,
            installation_id=payload.installation.id,
            db_session=db_session,
        )
        async with db_session.begin():
            await github_repo_service.sync_from_push(payload)
    return "FIXME"
