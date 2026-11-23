"""Service for GitHub Check runs."""

from __future__ import annotations

import asyncio
from collections import deque
from http import HTTPStatus

import httpx
from gidgethub import BadRequest, RedirectionException
from gidgethub.httpx import GitHubAPI
from httpx import AsyncClient
from pydantic import ValidationError
from safir.github.models import (
    GitHubBranchModel,
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
from ..storage.github.apimodels import (
    GitHubCheckSuiteHeadBranchModel,
    GitHubCommitComparisonModel,
)
from ..storage.github.retry import (
    TRANSIENT_GITHUB_ERRORS,
    retry_transient_github_errors,
)
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
        """Do nothing for a pull request event.

        This method is intentionally not implemented, and is only called by
        the stub ``pull_request_sync`` task. Do not run checks from pull
        request events: they are delivered for pull requests from forks,
        whose notebooks must never be executed. Checks are run by
        `initiate_check_runs` instead, in response to ``check_suite`` events.
        """

    async def initiate_check_runs(
        self, *, payload: GitHubCheckSuiteEventModel
    ) -> None:
        """Create a new GitHub check runs, given a new Check Suite.

        Notes
        -----
        NOTE: currently we're assuming that check suites are automatically
        created when created a check run. See
        https://docs.github.com/en/rest/checks/runs#create-a-check-run

        No check runs are created for a repository whose owner is not in
        ``TS_GITHUB_ORGS``, or for a commit that is not on a branch of the
        repository. That is a commit from a fork, but also a commit that was
        pushed to the repository and is no longer on any of its branches,
        such as the head of a pull request whose branch was deleted after a
        squash or rebase merge, or a commit that was force-pushed away.
        """
        if not await self._is_trusted_source(
            repo=payload.repository,
            head_sha=payload.check_suite.head_sha,
            check_suite_id=payload.check_suite.id,
        ):
            return

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

    async def _is_trusted_source(
        self,
        *,
        repo: GitHubRepositoryModel,
        head_sha: str,
        check_suite_id: int,
    ) -> bool:
        """Determine whether notebooks at a commit may be read and executed.

        Checking a commit means executing its notebooks with Times Square's
        credentials, so this is the gate that keeps content from forks out.
        GitHub serves a fork's commits through the base repository's API, so
        being able to read ``head_sha`` from ``repo`` proves nothing about
        where the commit was pushed. Instead, a commit is trusted only if it
        is on a branch of ``repo``, which only someone with write access to
        the repository can put it on, and only if the repository's owner is
        in ``TS_GITHUB_ORGS``.

        A commit that was pushed to ``repo`` but is no longer on any of its
        branches is not trusted either, because GitHub serves it just as it
        serves a fork's commit. Examples are the head of a pull request whose
        branch was deleted after a squash or rebase merge, and a commit that
        was force-pushed away. Checks of such commits are skipped.
        """
        if repo.owner.login not in config.accepted_github_orgs:
            self._logger.warning(
                "Skipping check for a repository in an unaccepted org",
                head_sha=head_sha,
                accepted_orgs=config.accepted_github_orgs,
            )
            return False

        if not await self._is_on_branch(
            repo=repo, head_sha=head_sha, check_suite_id=check_suite_id
        ):
            self._logger.warning(
                "Skipping check for a commit that is not on a branch of the "
                "repository, such as a commit from a fork or a commit that "
                "was deleted",
                head_sha=head_sha,
            )
            return False
        return True

    async def _is_on_branch(
        self,
        *,
        repo: GitHubRepositoryModel,
        head_sha: str,
        check_suite_id: int,
    ) -> bool:
        """Determine whether a commit is on a branch of the repository.

        The commit is on a branch if it is the head of any branch, or in the
        history of the check suite's head branch or of the default branch.
        Other branches' histories are not searched. A commit that none of
        these branches reach, such as one whose branch was deleted after a
        squash or rebase merge or one that was force-pushed away, is not on a
        branch.
        """
        # A check suite is normally requested for a commit that was just
        # pushed, which is the head of its branch.
        branches_where_head = await retry_transient_github_errors(
            lambda: self._github_client.getitem(
                "repos/{owner}/{repo}/commits/{sha}/branches-where-head",
                url_vars={
                    "owner": repo.owner.login,
                    "repo": repo.name,
                    "sha": head_sha,
                },
            )
        )
        if branches_where_head:
            return True

        # Otherwise the branch has moved on, as when a check is re-run on an
        # older commit, so look for the commit in the history of the branch
        # it was pushed to, or of the default branch in case that branch was
        # merged and deleted, or renamed.
        check_suite = GitHubCheckSuiteHeadBranchModel.model_validate(
            await retry_transient_github_errors(
                lambda: self._github_client.getitem(
                    "repos/{owner}/{repo}/check-suites/{check_suite_id}",
                    url_vars={
                        "owner": repo.owner.login,
                        "repo": repo.name,
                        "check_suite_id": str(check_suite_id),
                    },
                )
            )
        )
        candidates = dict.fromkeys(
            name
            for name in (check_suite.head_branch, repo.default_branch)
            if name
        )
        for branch_name in candidates:
            if await self._is_in_branch_history(
                repo=repo, head_sha=head_sha, branch_name=branch_name
            ):
                return True
        return False

    async def _is_in_branch_history(
        self, *, repo: GitHubRepositoryModel, head_sha: str, branch_name: str
    ) -> bool:
        """Determine whether a commit is the head of a branch, or one of its
        ancestors.
        """
        # The name is resolved strictly as a branch, and the commits are then
        # compared by SHA. A check suite for a fork's commit can name the
        # fork's branch, as GitHub Actions' check suites do, and the compare
        # API would resolve a name such as pull/3/head to the fork's commit
        # itself.
        try:
            data = await retry_transient_github_errors(
                lambda: self._github_client.getitem(
                    "repos/{owner}/{repo}/branches/{branch}",
                    url_vars={
                        "owner": repo.owner.login,
                        "repo": repo.name,
                        "branch": branch_name,
                    },
                )
            )
        except BadRequest as e:
            if e.status_code == HTTPStatus.NOT_FOUND:
                return False
            raise
        except RedirectionException:
            # GitHub redirects the old name of a renamed branch to its new
            # name. The redirect is not followed, so the guard only trusts
            # branches it looked up by name in this repository. A renamed
            # default branch is still checked under its current name.
            return False
        branch = GitHubBranchModel.model_validate(data)

        try:
            data = await retry_transient_github_errors(
                lambda: self._github_client.getitem(
                    "repos/{owner}/{repo}/compare/{base}...{head}",
                    url_vars={
                        "owner": repo.owner.login,
                        "repo": repo.name,
                        "base": branch.commit.sha,
                        "head": head_sha,
                    },
                )
            )
        except BadRequest as e:
            # GitHub reports a commit it cannot relate to the branch as not
            # found.
            if e.status_code == HTTPStatus.NOT_FOUND:
                return False
            raise
        return GitHubCommitComparisonModel.model_validate(data).head_is_in_base

    async def create_rerequested_check_run(
        self, *, payload: GitHubCheckRunEventModel
    ) -> None:
        """Run a GitHub check run that was rerequested.

        A check run for a repository whose owner is not in
        ``TS_GITHUB_ORGS``, or for a commit that is not on a branch of the
        repository, is concluded as skipped instead. That is a commit from a
        fork, but also a commit that was pushed to the repository and is no
        longer on any of its branches, such as the head of a pull request
        whose branch was deleted after a squash or rebase merge, or a commit
        that was force-pushed away.
        """
        if not await self._is_trusted_source(
            repo=payload.repository,
            head_sha=payload.check_run.head_sha,
            check_suite_id=payload.check_run.check_suite.id,
        ):
            # The check run already exists, so conclude it rather than
            # leaving it queued.
            await self._github_client.patch(
                str(payload.check_run.url),
                data={
                    "conclusion": GitHubCheckRunConclusion.neutral,
                    "output": {
                        "title": "Skipped",
                        "summary": (
                            "This commit is not on a branch of this "
                            "repository, so Times Square did not check it. "
                            "It may come from a fork, or the original commit "
                            "may have been deleted: its branch was deleted "
                            "after a squash or rebase merge, or it was "
                            "force-pushed away."
                        ),
                    },
                },
            )
            return

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

        try:
            checkout = await GitHubRepositoryCheckout.create(
                github_client=self._github_client,
                repo=repo,
                head_sha=check_run.head_sha,
            )
            await self._delete_existing_pages(checkout, check_run.head_sha)

            tree = await checkout.get_git_tree(self._github_client)
        except TRANSIENT_GITHUB_ERRORS:
            # A transient GitHub/network error outlasted the retry budget
            # while checking out the repository. Conclude the check with an
            # actionable failure rather than leaving it dangling in_progress.
            self._logger.warning(
                "Transient GitHub error during notebook check checkout"
            )
            await self._conclude_transient_checkout_error(check)
            return

        pending_pages: deque[PageExecutionInfo] = deque()
        for notebook_ref in tree.find_notebooks(checkout.settings):
            self._logger.debug(
                "Started notebook execution for notebook",
                path=notebook_ref.notebook_source_path,
            )
            try:
                notebook = await checkout.load_notebook(
                    notebook_ref=notebook_ref,
                    github_client=self._github_client,
                )
            except TRANSIENT_GITHUB_ERRORS:
                # A transient GitHub/network error outlasted the retry budget
                # while reading the notebook's git blobs. Conclude the check
                # rather than leaving it dangling in_progress.
                self._logger.warning(
                    "Transient GitHub error loading notebook for check",
                    path=notebook_ref.notebook_source_path,
                )
                await self._conclude_transient_checkout_error(
                    check, notebook_ref.notebook_source_path
                )
                return
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
            await self._report_pr_notebook_timeout_errors(check, pending_pages)

        await check.submit_conclusion(github_client=self._github_client)

    async def _conclude_transient_checkout_error(
        self, check: NotebookExecutionsCheck, path: str | None = None
    ) -> None:
        """Conclude a notebook check that hit an exhausted transient GitHub
        error, with an actionable, re-runnable failure annotation.

        Parameters
        ----------
        check
            The check run to conclude.
        path
            Repository path of the file the check was reading when the error
            occurred. If `None`, the annotation falls back to the
            repository's Times Square configuration file.
        """
        if path is None:
            check.report_transient_checkout_error()
        else:
            check.report_transient_checkout_error(path)
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

    async def _report_pr_notebook_timeout_errors(
        self,
        check: NotebookExecutionsCheck,
        pending_pages: deque[PageExecutionInfo],
    ) -> None:
        """Report timeout errors for all pending pages."""
        for page_execution in pending_pages:
            # Try to get the current job state including runtime. A failed or
            # missing status lookup yields job_result=None so the timeout is
            # still reported (without runtime).
            if page_execution.noteburst_job is not None:
                try:
                    r = await self._page_service.noteburst_api.get_job(
                        str(page_execution.noteburst_job.job_url)
                    )
                    job_result = r.data if r.status_code < 400 else None
                except httpx.HTTPError, ValidationError:
                    job_result = None
            else:
                job_result = None

            check.report_noteburst_timeout(
                page_execution=page_execution,
                job_result=job_result,
                message=(
                    "Pull request timed out waiting for noteburst results "
                    f" (timeout: {config.github_checkrun_timeout}s)"
                ),
            )
