"""Worker function that processes a repo_transferred task."""

from __future__ import annotations

from typing import Any

from safir.dependencies.db_session import db_session_dependency
from safir.slack.blockkit import SlackCodeBlock, SlackMessage, SlackTextField
from structlog.stdlib import BoundLogger

from timessquare.config import config
from timessquare.factory import WorkerFactory
from timessquare.services.page import PageService
from timessquare.storage.github.apimodels import (
    GitHubRepositoryTransferredEventModel,
)


async def repo_transferred(
    ctx: dict[Any, Any], *, payload: GitHubRepositoryTransferredEventModel
) -> str:
    """Process repo_transferred queue tasks, triggered by ``repository``
    (transferred) events on GitHub.

    A transfer does not change the repository's content, so if the new owner
    is one Times Square syncs from, this only rewrites the owner and
    repository name stored on the repository's pages. If the new owner is not
    in `~timessquare.config.Config.accepted_github_orgs`, the repository has
    left Times Square's remit and its pages are soft-deleted, exactly as if
    the app had been uninstalled from it.

    In both cases the repository's pages are matched on GitHub's stable
    numeric repository ID alone. A transfer frees the repository's old
    ``owner/repo`` name pair on GitHub the moment it happens, so matching on
    those names could catch the pages of whatever repository claims the name
    next; pages that predate ID capture are healed by the next sync instead.
    """
    repository = payload.repository
    new_owner = repository.owner.login
    is_accepted = new_owner in config.accepted_github_orgs
    logger = ctx["logger"].bind(
        task="repo_transferred",
        old_github_owner=payload.old_owner_login,
        github_owner=new_owner,
        github_repo=repository.name,
        github_repository_id=repository.id,
        github_owner_accepted=is_accepted,
    )
    logger.info("Running repo_transferred")

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
                if is_accepted:
                    page_names = await _transfer_pages(
                        page_service, payload=payload
                    )
                else:
                    page_names = await _retire_pages(
                        page_service, payload=payload, logger=logger
                    )
            logger.info(
                "Transferred GitHub repository pages"
                if is_accepted
                else "Soft-deleted transferred-away GitHub repository pages",
                page_count=len(page_names),
                page_names=page_names,
            )
    except Exception as e:
        if "slack" in ctx:
            await ctx["slack"].post(
                SlackMessage(
                    message="Times Square worker exception.",
                    fields=[
                        SlackTextField(
                            heading="Task", text="repo_transferred"
                        ),
                        SlackTextField(
                            heading="Repository",
                            text=(
                                f"https://github.com/{new_owner}/"
                                f"{repository.name}"
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
    verb = "Transferred" if is_accepted else "Soft-deleted"
    return f"{verb} {len(page_names)} pages"


async def _transfer_pages(
    page_service: PageService,
    *,
    payload: GitHubRepositoryTransferredEventModel,
) -> list[str]:
    """Flip the stored identity of a repository transferred to an owner
    Times Square syncs from.
    """
    repository = payload.repository
    return await page_service.transfer_github_repository(
        repository_id=repository.id,
        new_owner=repository.owner.login,
        new_owner_id=repository.owner.id,
        new_name=repository.name,
    )


async def _retire_pages(
    page_service: PageService,
    *,
    payload: GitHubRepositoryTransferredEventModel,
    logger: BoundLogger,
) -> list[str]:
    """Soft-delete the pages of a repository transferred to an owner Times
    Square does not sync from.
    """
    logger.warning(
        "GitHub repository transferred to an unaccepted owner; "
        "soft-deleting its pages",
        accepted_orgs=config.accepted_github_orgs,
    )
    return await page_service.soft_delete_pages_for_repository_id(
        payload.repository.id
    )
