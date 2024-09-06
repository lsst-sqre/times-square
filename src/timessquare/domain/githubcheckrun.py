"""Domain models for a GitHub Check Runs computations."""

from __future__ import annotations

from abc import ABCMeta, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

from gidgethub.httpx import GitHubAPI
from pydantic import ValidationError
from safir.github.models import (
    GitHubBlobModel,
    GitHubCheckRunAnnotationLevel,
    GitHubCheckRunConclusion,
    GitHubCheckRunModel,
    GitHubCheckRunStatus,
    GitHubRepositoryModel,
)
from yaml import YAMLError

from timessquare.config import config
from timessquare.exceptions import PageJinjaError

from ..storage.noteburst import NoteburstJobResponseModel, NoteburstJobStatus
from .githubcheckout import (
    GitHubRepositoryCheckout,
    NotebookSidecarFile,
    RecursiveGitTreeModel,
    RepositoryNotebookTreeRef,
)
from .page import PageExecutionInfo, PageModel


@dataclass(kw_only=True)
class Annotation:
    """Annotation of an issue in a file."""

    path: str

    start_line: int

    message: str

    title: str

    annotation_level: GitHubCheckRunAnnotationLevel

    end_line: int | None = None

    @classmethod
    def from_validation_error(
        cls, path: str, error: ValidationError
    ) -> list[Annotation]:
        """Create a list of annotations from a Pydantic validation error."""
        annotations: list[Annotation] = []
        for item in error.errors():
            title = cls._format_title_for_pydantic_item(item["loc"])
            annotations.append(
                Annotation(
                    path=path,
                    start_line=1,
                    message=item["msg"],
                    title=title,
                    annotation_level=GitHubCheckRunAnnotationLevel.failure,
                )
            )
        return annotations

    @classmethod
    def from_yaml_error(cls, path: str, error: YAMLError) -> list[Annotation]:
        """Create a list of annotations from a YAML syntax error."""
        if hasattr(error, "problem_mark"):
            # The YAML syntax error has a problem mark pointing to the
            # location of the error.
            start_line = error.problem_mark.line + 1
            column = error.problem_mark.column + 1
            return [
                Annotation(
                    path=path,
                    start_line=start_line,
                    message=str(error),
                    title=f"YAML syntax error ({start_line}:{column})",
                    annotation_level=GitHubCheckRunAnnotationLevel.failure,
                )
            ]
        return [
            # The exact location is unknown
            Annotation(
                path=path,
                start_line=1,
                message=str(error),
                title="YAML syntax error",
                annotation_level=GitHubCheckRunAnnotationLevel.failure,
            )
        ]

    @staticmethod
    def _format_title_for_pydantic_item(locations: Sequence[str | int]) -> str:
        title_elements: list[str] = []
        for location in locations:
            if isinstance(location, int):
                title_elements.append(f"[{location}]")
            else:
                title_elements.append(f".{location}")
        return "".join(title_elements).lstrip(".")

    def export(self) -> dict[str, Any]:
        """Export a GitHub check run output annotation object."""
        output = {
            "path": self.path,
            "start_line": self.start_line,
            "message": self.message,
            "title": self.title,
            "annotation_level": self.annotation_level,
        }
        if self.end_line:
            output["end_line"] = self.end_line
        else:
            output["end_line"] = self.start_line
        return output


