"""Worker function that processes a repo_renamed task."""

from __future__ import annotations

from typing import Any

from safir.dependencies.db_session import db_session_dependency
from safir.slack.blockkit import SlackCodeBlock, SlackMessage, SlackTextField

from timessquare.factory import WorkerFactory
from timessquare.storage.github.apimodels import (
    GitHubRepositoryRenamedEventModel,
)


async def repo_renamed(
    ctx: dict[Any, Any], *, payload: GitHubRepositoryRenamedEventModel
) -> str:
    """Process repo_renamed queue tasks, triggered by ``repository``
    (renamed) events on GitHub.

    A rename does not change the repository's content, so this task only
    flips the repository name stored on the repository's pages. No content is
    re-synced and no notebook is re-executed.
    """
    repository = payload.repository
    logger = ctx["logger"].bind(
        task="repo_renamed",
        github_owner=repository.owner.login,
        old_github_repo=payload.old_repo_name,
        github_repo=repository.name,
        github_repository_id=repository.id,
    )
    logger.info("Running repo_renamed")

    page_names: list[str] = []
    try:
        async for db_session in db_session_dependency():
            factory = WorkerFactory(
                logger=logger,
                session=db_session,
                process_context=ctx["process_context"],
            )
            page_service = factory.create_page_service()
            async with db_session.begin():
                page_names = await page_service.rename_github_repository(
                    owner=repository.owner.login,
                    old_name=payload.old_repo_name,
                    new_name=repository.name,
                    repository_id=repository.id,
                )
            logger.info(
                "Renamed GitHub repository pages",
                page_count=len(page_names),
                page_names=page_names,
            )
    except Exception as e:
        if "slack" in ctx:
            await ctx["slack"].post(
                SlackMessage(
                    message="Times Square worker exception.",
                    fields=[
                        SlackTextField(heading="Task", text="repo_renamed"),
                        SlackTextField(
                            heading="Repository",
                            text=(
                                "https://github.com/"
                                f"{repository.owner.login}/{repository.name}"
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
    return f"Renamed {len(page_names)} pages"
