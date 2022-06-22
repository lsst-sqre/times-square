"""Service layer related to GitHub-backed content.

This service works with the githubcheckout domain models and collaborates
with the Page service for managing page domain models.
"""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import List

from gidgethub.httpx import GitHubAPI
from structlog.stdlib import BoundLogger

from timessquare.domain.githubapi import (
    GitHubBlobModel,
    GitHubBranchModel,
    GitHubCheckRunModel,
    GitHubCheckRunStatus,
    GitHubRepositoryModel,
)
from timessquare.domain.githubcheckout import (
    GitHubRepositoryCheckout,
    RepositoryNotebookModel,
    RepositorySettingsFile,
)
from timessquare.domain.githubcheckrun import GitHubConfigsCheck
from timessquare.domain.githubwebhook import (
    GitHubCheckRunEventModel,
    GitHubCheckSuiteEventModel,
    GitHubPullRequestModel,
    GitHubPushEventModel,
)
from timessquare.domain.page import PageModel

from ..page import PageService


class GitHubRepoService:
    """A service manager for GitHub-backed pages.

    Parameters
    ----------
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
        github_client: GitHubAPI,
        page_service: PageService,
        logger: BoundLogger,
    ) -> None:
        self._github_client = github_client
        self._page_service = page_service
        self._logger = logger

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

    async def check_pull_request(
        self, pr_payload: GitHubPullRequestModel
    ) -> None:
        """Run a check on a pull request."""
        pass

    async def request_github_repository(
        self, owner: str, repo: str
    ) -> GitHubRepositoryModel:
        """Request the GitHub repo resource from the GitHub API."""
        uri = "/repos/{owner}/{repo}"
        data = await self._github_client.getitem(
            uri, url_vars={"owner": owner, "repo": repo}
        )
        return GitHubRepositoryModel.parse_obj(data)

    async def request_github_branch(
        self, *, url_template: str, branch: str
    ) -> GitHubBranchModel:
        """Request a GitHub branch resource."""
        data = await self._github_client.getitem(
            url_template, url_vars={"branch": branch}
        )
        return GitHubBranchModel.parse_obj(data)

    async def create_checkout(
        self, *, repo: GitHubRepositoryModel, git_ref: str, head_sha: str
    ) -> GitHubRepositoryCheckout:
        settings = await self.load_settings_file(repo=repo, git_ref=head_sha)
        checkout = GitHubRepositoryCheckout(
            owner_name=repo.owner.login,
            name=repo.name,
            settings=settings,
            git_ref=git_ref,
            head_sha=head_sha,
            trees_url=repo.trees_url,
            blobs_url=repo.blobs_url,
        )
        return checkout

    async def load_settings_file(
        self, *, repo: GitHubRepositoryModel, git_ref: str
    ) -> RepositorySettingsFile:
        """Load the times-square.yaml from a repository."""
        uri = repo.contents_url + "{?ref}"
        # TODO handle cases where the repo doesn't have settings (i.e.
        # fail gracefully)
        data = await self._github_client.getitem(
            uri, url_vars={"path": "times-square.yaml", "ref": git_ref}
        )
        content_data = GitHubBlobModel.parse_obj(data)
        file_content = content_data.decode()
        return RepositorySettingsFile.parse_yaml(file_content)

    async def sync_checkout(self, checkout: GitHubRepositoryCheckout) -> None:
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

        3. Delete any pages not found in the repository checkout.
        """
        existing_pages = {
            page.display_path: page
            for page in await self._page_service.get_pages_for_repo(
                owner=checkout.owner_name, name=checkout.name
            )
        }
        found_display_paths: List[str] = []
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

            if display_path in existing_pages.keys():
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
                    self._logger.debug(
                        "Notebook content has updated",
                        display_path=display_path,
                    )
                    await self.update_page(
                        notebook=notebook, page=existing_pages[display_path]
                    )
                else:
                    self._logger.debug(
                        "Notebook content is the same; skipping",
                        display_path=display_path,
                    )
            else:
                # add new page
                self._logger.debug(
                    "Creating new page for notebook", display_path=display_path
                )
                await self.create_new_page(
                    checkout=checkout, notebook=notebook
                )

        deleted_paths = set(existing_pages.keys()) - set(found_display_paths)
        self._logger.info("Paths to delete", count=len(deleted_paths))
        for deleted_path in deleted_paths:
            page = existing_pages[deleted_path]
            await self._page_service.soft_delete_page(page)

    async def create_new_page(
        self,
        *,
        checkout: GitHubRepositoryCheckout,
        notebook: RepositoryNotebookModel,
    ) -> None:
        """Create a new page based on the notebook tree ref."""
        display_path_prefix = notebook.get_display_path_prefix(checkout)

        source_path = PurePosixPath(notebook.notebook_source_path)
        sidecar_path = PurePosixPath(notebook.sidecar_path)
        path_stem = source_path.stem
        n = len(path_stem)
        source_ext = source_path.name[n:]
        sidecar_ext = sidecar_path.name[n:]

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
        )
        await self._page_service.add_page(page)

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
        page.description = notebook.sidecar.description
        page.cache_ttl = notebook.sidecar.cache_ttl
        # The extensions might change, but we resolve them to the same
        # display path and thus the same page
        page.repository_source_extension = source_ext
        page.repository_sidecar_extension = sidecar_ext
        page.repository_source_sha = notebook.notebook_git_tree_sha
        page.repository_sidecar_sha = notebook.sidecar_git_tree_sha

        await self._page_service.update_page(page)

    async def create_check_run(
        self, *, payload: GitHubCheckSuiteEventModel
    ) -> None:
        """Create a new GitHub check run suite, given a new Check Suite.

        NOTE: currently we're assuming that check suites are automatically
        created when created a check run. See
        https://docs.github.com/en/rest/checks/runs#create-a-check-run
        """
        await self._create_yaml_config_check_run(
            repo=payload.repository,
            head_sha=payload.check_suite.head_sha,
        )

    async def create_rerequested_check_run(
        self, *, payload: GitHubCheckRunEventModel
    ) -> None:
        """Run a GitHub check run that was rerequested."""
        await self._create_yaml_config_check_run(
            repo=payload.repository,
            head_sha=payload.check_run.head_sha,
        )

    async def _create_yaml_config_check_run(
        self, *, repo: GitHubRepositoryModel, head_sha: str
    ) -> None:
        data = await self._github_client.post(
            "repos/{owner}/{repo}/check-runs",
            url_vars={"owner": repo.owner.login, "repo": repo.name},
            data={"name": "YAML configurations", "head_sha": head_sha},
        )
        check_run = GitHubCheckRunModel.parse_obj(data)
        await self._compute_check_run(check_run=check_run, repo=repo)

    async def compute_check_run(
        self, *, payload: GitHubCheckRunEventModel
    ) -> None:
        """Compute a GitHub check run."""
        await self._compute_check_run(
            repo=payload.repository, check_run=payload.check_run
        )

    async def _compute_check_run(
        self, *, repo: GitHubRepositoryModel, check_run: GitHubCheckRunModel
    ) -> None:
        """Compute the YAML validation check run."""
        # Set the check run to in-progress
        await self._github_client.patch(
            check_run.url,
            data={"status": GitHubCheckRunStatus.in_progress},
        )

        config_check = await GitHubConfigsCheck.validate_repo(
            github_client=self._github_client,
            repo=repo,
            head_sha=check_run.head_sha,
        )

        # Set the check run to complete
        await self._github_client.patch(
            check_run.url,
            data={
                "status": GitHubCheckRunStatus.completed,
                "conclusion": config_check.conclusion,
                "output": {
                    "title": config_check.title,
                    "summary": config_check.summary,
                    "text": config_check.text,
                    "annotations": config_check.export_truncated_annotations(),
                },
            },
        )
