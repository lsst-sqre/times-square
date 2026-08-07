"""Worker function that processes an org_renamed task."""

from __future__ import annotations

from typing import Any

from safir.dependencies.db_session import db_session_dependency
from safir.slack.blockkit import SlackCodeBlock, SlackMessage, SlackTextField

from timessquare.config import config
from timessquare.factory import WorkerFactory
from timessquare.storage.github.apimodels import (
    GitHubOrganizationRenamedEventModel,
)


async def org_renamed(
    ctx: dict[Any, Any], *, payload: GitHubOrganizationRenamedEventModel
) -> str:
    """Process org_renamed queue tasks, triggered by ``organization``
    (renamed) events on GitHub.

    Renaming an organization does not change any repository's content, so this
    task only flips the owner login stored on the organization's pages. No
    content is re-synced and no notebook is re-executed.

    Pages are matched on GitHub's stable numeric owner ID, with a fallback to
    the old login restricted to pages that have no owner ID recorded yet.
    """
    old_login = payload.old_login
    new_login = payload.new_login
    logger = ctx["logger"].bind(
        task="org_renamed",
        old_github_owner=old_login,
        github_owner=new_login,
        github_owner_id=payload.organization.id,
    )
    logger.info("Running org_renamed")

    if new_login not in config.accepted_github_orgs:
        # TS_GITHUB_ORGS is keyed on login names, so until an operator updates
        # it the organization's own future events are dropped by the webhook
        # handlers' allowlist gate.
        logger.warning(
            "GitHub organization renamed; update TS_GITHUB_ORGS to its new "
            "login or Times Square will ignore its future events",
            accepted_orgs=config.accepted_github_orgs,
        )

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
                page_names = await page_service.rename_github_owner(
                    old_login=old_login,
                    new_login=new_login,
                    owner_id=payload.organization.id,
                )
            logger.info(
                "Renamed GitHub organization pages",
                page_count=len(page_names),
                page_names=page_names,
            )
    except Exception as e:
        if "slack" in ctx:
            await ctx["slack"].post(
                SlackMessage(
                    message="Times Square worker exception.",
                    fields=[
                        SlackTextField(heading="Task", text="org_renamed"),
                        SlackTextField(
                            heading="Organization",
                            text=f"https://github.com/{new_login}",
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
