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

from timessquare.config import config
from timessquare.domain.githubcheckout import (
    GitHubRepositoryCheckout,
    RepositoryNotebookModel,
)
from timessquare.domain.githubcheckrun import (
    GitHubConfigsCheck,
    NotebookExecutionsCheck,
)
from timessquare.exceptions import PageJinjaError

from ..domain.page import PageExecutionInfo, PageModel
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

    async def run_notebook_check_run(
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
        await self._delete_existing_pages(checkout, check_run.head_sha)

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
            try:
                page = await self._create_page(
                    checkout, notebook, check_run.head_sha
                )
                self._logger.debug(
                    "Created page for notebook check run",
                    path=notebook_ref.notebook_source_path,
                    page_name=page.name,
                    ipynb=page.ipynb,
                )
            except Exception as e:
                check.report_ipynb_format_error(
                    notebook_ref.notebook_source_path,
                    error=e,
                )
                continue
            try:
                page_execution_info = await self._execute_page(page)
            except PageJinjaError as e:
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

        try:
            await asyncio.wait_for(
                self._poll_noteburst_results(check, pending_pages),
                float(config.github_checkrun_timeout),
            )
        except TimeoutError:
            self._report_pr_notebook_timeout_errors(check, pending_pages)

        await check.submit_conclusion(github_client=self._github_client)

    async def _delete_existing_pages(
        self, checkout: GitHubRepositoryCheckout, commit_sha: str
    ) -> None:
        """Delete existing pages for this commit (if the check run was
        re-run).
        """
        for page in await self._page_service.get_pages_for_repo(
            owner=checkout.owner_name,
            name=checkout.name,
            commit=commit_sha,
        ):
            await self._page_service.soft_delete_page(page)
            self._logger.debug(
                "Deleted existing page for notebook check run",
                page_name=page.name,
            )

    async def _create_page(
        self,
        checkout: GitHubRepositoryCheckout,
        notebook: RepositoryNotebookModel,
        commit_sha: str,
    ) -> PageModel:
        """Create a page representing this notebook for this check run's
        commit SHA.
        """
        return await self._repo_service.create_page(
            checkout=checkout,
            notebook=notebook,
            commit_sha=commit_sha,
        )

    async def _execute_page(self, page: PageModel) -> PageExecutionInfo:
        """Execute a page with noteburst."""
        return await self._page_service.execute_page_with_defaults(
            page,
            enable_retry=False,  # fail quickly for CI
        )

    async def _poll_noteburst_results(
        self,
        check: NotebookExecutionsCheck,
        pending_pages: deque[PageExecutionInfo],
    ) -> None:
        """Poll noteburst for results from page executions until completion or
        timeout.
        """
        checked_page_count = 0
        while len(pending_pages) > 0:
            checked_page_count += 1

            # Pop a page from the queue to check. If the page isn't complete
            # we'll re-add it to the queue.
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
                pending_pages.append(page_execution)
                self._logger.debug(
                    "Continuing to check noteburst job",
                    path=page_execution.page.repository_source_path,
                )

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

    def _report_pr_notebook_timeout_errors(
        self,
        check: NotebookExecutionsCheck,
        pending_pages: deque[PageExecutionInfo],
    ) -> None:
        """Report timeout errors for all pending pages."""
        for page_execution in pending_pages:
            # Try to get the current job state including runtime
            try:
                if page_execution.noteburst_job is not None:
                    r = self._page_service.noteburst_api.get_job(
                        str(page_execution.noteburst_job.job_url)
                    )
                    job_result = r.data if r and hasattr(r, "data") else None
                else:
                    job_result = None
            except Exception:
                job_result = None

            check.report_noteburst_timeout(
                page_execution=page_execution,
                job_result=job_result,
                message=(
                    "Pull request timed out waiting for noteburst results "
                    f" (timeout: {config.github_checkrun_timeout}s)"
                ),
            )
