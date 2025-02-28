"""Tests for the timessquare.storage.github.apimodels module."""

from __future__ import annotations

from pathlib import Path

from timessquare.storage.github.apimodels import (
    GitTreeMode,
    RecursiveGitTreeModel,
)


def test_recursive_git_tree_model_rsp_broadcast() -> None:
    """Test that an object returned by the GitHub Git Tree API with
    recursive=1 can be parsed by RecursiveGitTreeModel.
    """
    json_path = Path(__file__).parent.joinpath(
        "../../data/rsp_broadcast/recursive_tree.json"
    )
    repo_tree = RecursiveGitTreeModel.model_validate_json(
        json_path.read_text()
    )
    assert repo_tree.sha == "46372dfa5a432026d68d262899755ef0333ef8c0"
    assert repo_tree.truncated is False
    assert len(repo_tree.tree) == 14

    for tree_item in repo_tree.tree:
        if tree_item.path == "README.md":
            assert tree_item.mode == GitTreeMode.file
            assert tree_item.sha == "8e977bc4a1503adb11e3fe06e0ddcf759ad59a91"
