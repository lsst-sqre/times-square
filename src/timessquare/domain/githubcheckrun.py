"""Domain models for a GitHub Check Runs computations."""

from __future__ import annotations

from abc import ABCMeta, abstractproperty
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Union

from gidgethub.httpx import GitHubAPI
from pydantic import ValidationError

from .githubapi import (
    GitHubBlobModel,
    GitHubCheckRunAnnotationLevel,
    GitHubCheckRunConclusion,
    GitHubCheckRunModel,
    GitHubCheckRunStatus,
    GitHubRepositoryModel,
)
from .githubcheckout import (
    GitHubRepositoryCheckout,
    NotebookSidecarFile,
    RecursiveGitTreeModel,
    RepositoryNotebookTreeRef,
)


@dataclass(kw_only=True)
class Annotation:
    """Annotation of an issue in a file."""

    path: str

    start_line: int

    message: str

    title: str

    annotation_level: GitHubCheckRunAnnotationLevel

    end_line: Optional[int] = None

    @classmethod
    def from_validation_error(
        cls, path: str, error: ValidationError
    ) -> List[Annotation]:
        annotations: List[Annotation] = []
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

    @staticmethod
    def _format_title_for_pydantic_item(
        locations: Sequence[Union[str, int]]
    ) -> str:
        title_elements: List[str] = []
        for location in locations:
            if isinstance(location, int):
                title_elements.append(f"[{location}]")
            else:
                title_elements.append(f".{location}")
        return "".join(title_elements).lstrip(".")

    def export(self) -> Dict[str, Any]:
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

    def __init__(self, check_run: GitHubCheckRunModel) -> None:
        self.check_run = check_run
        self.annotations: List[Annotation] = []

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

    @abstractproperty
    def summary(self) -> str:
        """Summary text for the check."""
        raise NotImplementedError

    @abstractproperty
    def text(self) -> str:
        """The text body of the check's message."""
        raise NotImplementedError

    def export_truncated_annotations(self) -> List[Dict[str, Any]]:
        """Export the first 50 annotations to objects serializable to
        GitHub.

        Sending more than 50 annotations requires multiple HTTP requests,
        which we haven't implemented yet. See
        https://docs.github.com/en/rest/checks/runs#update-a-check-run
        """
        return [a.export() for a in self.annotations[:50]]

    async def submit_conclusion(
        self,
        *,
        github_client: GitHubAPI,
    ) -> None:
        """Send a patch result for the check run to GitHub with the final
        conclusion of the check.
        """
        await github_client.patch(
            self.check_run.url,
            data={
                "status": GitHubCheckRunStatus.completed,
                "conclusion": self.conclusion,
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

    def __init__(self, check_run: GitHubCheckRunModel) -> None:
        self.sidecar_files_checked: List[str] = []

        # Optional caching for data reuse
        self.checkout: Optional[GitHubRepositoryCheckout] = None
        self.tree: Optional[RecursiveGitTreeModel] = None

        super().__init__(check_run=check_run)

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
        check_run = GitHubCheckRunModel.parse_obj(data)
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
        check = cls(check_run)

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
        check._cache_github_checkout(
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
        sidecar_blob = GitHubBlobModel.parse_obj(data)
        try:
            NotebookSidecarFile.parse_yaml(sidecar_blob.decode())
        except ValidationError as e:
            annotations = Annotation.from_validation_error(
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
        for annotation in self.annotations:
            if annotation.path == path:
                return False
        return True

    def _cache_github_checkout(
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
