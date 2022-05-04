from __future__ import annotations

from typing import Any, Dict, Union

from safir.dependencies.db_session import db_session_dependency

from timessquare.domain.githubwebhook import (
    AppInstallationRepoModel,
    GitHubAppInstallationEventModel,
    GitHubAppInstallationRepositoriesEventModel,
)
from timessquare.worker.servicefactory import create_github_repo_service


async def repo_removed(
    ctx: Dict[Any, Any],
    *,
    payload: Union[
        GitHubAppInstallationRepositoriesEventModel,
        GitHubAppInstallationEventModel,
    ],
    repo: AppInstallationRepoModel,
) -> str:
    """Process repo_removed queue tasks, triggered by Times Square app
    installation events on GitHub.

    When the Times Square app is uninstalled from a repository, Times Square
    drops its content.
    """
    logger = ctx["logger"].bind(task="repo_removed")
    logger.info("Running repo_removed")

    async for db_session in db_session_dependency():
        github_repo_service = await create_github_repo_service(
            http_client=ctx["http_client"],
            logger=logger,
            installation_id=payload.installation.id,
            db_session=db_session,
        )
        async with db_session.begin():
            await github_repo_service.delete_repository(
                owner=repo.owner_name, repo_name=repo.name
            )
    return "FIXME"
