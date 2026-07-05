"""Worker task to process a pull request."""

from __future__ import annotations

from typing import Any

from safir.dependencies.db_session import db_session_dependency
from safir.github.webhooks import GitHubPullRequestEventModel
from safir.slack.blockkit import SlackCodeBlock, SlackMessage, SlackTextField

from timessquare.factory import WorkerFactory


async def pull_request_sync(
    ctx: dict[Any, Any],
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

    try:
        async for db_session in db_session_dependency():
            factory = WorkerFactory(
                logger=logger,
                session=db_session,
                process_context=ctx["process_context"],
            )
            github_repo_service = (
                await factory.create_github_check_run_service(
                    installation_id=payload.installation.id
                )
            )
            async with db_session.begin():
                await github_repo_service.check_pull_request(
                    pr_payload=payload.pull_request
                )
    except Exception as e:
        if "slack" in ctx:
            await ctx["slack"].post(
                SlackMessage(
                    message="Times Square worker exception.",
                    fields=[
                        SlackTextField(
                            heading="Task", text="pull_request_sync"
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
    return "FIXME"
