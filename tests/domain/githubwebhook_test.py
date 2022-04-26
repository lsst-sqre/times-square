"""Tests for Github webhook domain models."""

from __future__ import annotations

from pathlib import Path

from timessquare.domain.githubwebhook import GitHubPushEventModel


def test_push_event() -> None:
    data_path = Path(__file__).parent.joinpath(
        "../data/github_webhooks/push_event.json"
    )
    data = GitHubPushEventModel.parse_raw(data_path.read_text())

    assert data.ref == "refs/tags/simple-tag"
    assert data.repository.name == "Hello-World"