class GitHubCheck(metaclass=ABCMeta):
    """A base class for GitHub Check domain models."""

    title: str = "Times Square check"

    external_id: str = "times-square/generic-check"
    """The CheckRun external ID field. All check runs of this type
    share the same external ID.
    """

    def __init__(
        self, *, check_run: GitHubCheckRunModel, repo: GitHubRepositoryModel
    ) -> None:
        self.check_run = check_run
        self.repo = repo
        self.annotations: list[Annotation] = []

    @property
    def conclusion(self) -> GitHubCheckRunConclusion:
        """A conclusion based on the annotations."""
        for annotation in self.annotations:
            if (
                annotation.annotation_level
                == GitHubCheckRunAnnotationLevel.failure
            ):
                return GitHubCheckRunConclusion.failure

        return GitHubCheckRunConclusion.success

    @property
    @abstractmethod
    def summary(self) -> str:
        """Summary text for the check."""
        raise NotImplementedError

    @property
    @abstractmethod
    def text(self) -> str:
        """Text body of the check's message."""
        raise NotImplementedError

    @property
    def squareone_pr_url_root(self) -> str:
        """Root URL for this check run in Squareone.

        Formatted as ``{host}/times-square/github-pr/{owner}/{repo}/{commit}``
        """
        if str(config.environment_url).endswith("/"):
            squareone_url = str(config.environment_url)
        else:
            squareone_url = f"{config.environment_url!s}/"
        return (
            f"{squareone_url}/times-square/github-pr/{self.repo.owner.login}"
            f"/{self.repo.name}/{self.check_run.head_sha}"
        )

    def get_preview_url(self, notebook_path: str) -> str:
        path = PurePosixPath(notebook_path)
        display_path = str(path.parent.joinpath(path.stem))
        return f"{self.squareone_pr_url_root}/{display_path}"

    def export_truncated_annotations(self) -> list[dict[str, Any]]:
        """Export the first 50 annotations to objects serializable to
        GitHub.

        Sending more than 50 annotations requires multiple HTTP requests,
        which we haven't implemented yet. See
        https://docs.github.com/en/rest/checks/runs#update-a-check-run
        """
        return [a.export() for a in self.annotations[:50]]

    async def submit_in_progress(self, github_client: GitHubAPI) -> None:
        """Set the check run to "In progress"."""
        await github_client.patch(
            str(self.check_run.url),
            data={"status": GitHubCheckRunStatus.in_progress},
        )

    async def submit_conclusion(
        self,
        *,
        github_client: GitHubAPI,
    ) -> None:
        """Send a patch result for the check run to GitHub with the final
        conclusion of the check.
        """
        await github_client.patch(
            str(self.check_run.url),
            data={
                "status": GitHubCheckRunStatus.completed,
                "conclusion": self.conclusion,
                "details_url": self.squareone_pr_url_root,
                "output": {
                    "title": self.title,
                    "summary": self.summary,
                    "text": self.text,
                    "annotations": self.export_truncated_annotations(),
                },
            },
        )


