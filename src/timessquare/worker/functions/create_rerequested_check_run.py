"""Worker function that creates a re-requested GitHub check_run."""

from __future__ import annotations

from typing import Any

from safir.dependencies.db_session import db_session_dependency
from safir.github.webhooks import GitHubCheckRunEventModel
from safir.slack.blockkit import SlackCodeBlock, SlackMessage, SlackTextField

from timessquare.worker.servicefactory import create_github_repo_service


async def create_rerequested_check_run(
    ctx: dict[Any, Any], *, payload: GitHubCheckRunEventModel
) -> str:
    """Process create_rerequested_check_run queue tasks, triggered by
    check_run rerequested events on GitHub repositories.
    """
    logger = ctx["logger"].bind(
        task="create_rerequested_check_run",
        github_owner=payload.repository.owner.login,
        github_repo=payload.repository.name,
    )
    logger.info(
        "Running create_rerequested_check_run",
        payload=payload.model_dump(mode="json"),
    )

    try:
        async for db_session in db_session_dependency():
            github_repo_service = await create_github_repo_service(
                http_client=ctx["http_client"],
                logger=logger,
                installation_id=payload.installation.id,
                db_session=db_session,
            )
            async with db_session.begin():
                await github_repo_service.create_rerequested_check_run(
                    payload=payload
                )
    except Exception as e:
        if "slack" in ctx:
            await ctx["slack"].post(
                SlackMessage(
                    message="Times Square worker exception.",
                    fields=[
                        SlackTextField(
                            heading="Task", text="create_rerequested_check_run"
                        ),
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

    return "done"
