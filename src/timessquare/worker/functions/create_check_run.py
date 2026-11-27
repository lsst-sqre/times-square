"""Worker function that creates a GitHub check_run."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

from arq import Retry
from safir.dependencies.db_session import db_session_dependency
from safir.slack.blockkit import SlackCodeBlock, SlackMessage, SlackTextField

from timessquare.factory import WorkerFactory
from timessquare.services.githubcheckrun import CheckSuiteOutcome
from timessquare.storage.github.apimodels import (
    GitHubCheckSuiteEventWithNullableBranchModel,
)

__all__ = [
    "NOT_VISIBLE_RETRIES",
    "NOT_VISIBLE_RETRY_DELAY",
    "create_check_run",
]

NOT_VISIBLE_RETRIES = 3
"""How many times a check suite is retried while GitHub may not show its
commit on its branch yet, before it is skipped.
"""

NOT_VISIBLE_RETRY_DELAY = timedelta(seconds=5)
"""How long to wait before the first retry of a check suite whose commit
GitHub may not show on its branch yet.

Each later retry waits this much longer than the one before, so the
`NOT_VISIBLE_RETRIES` retries span 30 seconds.
"""


async def create_check_run(
    ctx: dict[Any, Any],
    *,
    payload: GitHubCheckSuiteEventWithNullableBranchModel,
) -> str:
    """Process create_check_run queue tasks, triggered by check_suite created
    events on GitHub repositories.

    A requested check suite whose commit GitHub may not show on its branch
    yet, as can happen for a moment after a push, is deferred with
    `arq.Retry` up to `NOT_VISIBLE_RETRIES` times before it is skipped,
    without posting a Slack alert. Each deferral and the final outcome are
    logged with the attempt number.
    """
    attempt = ctx["job_try"]
    logger = ctx["logger"].bind(
        task="create_check_run",
        github_owner=payload.repository.owner.login,
        github_repo=payload.repository.name,
        attempt=attempt,
    )
    logger.info(
        "Running create_check_run", payload=payload.model_dump(mode="json")
    )

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
                outcome = await github_repo_service.initiate_check_runs(
                    payload=payload, may_retry=attempt <= NOT_VISIBLE_RETRIES
                )
    except Exception as e:
        if "slack" in ctx:
            await ctx["slack"].post(
                SlackMessage(
                    message="Times Square worker exception.",
                    fields=[
                        SlackTextField(
                            heading="Task", text="create_check_run"
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

    # Raised outside the try block, so that the deferral is not reported to
    # Slack as a worker exception.
    if outcome is CheckSuiteOutcome.not_yet_visible:
        defer = NOT_VISIBLE_RETRY_DELAY * attempt
        logger.info(
            "Deferring check suite until GitHub shows its commit on a branch",
            defer_seconds=defer.total_seconds(),
        )
        raise Retry(defer=defer)

    logger.info("Finished create_check_run", outcome=outcome.value)
    return "done"