class GitHubConfigsCheck(GitHubCheck):
    """A domain model for a YAML configuration GitHub Check run."""

    title: str = "YAML config validation"

    external_id: str = "times-square/yaml-check"
    """The CheckRun external ID field. All check runs of this type
    share the same external ID.
    """

    def __init__(
        self, check_run: GitHubCheckRunModel, repo: GitHubRepositoryModel
    ) -> None:
        self.sidecar_files_checked: list[str] = []

        # Optional caching for data reuse
        self.checkout: GitHubRepositoryCheckout | None = None
        self.tree: RecursiveGitTreeModel | None = None

        super().__init__(check_run=check_run, repo=repo)

    @classmethod
    async def create_check_run_and_validate(
        cls,
        *,
        github_client: GitHubAPI,
        repo: GitHubRepositoryModel,
        head_sha: str,
    ) -> GitHubConfigsCheck:
        """Create a GitHubConfigsCheck by first creating a GitHub Check Run,
        then running a validation via `validate_repo`.
        """
        data = await github_client.post(
            "repos/{owner}/{repo}/check-runs",
            url_vars={"owner": repo.owner.login, "repo": repo.name},
            data={
                "name": cls.title,
                "head_sha": head_sha,
                "external_id": cls.external_id,
            },
        )
        check_run = GitHubCheckRunModel.model_validate(data)
        return await cls.validate_repo(
            check_run=check_run,
            github_client=github_client,
            repo=repo,
            head_sha=head_sha,
        )

    @classmethod
    async def validate_repo(
        cls,
        *,
        github_client: GitHubAPI,
        repo: GitHubRepositoryModel,
        head_sha: str,
        check_run: GitHubCheckRunModel,
    ) -> GitHubConfigsCheck:
        """Create a check run result model for a specific SHA of a GitHub
        repository containing Times Square notebooks given a check run already
        registered with GitHub.
        """
        check = cls(check_run, repo)
        await check.submit_in_progress(github_client)

        # Check out the repository and validate the times-square.yaml file.
        try:
            checkout = await GitHubRepositoryCheckout.create(
                github_client=github_client,
                repo=repo,
                head_sha=head_sha,
            )
        except ValidationError as e:
            annotations = Annotation.from_validation_error(
                path="times-square.yaml", error=e
            )
            check.annotations.extend(annotations)
            return check
        except YAMLError as e:
            annotations = Annotation.from_yaml_error(
                path="times-square.yaml", error=e
            )
            check.annotations.extend(annotations)
            return check

        # Validate each notebook yaml file
        tree = await checkout.get_git_tree(github_client)
        for notebook_ref in tree.find_notebooks(checkout.settings):
            await check.validate_sidecar(
                github_client=github_client,
                repo=repo,
                notebook_ref=notebook_ref,
            )

        # Cache this checkout and tree so that the notebook execution check
        # can reuse them efficiently.
        check.cache_github_checkout(
            checkout=checkout,
            tree=tree,
        )

        return check

    async def validate_sidecar(
        self,
        *,
        github_client: GitHubAPI,
        repo: GitHubRepositoryModel,
        notebook_ref: RepositoryNotebookTreeRef,
    ) -> None:
        """Validate the sidecar file for a notebook, adding its results
        to the check.
        """
        data = await github_client.getitem(
            repo.blobs_url,
            url_vars={"sha": notebook_ref.sidecar_git_tree_sha},
        )
        sidecar_blob = GitHubBlobModel.model_validate(data)
        try:
            NotebookSidecarFile.parse_yaml(sidecar_blob.decode())
        except ValidationError as e:
            annotations = Annotation.from_validation_error(
                path=notebook_ref.sidecar_path, error=e
            )
            self.annotations.extend(annotations)
        except YAMLError as e:
            annotations = Annotation.from_yaml_error(
                path=notebook_ref.sidecar_path, error=e
            )
            self.annotations.extend(annotations)
        self.sidecar_files_checked.append(notebook_ref.sidecar_path)

    @property
    def conclusion(self) -> GitHubCheckRunConclusion:
        for annotation in self.annotations:
            if (
                annotation.annotation_level
                == GitHubCheckRunAnnotationLevel.failure
            ):
                return GitHubCheckRunConclusion.failure

        return GitHubCheckRunConclusion.success

    @property
    def summary(self) -> str:
        sidecar_count = len(self.sidecar_files_checked)

        if self.conclusion == GitHubCheckRunConclusion.success:
            text = "Everything looks good ✅"
        else:
            text = "There are some issues 🧐"

        if sidecar_count == 1:
            text = (
                f"{text} (checked times-square.yaml and 1 notebook sidecar "
                "file)"
            )
        else:
            text = (
                f"{text} (checked times-square.yaml and "
                f"{sidecar_count} notebook sidecar files)"
            )

        return text

    @property
    def text(self) -> str:
        text = "| File | Status |\n | --- | :-: |\n"

        if self._is_file_ok("times-square.yaml"):
            text = f"{text}| times-square.yaml | ✅ |\n"
        else:
            text = f"{text}| times-square.yaml | ❌ |\n"

        sidecar_files = list(set(self.sidecar_files_checked))
        sidecar_files.sort()
        for sidecar_path in sidecar_files:
            if self._is_file_ok(sidecar_path):
                text = f"{text}| {sidecar_path} | ✅ |\n"
            else:
                text = f"{text}| {sidecar_path} | ❌ |\n"

        return text

    def _is_file_ok(self, path: str) -> bool:
        return all(annotation.path != path for annotation in self.annotations)

    def cache_github_checkout(
        self,
        *,
        checkout: GitHubRepositoryCheckout,
        tree: RecursiveGitTreeModel,
    ) -> None:
        """Cache the checkout and Git tree (usually obtained in
        iniitalization so they can be reused elsewhere without getting the
        resources again from GitHub.
        """
        self.checkout = checkout
        self.tree = tree


