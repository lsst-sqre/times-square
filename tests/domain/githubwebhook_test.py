"""Tests for Github webhook domain models."""

from __future__ import annotations

from pathlib import Path

from timessquare.domain.githubwebhook import (
    GitHubAppInstallationRepositoriesEventModel,
    GitHubPullRequestEventModel,
    GitHubPushEventModel,
)


def test_push_event() -> None:
    data_path = Path(__file__).parent.joinpath(
        "../data/github_webhooks/push_event.json"
    )
    data = GitHubPushEventModel.parse_raw(data_path.read_text())

    assert data.ref == "refs/tags/simple-tag"
    assert data.repository.name == "Hello-World"


def test_installation_repositories_event() -> None:
    data_path = Path(__file__).parent.joinpath(
        "../data/github_webhooks/installation_repositories.json"
    )
    data = GitHubAppInstallationRepositoriesEventModel.parse_raw(
        data_path.read_text()
    )

    assert data.action == "added"
    assert data.repositories_added[0].name == "Space"
    assert data.repositories_added[0].owner_name == "Codertocat"


def test_pull_request_event() -> None:
    data_path = Path(__file__).parent.joinpath(
        "../data/github_webhooks/pull_request_event.json"
    )
    data = GitHubPullRequestEventModel.parse_raw(data_path.read_text())

    assert data.number == 2
    assert data.action == "opened"
    assert data.pull_request.number == 2
    assert data.pull_request.title == "Update the README with new information."
