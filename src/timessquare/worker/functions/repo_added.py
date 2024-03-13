"""Worker function to process repo_added queue tasks."""

from __future__ import annotations

from typing import Any

from safir.dependencies.db_session import db_session_dependency
from safir.github.webhooks import (
    GitHubAppInstallationEventModel,
    GitHubAppInstallationEventRepoModel,
    GitHubAppInstallationRepositoriesEventModel,
)
from safir.slack.blockkit import SlackCodeBlock, SlackMessage, SlackTextField

from timessquare.worker.servicefactory import create_github_repo_service


async def repo_added(
    ctx: dict[Any, Any],
    *,
    payload: GitHubAppInstallationRepositoriesEventModel
    | GitHubAppInstallationEventModel,
    repo: GitHubAppInstallationEventRepoModel,
) -> str:
    """Process repo_added queue tasks, triggered by Times Square app
    installation events on GitHub.

    When Times Square is "installed" on a repository, Times Square displays
    its notebook content.
    """
    logger = ctx["logger"].bind(
        task="repo_added", github_owner=repo.owner_name, github_repo=repo.name
    )
    logger.info("Running repo_added")

    try:
        async for db_session in db_session_dependency():
            github_repo_service = await create_github_repo_service(
                http_client=ctx["http_client"],
                logger=logger,
                installation_id=payload.installation.id,
                db_session=db_session,
            )
            async with db_session.begin():
                await github_repo_service.sync_from_repo_installation(
                    owner=repo.owner_name,
                    repo_name=repo.name,
                )
    except Exception as e:
        if "slack" in ctx:
            await ctx["slack"].post(
                SlackMessage(
                    message="Times Square worker exception.",
                    fields=[
                        SlackTextField(heading="Task", text="repo_added"),
                        SlackTextField(
                            heading="Repository",
                            text=(
                                f"https://github.com/{repo.owner_name}/"
                                f"{repo.name}"
                            ),
                        ),
                    ],
                    blocks=[
                        SlackCodeBlock(
                            heading="Exception",
                            code=str(e),
                        )
                    ],
                )
            )
        raise

    return "FIXME"