class NotebookExecutionsCheck(GitHubCheck):
    """A domain model for a notebook execution GitHub check."""

    title: str = "Notebook execution"

    external_id: str = "times-square/nbexec"
    """The CheckRun external ID field. All check runs of this type
    share the same external ID.
    """

    def __init__(
        self, check_run: GitHubCheckRunModel, repo: GitHubRepositoryModel
    ) -> None:
        self.notebook_paths_checked: list[str] = []
        super().__init__(check_run=check_run, repo=repo)

    def report_jinja_error(
        self, page: PageModel, error: PageJinjaError
    ) -> None:
        """Report an error rendering a Jinja template in a notebook cell."""
        path = page.repository_source_path
        if path is None:
            raise RuntimeError("Page execution has no notebook path")
        annotation = Annotation(
            path=path,
            start_line=1,
            message=str(error),
            title="Notebook Jinja templating error",
            annotation_level=GitHubCheckRunAnnotationLevel.failure,
        )
        self.annotations.append(annotation)
        self.notebook_paths_checked.append(path)

    def report_noteburst_failure(
        self, page_execution: PageExecutionInfo
    ) -> None:
        path = page_execution.page.repository_source_path
        if path is None:
            raise RuntimeError("Page execution has no notebook path")
        annotation = Annotation(
            path=path,
            start_line=1,
            message=page_execution.noteburst_error_message or "",
            title=(
                "Noteburst error (status "
                f"{page_execution.noteburst_error_message})"
            ),
            annotation_level=GitHubCheckRunAnnotationLevel.failure,
        )
        self.annotations.append(annotation)
        self.notebook_paths_checked.append(path)

    def report_noteburst_completion(
        self,
        *,
        page_execution: PageExecutionInfo,
        job_result: NoteburstJobResponseModel,
    ) -> None:
        if job_result.status != NoteburstJobStatus.complete:
            raise ValueError("Noteburst job isn't complete yet")
        if job_result.status is None:
            raise RuntimeError("Noteburst job has no status")

        notebook_path = page_execution.page.repository_source_path
        if notebook_path is None:
            raise RuntimeError("Page execution has no notebook source path")
        self.notebook_paths_checked.append(notebook_path)
        if not job_result.success:
            annotation = Annotation(
                path=notebook_path,
                start_line=1,
                message="We couldn't run this notebook successfully.",
                title="Notebook execution error",
                annotation_level=GitHubCheckRunAnnotationLevel.failure,
            )
            self.annotations.append(annotation)

    def report_noteburst_timeout(
        self,
        *,
        page_execution: PageExecutionInfo,
        job_result: NoteburstJobResponseModel,
    ) -> None:
        """Report that the notebook execution failed to complete in time."""
        path = page_execution.page.repository_source_path
        if path is None:
            raise RuntimeError("Page execution has no notebook path")
        message = "The notebook execution timed out."
        if job_result.status == NoteburstJobStatus.in_progress:
            message += (
                " The notebook execution is still in progress "
                f"after {job_result.runtime.total_seconds()} seconds."
            )
        elif job_result.status == NoteburstJobStatus.queued:
            message += (
                " The notebook execution is still in the Noteburst queue."
                f"after {job_result.runtime.total_seconds()} seconds."
            )
        annotation = Annotation(
            path=path,
            start_line=1,
            message=message,
            title="Noteburst timeout",
            annotation_level=GitHubCheckRunAnnotationLevel.failure,
        )
        self.annotations.append(annotation)
        self.notebook_paths_checked.append(path)

    @property
    def summary(self) -> str:
        notebooks_count = len(self.notebook_paths_checked)
        if self.conclusion == GitHubCheckRunConclusion.success:
            text = "Notebooks ran without issue ✅"
        else:
            text = "There are some issues 🧐"

        if notebooks_count == 1:
            text = f"{text} (checked {notebooks_count} notebook)"
        else:
            text = f"{text} (checked {notebooks_count} notebooks)"

        return text

    @property
    def text(self) -> str:
        text = "| Notebook | Status |\n | --- | :-: |\n"

        notebook_paths = list(set(self.notebook_paths_checked))
        notebook_paths.sort()
        for notebook_path in notebook_paths:
            preview_url = self.get_preview_url(notebook_path)
            linked_notebook = f"[{notebook_path}]({preview_url})"
            if self._is_file_ok(notebook_path):
                text = f"{text}| {linked_notebook} | ✅ |\n"
            else:
                text = f"{text}| {linked_notebook} | ❌ |\n"

        return text

    def _is_file_ok(self, path: str) -> bool:
        return all(annotation.path != path for annotation in self.annotations)
