"""Worker cron that reconciles stored GitHub names against GitHub."""

from __future__ import annotations

from typing import Any

from safir.dependencies.db_session import db_session_dependency

from timessquare.config import config
from timessquare.factory import WorkerFactory
from timessquare.services.githubnamereconcile import (
    GitHubNameReconciliationReport,
)


async def reconcile_github_names(ctx: dict[Any, Any]) -> str:
    """Heal drift between the GitHub owner and repository names stored on
    pages and the names GitHub currently answers with.

    Renames and transfers normally reach Times Square as webhooks, and every
    repository sync refreshes the stored names. Neither covers a rename that
    happens while Times Square is down or whose webhook delivery fails, so
    this daily pass re-reads every repository behind a live page by its stable
    numeric ID and rewrites the stored names when they disagree. Like the
    rename webhooks it is a pure name flip: nothing is re-synced from GitHub
    and no notebook is re-executed.

    Repositories the GitHub App cannot read are logged and left alone. This
    task never deletes pages, because a deleted repository is indistinguishable
    here from an app whose installation token could not be minted.
    """
    logger = ctx["logger"].bind(task="reconcile_github_names")

    if not config.enable_github_app:
        logger.info(
            "GitHub App is not enabled; skipping GitHub name reconciliation"
        )
        return "GitHub App is not enabled"

    logger.info("Running reconcile_github_names")

    report: GitHubNameReconciliationReport | None = None
    async for db_session in db_session_dependency():
        factory = WorkerFactory(
            logger=logger,
            session=db_session,
            process_context=ctx["process_context"],
        )
        reconciliation_service = (
            factory.create_github_name_reconciliation_service()
        )
        # One transaction for the whole pass, so a failure part-way through
        # leaves no half-healed repository behind. The service makes all of
        # its GitHub round trips before its first write, so the row locks the
        # heals take are held for one short burst at the end of the run
        # rather than for the length of the run.
        async with db_session.begin():
            report = await reconciliation_service.reconcile()

    if report is None:  # pragma: no cover
        raise RuntimeError("No database session")

    logger.info(
        "Reconciled GitHub repository names",
        repositories_checked=report.repositories_checked,
        repositories_healed=report.repositories_healed,
        repositories_skipped=report.repositories_skipped,
        repositories_failed=report.repositories_failed,
        pages_updated=report.pages_updated,
    )
    return (
        f"Checked {report.repositories_checked} repositories; "
        f"healed {report.repositories_healed}, "
        f"failed {report.repositories_failed}"
    )
