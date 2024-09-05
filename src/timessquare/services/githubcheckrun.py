"""Service for GitHub Check runs."""

from __future__ import annotations

import asyncio
from collections import deque

from gidgethub.httpx import GitHubAPI
from httpx import AsyncClient
from safir.github.models import (
    GitHubCheckRunConclusion,
    GitHubCheckRunModel,
    GitHubPullRequestModel,
    GitHubRepositoryModel,
)
from safir.github.webhooks import (
    GitHubCheckRunEventModel,
    GitHubCheckSuiteEventModel,
)
from structlog.stdlib import BoundLogger

from timessquare.domain.githubcheckout import GitHubRepositoryCheckout
from timessquare.domain.githubcheckrun import (
    GitHubConfigsCheck,
    NotebookExecutionsCheck,
)
from timessquare.exceptions import PageJinjaError

from ..domain.page import PageExecutionInfo
from ..storage.noteburst import NoteburstJobStatus
from .githubrepo import GitHubRepoService
from .page import PageService

__all__ = ["GitHubCheckRunService"]


class GitHubCheckRunService:
    """Service for GitHub Check runs.

    This service is responsible for creating and updating GitHub Check runs. It
    should only be run from arq background tasks, triggered by GitHub webhooks.
    """

    def __init__(
        self,
        http_client: AsyncClient,
        github_client: GitHubAPI,
        repo_service: GitHubRepoService,
        page_service: PageService,
        logger: BoundLogger,
    ) -> None:
        self._http_client = http_client
        self._github_client = github_client
        self._repo_service = repo_service
        self._page_service = page_service
        self._logger = logger

    async def check_pull_request(
        self, pr_payload: GitHubPullRequestModel
    ) -> None:
        """Run a check on a pull request."""
        # Called by the pull_request_sync function
        # This isn't run. Instead we use the initial_check_run method
        # called by the create_check_run async function.

    async def initiate_check_runs(
        self, *, payload: GitHubCheckSuiteEventModel
    ) -> None:
        """Create a new GitHub check runs, given a new Check Suite.

        Notes
        -----
        NOTE: currently we're assuming that check suites are automatically
        created when created a check run. See
        https://docs.github.com/en/rest/checks/runs#create-a-check-run
        """
        # Run the configurations check
        config_check = await GitHubConfigsCheck.create_check_run_and_validate(
            github_client=self._github_client,
            repo=payload.repository,
            head_sha=payload.check_suite.head_sha,
        )
        await config_check.submit_conclusion(github_client=self._github_client)

        repo = payload.repository
        data = await self._github_client.post(
            "repos/{owner}/{repo}/check-runs",
            url_vars={"owner": repo.owner.login, "repo": repo.name},
            data={
                "name": NotebookExecutionsCheck.title,
                "head_sha": payload.check_suite.head_sha,
                "external_id": NotebookExecutionsCheck.external_id,
            },
        )
        check_run = GitHubCheckRunModel.model_validate(data)
        if config_check.conclusion == GitHubCheckRunConclusion.success:
            await self.run_notebook_check_run(
                check_run=check_run,
                repo=payload.repository,
            )
        else:
            # Set the notebook check run to "neutral" indicating that we're
            # skipping this check.
            await self._github_client.patch(
                str(check_run.url),
                data={"conclusion": GitHubCheckRunConclusion.neutral},
            )

    async def create_rerequested_check_run(
        self, *, payload: GitHubCheckRunEventModel
    ) -> None:
        """Run a GitHub check run that was rerequested."""
        external_id = payload.check_run.external_id
        if external_id == GitHubConfigsCheck.external_id:
            config_check = await GitHubConfigsCheck.validate_repo(
                github_client=self._github_client,
                repo=payload.repository,
                head_sha=payload.check_run.head_sha,
                check_run=payload.check_run,
            )
            await config_check.submit_conclusion(
                github_client=self._github_client
            )
        elif external_id == NotebookExecutionsCheck.external_id:
            await self.run_notebook_check_run(
                check_run=payload.check_run,
                repo=payload.repository,
            )

    async def run_notebook_check_run(  # noqa: C901 PLR0912 PLR0915
        self, *, check_run: GitHubCheckRunModel, repo: GitHubRepositoryModel
    ) -> None:
        """Run the notebook execution check.

        This check actually creates/updates Page resources, hence it is run
        at the service layer, rather than in a domain model.
        """
        check = NotebookExecutionsCheck(check_run, repo)
        await check.submit_in_progress(self._github_client)
        self._logger.debug("Notebook executions check in progress")

        checkout = await GitHubRepositoryCheckout.create(
            github_client=self._github_client,
            repo=repo,
            head_sha=check_run.head_sha,
        )

        # Look for any existing pages for this repo's SHA. If they already
        # exist it indicates the check is being re-run, so we'll delete those
        # old pages for this commit
        for page in await self._page_service.get_pages_for_repo(
            owner=checkout.owner_name,
            name=checkout.name,
            commit=check_run.head_sha,
        ):
            await self._page_service.soft_delete_page(page)
            self._logger.debug(
                "Deleted existing page for notebook check run",
                page_name=page.name,
            )

        tree = await checkout.get_git_tree(self._github_client)
        pending_pages: deque[PageExecutionInfo] = deque()
        for notebook_ref in tree.find_notebooks(checkout.settings):
            self._logger.debug(
                "Started notebook execution for notebook",
                path=notebook_ref.notebook_source_path,
            )
            notebook = await checkout.load_notebook(
                notebook_ref=notebook_ref, github_client=self._github_client
            )
            if notebook.sidecar.enabled is False:
                self._logger.debug(
                    "Skipping notebook execution check for disabled notebook",
                    path=notebook_ref.notebook_source_path,
                )
                continue
            page = await self._repo_service.create_page(
                checkout=checkout,
                notebook=notebook,
                commit_sha=check_run.head_sha,
            )
            try:
                page_execution_info = (
                    await self._page_service.execute_page_with_defaults(
                        page,
                        enable_retry=False,  # fail quickly for CI
                    )
                )
            except PageJinjaError as e:
                # Error rendering out the notebook's Jinja. Report in the
                # and move on to the next notebook
                check.report_jinja_error(page, e)
                continue

            if page_execution_info.noteburst_error_message is not None:
                self._logger.debug(
                    "Got immediate noteburst error",
                    path=notebook_ref.notebook_source_path,
                    error_message=page_execution_info.noteburst_error_message,
                )
                check.report_noteburst_failure(page_execution_info)
            else:
                pending_pages.append(page_execution_info)
                self._logger.debug(
                    "Noteburst result is pending",
                    path=notebook_ref.notebook_source_path,
                )

        await asyncio.sleep(5.0)  # pause for noteburst to work

        # Poll for noteburst results
        checked_page_count = 0
        while len(pending_pages) > 0:
            checked_page_count += 1
            page_execution = pending_pages.popleft()
            self._logger.debug(
                "Polling noteburst job status",
                path=page_execution.page.repository_source_path,
            )
            if page_execution.noteburst_job is None:
                raise RuntimeError("Noteburst job is None")
            r = await self._page_service.noteburst_api.get_job(
                str(page_execution.noteburst_job.job_url)
            )
            if r.status_code >= 400:
                # This is actually an issue with the noteburst service
                # rather the notebook; consider adding that nuance to the
                # GitHub Check
                check.report_noteburst_failure(page_execution)
                continue

            job = r.data
            if job is None:
                raise RuntimeError("Noteburst job is None")
            if job.status == NoteburstJobStatus.complete:
                self._logger.debug(
                    "Noteburst job is complete",
                    path=page_execution.page.repository_source_path,
                )
                check.report_noteburst_completion(
                    page_execution=page_execution, job_result=job
                )
            else:
                # thow it back on the queue
                self._logger.debug(
                    "Continuing to check noteburst job",
                    path=page_execution.page.repository_source_path,
                )
                pending_pages.append(page_execution)

            # Once we've gone through all the pages once, pause
            if checked_page_count >= len(pending_pages):
                self._logger.debug(
                    "Pause polling of noteburst jobs",
                    checked_page_count=checked_page_count,
                )
                await asyncio.sleep(2)
                self._logger.debug(
                    "Pause finished",
                    checked_page_count=checked_page_count,
                )
                checked_page_count = 0
            else:
                self._logger.debug(
                    "Continuing to poll noteburst jobs",
                    pending_count=len(pending_pages),
                    checked_page_count=checked_page_count,
                )

        await check.submit_conclusion(github_client=self._github_client)
