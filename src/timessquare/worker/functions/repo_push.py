"""Worker function that processes a repo_push task."""

from __future__ import annotations

from typing import Any

from safir.dependencies.db_session import db_session_dependency
from safir.github.webhooks import GitHubPushEventModel
from safir.slack.blockkit import SlackCodeBlock, SlackMessage, SlackTextField

from timessquare.worker.servicefactory import create_github_repo_service


async def repo_push(
    ctx: dict[Any, Any], *, payload: GitHubPushEventModel
) -> str:
    """Process repo_push queue tasks, triggered by push events on GitHub
    repositories.
    """
    logger = ctx["logger"].bind(
        task="repo_push",
        github_owner=payload.repository.owner.login,
        github_repo=payload.repository.name,
    )
    logger.info("Running repo_push")

    try:
        async for db_session in db_session_dependency():
            github_repo_service = await create_github_repo_service(
                http_client=ctx["http_client"],
                logger=logger,
                installation_id=payload.installation.id,
                db_session=db_session,
            )
            async with db_session.begin():
                await github_repo_service.sync_from_push(payload)
    except Exception as e:
        if "slack" in ctx:
            await ctx["slack"].post(
                SlackMessage(
                    message="Times Square worker exception.",
                    fields=[
                        SlackTextField(heading="Task", text="repo_push"),
                        SlackTextField(
                            heading="Repository",
                            text=(
                                "https://github.com/"
                                f"{payload.repository.owner.login}/"
                                f"{payload.repository.name}"
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
