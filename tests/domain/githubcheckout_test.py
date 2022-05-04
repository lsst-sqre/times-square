"""Tests for the githubcheckout domain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List

import pytest
import respx
from gidgethub.httpx import GitHubAPI
from httpx import Response

from timessquare.domain.githubapi import GitHubBlobModel
from timessquare.domain.githubcheckout import (
    GitHubRepositoryCheckout,
    GitTreeMode,
    RecursiveGitTreeModel,
    RepositoryNotebookTreeRef,
    RepositorySettingsFile,
)


def test_settings_file_load() -> None:
    json_path = Path(__file__).parent.joinpath(
        "../data/times-square-demo/settings-blob.json"
    )
    blob = GitHubBlobModel.parse_raw(json_path.read_text())
    settings = RepositorySettingsFile.parse_yaml(blob.decode())
    assert settings.enabled is True


def test_recursive_git_tree_model_rsp_broadcast() -> None:
    """Test that an object returned by the GitHub Git Tree API with
    recursive=1 can be parsed by RecursiveGitTreeModel.
    """
    json_path = Path(__file__).parent.joinpath(
        "../data/rsp_broadcast/recursive_tree.json"
    )
    repo_tree = RecursiveGitTreeModel.parse_raw(json_path.read_text())
    assert repo_tree.sha == "46372dfa5a432026d68d262899755ef0333ef8c0"
    assert repo_tree.truncated is False
    assert len(repo_tree.tree) == 14

    for tree_item in repo_tree.tree:
        if tree_item.path == "README.md":
            assert tree_item.mode == GitTreeMode.file
            assert tree_item.sha == "8e977bc4a1503adb11e3fe06e0ddcf759ad59a91"


def test_git_blob_model_rsp_broadcast() -> None:
    """Test that a git blob, as retrieved from the GitTreeItem.url attribute
    can be parsed by GitHubBlobModel.
    """
    json_path = Path(__file__).parent.joinpath(
        "../data/rsp_broadcast/readme_blob.json"
    )
    blob = GitHubBlobModel.parse_raw(json_path.read_text())
    assert blob.sha == "8e977bc4a1503adb11e3fe06e0ddcf759ad59a91"
    assert blob.encoding == "base64"
    assert blob.decode().startswith(
        "# Broadcast messages for the Rubin Science Platform"
    )


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
        settings=RepositorySettingsFile(),
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
    assert repo_tree.sha == "46372dfa5a432026d68d262899755ef0333ef8c0"


@pytest.mark.asyncio
async def test_recursive_git_tree_find_notebooks() -> None:
    """test RecursiveGitTreeModel using the times-square-time dataset."""
    json_path = Path(__file__).parent.joinpath(
        "../data/times-square-demo/recursive_tree.json"
    )
    repo_tree = RecursiveGitTreeModel.parse_raw(json_path.read_text())
    settings = RepositorySettingsFile()
    notebook_refs: List[RepositoryNotebookTreeRef] = []
    for notebook_ref in repo_tree.find_notebooks(settings):
        notebook_refs.append(notebook_ref)
    assert len(notebook_refs) == 2

    # Apply ignore settings to reduce number of detected notebooks
    settings2 = RepositorySettingsFile(ignore=["matplotlib/*"])
    notebook_refs2: List[RepositoryNotebookTreeRef] = []
    for notebook_ref in repo_tree.find_notebooks(settings2):
        notebook_refs2.append(notebook_ref)
    assert len(notebook_refs2) == 1
