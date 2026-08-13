"""Tests for the timessquare.storage.github.apimodels module."""

from __future__ import annotations

import json
from pathlib import Path

from timessquare.storage.github.apimodels import (
    GitHubInstallationTargetRenamedEventModel,
    GitHubPushEventWithIdModel,
    GitHubRepositoryRenamedEventModel,
    GitHubRepositoryTransferredEventModel,
    GitTreeMode,
    RecursiveGitTreeModel,
)


def test_push_event_carries_numeric_ids() -> None:
    """Test that the local push event model keeps the numeric repository and
    owner IDs that Safir's model drops.
    """
    json_path = Path(__file__).parent.joinpath(
        "../../data/github_webhooks/push_event.json"
    )
    payload = json.loads(json_path.read_text())
    payload["installation"]["id"] = 456
    event = GitHubPushEventWithIdModel.model_validate(payload)

    assert event.repository.id == 186853002
    assert event.repository.owner.id == 21031067
    assert event.repository.owner.login == "Codertocat"
    assert event.installation.id == 456


def test_repository_renamed_event() -> None:
    """Test that the repository rename event exposes both the new name and
    the name the repository is stored under.
    """
    json_path = Path(__file__).parent.joinpath(
        "../../data/github_webhooks/repository_renamed.json"
    )
    event = GitHubRepositoryRenamedEventModel.model_validate_json(
        json_path.read_text()
    )

    assert event.old_repo_name == "Hello-World"
    assert event.repository.name == "Hello-World-Renamed"
    assert event.repository.id == 186853002
    assert event.repository.owner.login == "Codertocat"
    assert event.repository.owner.id == 21031067
    assert event.installation.id == 1234


def test_repository_transferred_event() -> None:
    """Test that the repository transfer event exposes the new owner's login
    and numeric ID, and the login of the owner it came from.
    """
    json_path = Path(__file__).parent.joinpath(
        "../../data/github_webhooks/repository_transferred.json"
    )
    event = GitHubRepositoryTransferredEventModel.model_validate_json(
        json_path.read_text()
    )

    assert event.repository.id == 186853002
    assert event.repository.name == "times-square-demo"
    assert event.repository.owner.login == "lsst-sqre"
    assert event.repository.owner.id == 30830384
    assert event.old_owner_login == "Codertocat"
    assert event.installation.id == 1234


def test_repository_transferred_event_from_organization() -> None:
    """Test that the previous owner is also read from an organization
    transfer, which GitHub reports under a different key than a user
    transfer.
    """
    json_path = Path(__file__).parent.joinpath(
        "../../data/github_webhooks/repository_transferred.json"
    )
    payload = json.loads(json_path.read_text())
    payload["changes"]["owner"]["from"] = {
        "organization": {"login": "lsst-sitcom", "id": 12345}
    }
    event = GitHubRepositoryTransferredEventModel.model_validate(payload)

    assert event.old_owner_login == "lsst-sitcom"


def test_installation_target_renamed_event() -> None:
    """Test that the installation target rename event exposes both the new
    login and the login the account's pages are stored under, along with the
    rename-proof numeric owner ID.
    """
    json_path = Path(__file__).parent.joinpath(
        "../../data/github_webhooks/installation_target_renamed.json"
    )
    event = GitHubInstallationTargetRenamedEventModel.model_validate_json(
        json_path.read_text()
    )

    assert event.old_login == "lsst-sqre"
    assert event.new_login == "lsst-so"
    assert event.account.login == "lsst-so"
    assert event.account.id == 30830384
    assert event.target_type == "Organization"
    assert event.installation.id == 1234


def test_installation_target_renamed_event_user_account() -> None:
    """A personal account rename parses the same way an organization's does:
    only ``target_type`` distinguishes them, and Times Square treats both as
    the ``github_owner`` of its pages.
    """
    json_path = Path(__file__).parent.joinpath(
        "../../data/github_webhooks/installation_target_renamed.json"
    )
    payload = json.loads(json_path.read_text())
    payload["target_type"] = "User"
    payload["account"]["type"] = "User"
    event = GitHubInstallationTargetRenamedEventModel.model_validate(payload)

    assert event.target_type == "User"
    assert event.old_login == "lsst-sqre"
    assert event.new_login == "lsst-so"


def test_installation_target_renamed_event_without_login_change() -> None:
    """GitHub does not mark ``changes.login`` as required, so a payload that
    renames something other than the login parses with no old login rather
    than failing validation and 500-ing the webhook endpoint.
    """
    json_path = Path(__file__).parent.joinpath(
        "../../data/github_webhooks/installation_target_renamed.json"
    )
    payload = json.loads(json_path.read_text())
    payload["changes"] = {"slug": {"from": "old-slug"}}
    event = GitHubInstallationTargetRenamedEventModel.model_validate(payload)

    assert event.old_login is None
    assert event.new_login == "lsst-so"


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
