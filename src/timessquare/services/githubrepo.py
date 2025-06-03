"""Service layer related to GitHub-backed content.

This service works with the githubcheckout domain models and collaborates
with the Page service for managing page domain models.
"""

from __future__ import annotations

from pathlib import PurePosixPath

from gidgethub.httpx import GitHubAPI
from httpx import AsyncClient
from safir.github import GitHubAppClientFactory
from safir.github.models import (
    GitHubBlobModel,
    GitHubBranchModel,
    GitHubCheckRunModel,
    GitHubPullRequestModel,
    GitHubRepositoryModel,
)
from safir.github.webhooks import GitHubPushEventModel
from safir.slack.blockkit import SlackException
from structlog.stdlib import BoundLogger

from timessquare.config import config
from timessquare.domain.githubcheckout import (
    GitHubRepositoryCheckout,
    RepositoryNotebookModel,
)
from timessquare.storage.github.settingsfiles import RepositorySettingsFile

from ..domain.page import PageModel
from .page import PageService


class GitHubRepoService:
    """A service manager for GitHub-backed pages.

    Parameters
    ----------
    http_client : `AsyncClient`
        An httpx client.
    github_client : `GitHubAPI`
        A GidgetHub API client that is authenticated as a GitHub app
        installation.
    page_service : `PageService`
        The Page service. This GitHubRepoService acts as a layer on top of
        the regular page service to handle domain models from the github
        domain.
    logger : `BoundLogger`
        A logger, ideally with request/worker job context already bound.
    """

    def __init__(
        self,
        http_client: AsyncClient,
        github_client: GitHubAPI,
        page_service: PageService,
        logger: BoundLogger,
    ) -> None:
        self._http_client = http_client
        self._github_client = github_client
        self._page_service = page_service
        self._logger = logger

    @classmethod
    async def create_for_repo(
        cls,
        *,
        owner: str,
        repo: str,
        http_client: AsyncClient,
        page_service: PageService,
        logger: BoundLogger,
    ) -> GitHubRepoService:
        """Create a github repo service for a specific repository (requires
        that the Times Square GitHub App is installed for that repository).

        Parameters
        ----------
        owner : `str`
            The GitHub repo's owner.
        repo : `str`
            The GitHub repo's name.
        http_client : `AsyncClient`
            An httpx client.
        github_client : `GitHubAPI`
            A GidgetHub API client that is authenticated as a GitHub app
            installation.
        page_service : `PageService`
            The Page service. This GitHubRepoService acts as a layer on top of
            the regular page service to handle domain models from the github
            domain.
        logger : `BoundLogger`
            A logger, ideally with request/worker job context already bound.
        """
        if not config.github_app_id or not config.github_app_private_key:
            raise SlackException(
                "github_app_id and github_app_private_key must be set to "
                "create the GitHubRepoService."
            )
        if owner not in config.accepted_github_orgs:
            raise SlackException(
                f"GitHub organization {owner} is not in the list of accepted "
                f"organizations: {config.accepted_github_orgs}"
            )
        github_client_factory = GitHubAppClientFactory(
            http_client=http_client,
            id=config.github_app_id,
            key=config.github_app_private_key,
            name="lsst-sqre/times-square",
        )
        installation_client = (
            await github_client_factory.create_installation_client_for_repo(
                owner=owner, repo=repo
            )
        )
        return cls(
            http_client=http_client,
            github_client=installation_client,
            page_service=page_service,
            logger=logger,
        )

    @property
    def page_service(self) -> PageService:
        """The page service used by the repo service."""
        return self._page_service

    async def sync_from_repo_installation(
        self,
        owner: str,
        repo_name: str,
    ) -> None:
        """Synchronize a new repository that was just installed."""
        repo = await self.request_github_repository(owner, repo_name)
        branch = await self.request_github_branch(
            url_template=repo.branches_url, branch=repo.default_branch
        )
        checkout = await GitHubRepositoryCheckout.create(
            github_client=self._github_client,
            repo=repo,
            git_ref=f"refs/heads/{branch.name}",
            head_sha=branch.commit.sha,
        )
        await self.sync_checkout(checkout)

    async def sync_from_push(
        self,
        push_payload: GitHubPushEventModel,
    ) -> None:
        """Synchronize based on a GitHub push event."""
        checkout = await GitHubRepositoryCheckout.create(
            github_client=self._github_client,
            repo=push_payload.repository,
            git_ref=push_payload.ref,
            head_sha=push_payload.after,
        )
        await self.sync_checkout(checkout)

    async def request_github_repository(
        self, owner: str, repo: str
    ) -> GitHubRepositoryModel:
        """Request the GitHub repo resource from the GitHub API."""
        uri = "/repos/{owner}/{repo}"
        data = await self._github_client.getitem(
            uri, url_vars={"owner": owner, "repo": repo}
        )
        return GitHubRepositoryModel.model_validate(data)

    async def request_github_branch(
        self, *, url_template: str, branch: str
    ) -> GitHubBranchModel:
        """Request a GitHub branch resource."""
        data = await self._github_client.getitem(
            url_template, url_vars={"branch": branch}
        )
        return GitHubBranchModel.model_validate(data)

    async def load_settings_file(
        self, *, repo: GitHubRepositoryModel, git_ref: str
    ) -> RepositorySettingsFile:
        """Load the times-square.yaml from a repository."""
        uri = repo.contents_url + "{?ref}"
        data = await self._github_client.getitem(
            uri, url_vars={"path": "times-square.yaml", "ref": git_ref}
        )
        content_data = GitHubBlobModel.model_validate(data)
        file_content = content_data.decode()
        return RepositorySettingsFile.parse_yaml(file_content)

    async def sync_checkout(
        self,
        checkout: GitHubRepositoryCheckout,
    ) -> None:
        """Sync a "checkout" of a GitHub repository.

        Notes
        -----
        Algorithm is:

        1. List existing pages
        2. Iterate over pages in the github repository:

           1. Compare git tree SHAs of content.
              different.
           2. If new, create the page.
           3. If changed, modify the existing page
           4. If disabled, mark the page for deletion.

        3. Delete any pages not found in the repository checkout.
        """
        existing_pages = {
            page.display_path: page
            for page in await self._page_service.get_pages_for_repo(
                owner=checkout.owner_name,
                name=checkout.name,
            )
        }
        found_display_paths: list[str] = []
        self._logger.debug(
            "Syncing checkout", existing_display_paths=existing_pages.keys()
        )

        tree = await checkout.get_git_tree(self._github_client)
        for notebook_ref in tree.find_notebooks(checkout.settings):
            self._logger.info(
                "Loading notebook to sync", notebook_ref=notebook_ref.to_dict()
            )
            notebook = await checkout.load_notebook(
                notebook_ref=notebook_ref, github_client=self._github_client
            )
            display_path = notebook.get_display_path(checkout)
            found_display_paths.append(display_path)
            self._logger.debug("Display path", display_path=display_path)

            if display_path in existing_pages:
                self._logger.debug(
                    "Notebook corresponds to existing page",
                    display_path=display_path,
                )
                # update existing page
                page = existing_pages[display_path]
                if (
                    notebook.notebook_git_tree_sha
                    != page.repository_source_sha
                    or notebook.sidecar_git_tree_sha
                    != page.repository_sidecar_sha
                ):
                    if notebook.sidecar.enabled is False:
                        self._logger.debug(
                            "Notebook is disabled. Dropping from update.",
                            display_path=display_path,
                        )
                        try:
                            found_display_paths.remove(display_path)
                        except ValueError:
                            self._logger.debug(
                                "Tried to delete existing page, now disabled, "
                                "but it was not in found_display_paths.",
                                display_path=display_path,
                                found_display_paths=found_display_paths,
                            )
                    else:
                        self._logger.debug(
                            "Notebook content has updated",
                            display_path=display_path,
                        )
                        await self.update_page(
                            notebook=notebook,
                            page=existing_pages[display_path],
                        )
                else:
                    self._logger.debug(
                        "Notebook content is the same; skipping",
                        display_path=display_path,
                    )
            else:
                if notebook.sidecar.enabled is False:
                    self._logger.debug(
                        "Notebook is disabled. Skipping",
                        display_path=display_path,
                    )
                    continue
                # add new page
                self._logger.debug(
                    "Creating new page for notebook", display_path=display_path
                )
                page = await self.create_page(
                    checkout=checkout, notebook=notebook
                )
                # pre-execute that page
                page_svc = self._page_service
                await page_svc.execute_page_with_defaults(page)

        deleted_paths = set(existing_pages.keys()) - set(found_display_paths)
        self._logger.info("Paths to delete", count=len(deleted_paths))
        for deleted_path in deleted_paths:
            page = existing_pages[deleted_path]
            await self._page_service.soft_delete_page(page)

    async def create_page(
        self,
        *,
        checkout: GitHubRepositoryCheckout,
        notebook: RepositoryNotebookModel,
        commit_sha: str | None = None,
    ) -> PageModel:
        """Create a new page based on the notebook tree ref.

        Parameters
        ----------
        checkout : `GitHubRepositoryCheckout`
            The repository checkout
        notebook : `RepositoryNotebookModel`
            The notebook from the repository that is the basis for the page.
        commit_sha : `str`, optional
            If set, this page is associated with a specific commit, rather than
            the default view of a repository. Commit-specific pages are used
            to show previews for pull requests and GitHub Check Run results.
        """
        display_path_prefix = notebook.get_display_path_prefix(checkout)

        source_path = PurePosixPath(notebook.notebook_source_path)
        sidecar_path = PurePosixPath(notebook.sidecar_path)
        path_stem = source_path.stem
        n = len(path_stem)
        source_ext = source_path.name[n:]
        sidecar_ext = sidecar_path.name[n:]

        if execution_schedule := notebook.sidecar.execution_schedule:
            schedule_rruleset = execution_schedule.schedule_rruleset
        else:
            schedule_rruleset = None

        page = PageModel.create_from_repo(
            ipynb=notebook.ipynb,
            title=notebook.title,
            parameters=notebook.sidecar.export_parameters(),
            github_owner=checkout.owner_name,
            github_repo=checkout.name,
            repository_path_prefix=notebook.path_prefix,
            repository_display_path_prefix=display_path_prefix,
            repository_path_stem=path_stem,
            repository_source_extension=source_ext,
            repository_sidecar_extension=sidecar_ext,
            repository_source_sha=notebook.notebook_git_tree_sha,
            repository_sidecar_sha=notebook.sidecar_git_tree_sha,
            description=notebook.sidecar.description,
            cache_ttl=notebook.sidecar.cache_ttl,
            tags=notebook.sidecar.tags,
            authors=notebook.sidecar.export_authors(),
            timeout=int(notebook.sidecar.timeout.total_seconds())
            if notebook.sidecar.timeout
            else None,
            github_commit=commit_sha,
            schedule_rruleset=schedule_rruleset,
            schedule_enabled=notebook.sidecar.schedule_enabled,
        )
        await self._page_service.add_page_to_store(page)
        return page

    async def update_page(
        self, *, notebook: RepositoryNotebookModel, page: PageModel
    ) -> None:
        """Update an existing page."""
        source_path = PurePosixPath(notebook.notebook_source_path)
        sidecar_path = PurePosixPath(notebook.sidecar_path)
        path_stem = source_path.stem
        n = len(path_stem)
        source_ext = source_path.name[n:]
        sidecar_ext = sidecar_path.name[n:]

        # The only PageModel attributes we don't update are those that are
        # set automatically like Page model and those that affect the display
        # path because then the notebook never would have been resolved
        page.ipynb = notebook.ipynb
        page.parameters = notebook.sidecar.export_parameters()
        page.title = notebook.title
        page.authors = notebook.sidecar.export_authors()
        page.tags = notebook.sidecar.tags
        page.timeout = (
            int(notebook.sidecar.timeout.total_seconds())
            if notebook.sidecar.timeout
            else None
        )
        page.description = notebook.sidecar.description
        page.cache_ttl = notebook.sidecar.cache_ttl
        page.schedule_enabled = notebook.sidecar.schedule_enabled
        if execution_schedule := notebook.sidecar.execution_schedule:
            page.schedule_rruleset = execution_schedule.schedule_rruleset

        # The extensions might change, but we resolve them to the same
        # display path and thus the same page
        page.repository_source_extension = source_ext
        page.repository_sidecar_extension = sidecar_ext
        page.repository_source_sha = notebook.notebook_git_tree_sha
        page.repository_sidecar_sha = notebook.sidecar_git_tree_sha

        await self._page_service.update_page_and_execute(page)

    async def get_check_runs(
        self, owner: str, repo: str, head_sha: str
    ) -> list[GitHubCheckRunModel]:
        """Get the check runs from GitHub corresponding to a commit.

        https://docs.github.com/en/rest/checks/runs#list-check-runs-for-a-git-reference
        """
        return [
            GitHubCheckRunModel.model_validate(item)
            async for item in self._github_client.getiter(
                "/repos/{owner}/{repo}/commits/{ref}/check-runs",
                url_vars={"owner": owner, "repo": repo, "ref": head_sha},
                iterable_key="check_runs",
            )
        ]

    async def get_pulls_for_check_runs(
        self, check_runs: list[GitHubCheckRunModel]
    ) -> list[GitHubPullRequestModel]:
        """Get the pull requests from GitHub covered by the provided check
        runs.

        Normally we'll look up the check runs first with `get_check_runs`
        and then use this method to get information about the corresponding
        pull requests.
        """
        # reduce the unique pull request urls
        pr_urls = [
            str(pr.url)
            for check_run in check_runs
            for pr in check_run.pull_requests
        ]
        pr_urls = sorted(list(set(pr_urls)))

        pull_requests: list[GitHubPullRequestModel] = []
        for pr_url in pr_urls:
            data = await self._github_client.getitem(pr_url)
            pull_requests.append(GitHubPullRequestModel.model_validate(data))

        return pull_requests
