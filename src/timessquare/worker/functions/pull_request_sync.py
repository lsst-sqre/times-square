from __future__ import annotations

from typing import Any, Dict

from safir.dependencies.db_session import db_session_dependency

from timessquare.domain.githubwebhook import GitHubPullRequestEventModel
from timessquare.worker.servicefactory import create_github_repo_service


async def pull_request_sync(
    ctx: Dict[Any, Any],
    *,
    payload: GitHubPullRequestEventModel,
) -> str:
    """Process pull_requet_sync tasks, triggered by GitHub Pull Request
    events.

    This function runs a CI testing service for Times Square content and
    configuration.
    """
    logger = ctx["logger"].bind(
        task="pull_request_sync",
        github_owner=payload.repository.owner.login,
        github_repo=payload.repository.name,
    )
    logger.info("Running pull_request_sync")

    async for db_session in db_session_dependency():
        github_repo_service = await create_github_repo_service(
            http_client=ctx["http_client"],
            logger=logger,
            installation_id=payload.installation.id,
            db_session=db_session,
        )
        async with db_session.begin():
            await github_repo_service.check_pull_request(
                pr_payload=payload.pull_request
            )
    return "FIXME"
