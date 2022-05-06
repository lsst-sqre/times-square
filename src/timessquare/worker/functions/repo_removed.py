from __future__ import annotations

from typing import Any, Dict, Union

from safir.dependencies.db_session import db_session_dependency

from timessquare.domain.githubwebhook import (
    AppInstallationRepoModel,
    GitHubAppInstallationEventModel,
    GitHubAppInstallationRepositoriesEventModel,
)
from timessquare.worker.servicefactory import create_page_service


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
    logger = ctx["logger"].bind(
        task="repo_removed",
        github_owner=repo.owner_name,
        github_repo=repo.name,
    )
    logger.info("Running repo_removed")

    async for db_session in db_session_dependency():
        page_service = await create_page_service(
            http_client=ctx["http_client"],
            logger=logger,
            db_session=db_session,
        )
        async with db_session.begin():
            await page_service.soft_delete_pages_for_repo(
                owner=repo.owner_name, name=repo.name
            )
    return "FIXME"
