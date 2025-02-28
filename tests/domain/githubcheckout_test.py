"""Tests for the githubcheckout domain."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import respx
from gidgethub.httpx import GitHubAPI
from httpx import Response

from timessquare.domain.githubcheckout import (
    GitHubRepositoryCheckout,
    RepositoryTree,
)
from timessquare.storage.github.apimodels import RecursiveGitTreeModel
from timessquare.storage.github.settingsfiles import RepositorySettingsFile


@pytest.mark.asyncio
async def test_repository_git_tree(
    github_client: GitHubAPI, respx_mock: respx.Router
) -> None:
    """Test that GitHubRepositoryCheckout.get_git_tree() calls the tree URL
    with the ``?recursive=1`` query string.

    Uses the lsst-sqre/rsp_broadcast repo as a simple test dataset.
    """
    json_path = Path(__file__).parent.joinpath(
        "../data/rsp_broadcast/recursive_tree.json"
    )
    repo = GitHubRepositoryCheckout(
        owner_name="lsst-sqre",
        name="rsp_broadcast",
        settings=RepositorySettingsFile(ignore=[]),
        git_ref="refs/heads/main",
        head_sha="46372dfa5a432026d68d262899755ef0333ef8c0",
        trees_url=(
            "https://api.github.com/repos/lsst-sqre/rsp_broadcast/git/trees/"
            "46372dfa5a432026d68d262899755ef0333ef8c0"
        ),
        blobs_url=(
            "https://api.github.com/repos/lsst-sqre/rsp_broadcast/git/blobs/"
            "46372dfa5a432026d68d262899755ef0333ef8c0"
        ),
    )

    # respx_mock
    respx_mock.get(
        "https://api.github.com/repos/lsst-sqre/rsp_broadcast/git/trees/"
        "46372dfa5a432026d68d262899755ef0333ef8c0?recursive=1"
    ).mock(return_value=Response(200, json=json.loads(json_path.read_text())))
    repo_tree = await repo.get_git_tree(github_client)
    assert (
        repo_tree.github_tree.sha == "46372dfa5a432026d68d262899755ef0333ef8c0"
    )


@pytest.mark.asyncio
async def test_recursive_git_tree_find_notebooks() -> None:
    """Test RepositoryTree using the times-square-time dataset."""
    json_path = Path(__file__).parent.joinpath(
        "../data/times-square-demo/recursive_tree.json"
    )
    repo_tree = RepositoryTree(
        github_tree=RecursiveGitTreeModel.model_validate_json(
            json_path.read_text()
        )
    )
    settings = RepositorySettingsFile(ignore=[])
    notebook_refs = list(repo_tree.find_notebooks(settings))
    assert len(notebook_refs) == 2

    # Apply ignore settings to reduce number of detected notebooks
    settings2 = RepositorySettingsFile(ignore=["matplotlib/*"])
    notebook_refs2 = list(repo_tree.find_notebooks(settings2))
    assert len(notebook_refs2) == 1
