"""Tests for Github webhook domain models."""

from __future__ import annotations

from pathlib import Path

from timessquare.domain.githubapi import (
    GitHubCheckRunStatus,
    GitHubCheckSuiteConclusion,
    GitHubCheckSuiteStatus,
)
from timessquare.domain.githubwebhook import (
    GitHubAppInstallationEventModel,
    GitHubAppInstallationRepositoriesEventModel,
    GitHubCheckRunEventModel,
    GitHubCheckSuiteEventModel,
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


def test_installation_event() -> None:
    data_path = Path(__file__).parent.joinpath(
        "../data/github_webhooks/installation.json"
    )
    data = GitHubAppInstallationEventModel.parse_raw(data_path.read_text())

    assert data.action == "deleted"
    assert data.repositories[0].name == "Hello-World"
    assert data.repositories[0].owner_name == "octocat"


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


def test_check_suite_completed_event() -> None:
    data_path = Path(__file__).parent.joinpath(
        "../data/github_webhooks/check_suite_completed.json"
    )
    data = GitHubCheckSuiteEventModel.parse_raw(data_path.read_text())

    assert data.action == "completed"
    assert data.check_suite.id == "118578147"
    assert data.check_suite.head_branch == "changes"
    assert data.check_suite.head_sha == (
        "ec26c3e57ca3a959ca5aad62de7213c562f8c821"
    )
    assert data.check_suite.status == GitHubCheckSuiteStatus.completed
    assert data.check_suite.conclusion == GitHubCheckSuiteConclusion.success


def test_check_run_created_event() -> None:
    data_path = Path(__file__).parent.joinpath(
        "../data/github_webhooks/check_run_created.json"
    )
    data = GitHubCheckRunEventModel.parse_raw(data_path.read_text())

    assert data.action == "created"
    assert data.check_run.id == "128620228"
    assert data.check_run.external_id == ""
    assert data.check_run.url == (
        "https://api.github.com/repos/Codertocat/Hello-World"
        "/check-runs/128620228"
    )
    assert data.check_run.html_url == (
        "https://github.com/Codertocat/Hello-World/runs/128620228"
    )
    assert data.check_run.status == GitHubCheckRunStatus.queued
    assert data.check_run.check_suite.id == "118578147"
