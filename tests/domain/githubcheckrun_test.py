"""Tests for the githubcheckrun domain, focused on graceful handling of
transient GitHub errors during repository checkout.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import cast

import httpx
import pytest
from gidgethub.httpx import GitHubAPI
from safir.github.models import GitHubCheckRunConclusion
from safir.github.webhooks import GitHubCheckSuiteEventModel

from timessquare.domain.githubcheckrun import (
    TRANSIENT_CHECKOUT_ERROR_MESSAGE,
    GitHubConfigsCheck,
)
from timessquare.storage.github.retry import MAX_ATTEMPTS

from ..support.github import MockGitHubCheckRunAPI

DATA = Path(__file__).parent.joinpath("../data/github_webhooks")


def _load_check_suite() -> GitHubCheckSuiteEventModel:
    payload = json.loads((DATA / "check_suite_completed.json").read_text())
    return GitHubCheckSuiteEventModel.model_validate(payload)


def _load_check_run() -> dict:
    return json.loads((DATA / "check_run_created.json").read_text())[
        "check_run"
    ]


@pytest.fixture(autouse=True)
def _instant_backoff(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make retry backoff instantaneous so tests do not actually wait."""
    monkeypatch.setattr(
        "timessquare.storage.github.retry._backoff_delay",
        lambda _attempt: 0.0,
    )


@pytest.mark.asyncio
async def test_validate_repo_concludes_on_transient_error() -> None:
    """A persistent transient checkout failure concludes the config check
    with a ``failure`` conclusion carrying the actionable re-run message,
    and no exception propagates.
    """
    payload = _load_check_suite()
    mock = MockGitHubCheckRunAPI(
        check_run=_load_check_run(),
        contents_error=httpx.ReadTimeout("slow"),
    )
    client = cast("GitHubAPI", mock)

    check = await GitHubConfigsCheck.create_check_run_and_validate(
        github_client=client,
        repo=payload.repository,
        head_sha=payload.check_suite.head_sha,
    )
    await check.submit_conclusion(github_client=client)

    # The check concluded as a failure with the actionable message.
    assert check.conclusion == GitHubCheckRunConclusion.failure
    assert any(
        a.message == TRANSIENT_CHECKOUT_ERROR_MESSAGE
        for a in check.annotations
    )

    # The times-square.yaml GET was retried up to the retry budget.
    contents_gets = [
        req
        for req in mock.requests
        if req[0] == "GET" and "times-square.yaml" in req[1]
    ]
    assert len(contents_gets) == MAX_ATTEMPTS

    # The final PATCH posted a failure conclusion to GitHub.
    assert mock.patched[-1]["conclusion"] == GitHubCheckRunConclusion.failure


@pytest.mark.asyncio
async def test_validate_repo_concludes_on_transient_tree_error() -> None:
    """A transient failure in the git tree read after a successful checkout
    also concludes the config check with a ``failure`` conclusion instead of
    leaving it dangling ``in_progress``.
    """
    payload = _load_check_suite()
    mock = MockGitHubCheckRunAPI(
        check_run=_load_check_run(),
        tree_error=httpx.ReadTimeout("slow"),
    )
    client = cast("GitHubAPI", mock)

    check = await GitHubConfigsCheck.create_check_run_and_validate(
        github_client=client,
        repo=payload.repository,
        head_sha=payload.check_suite.head_sha,
    )
    await check.submit_conclusion(github_client=client)

    # The check concluded as a failure with the actionable message.
    assert check.conclusion == GitHubCheckRunConclusion.failure
    assert any(
        a.message == TRANSIENT_CHECKOUT_ERROR_MESSAGE
        for a in check.annotations
    )

    # The tree GET was retried up to the retry budget.
    tree_gets = [
        req
        for req in mock.requests
        if req[0] == "GET" and "git/trees" in req[1]
    ]
    assert len(tree_gets) == MAX_ATTEMPTS

    # The final PATCH posted a failure conclusion to GitHub.
    assert mock.patched[-1]["conclusion"] == GitHubCheckRunConclusion.failure


@pytest.mark.asyncio
async def test_validate_repo_propagates_non_transient_error() -> None:
    """A non-transient, unexpected error during checkout still propagates so
    the worker's Slack alert fires (behavior unchanged for real errors).
    """
    payload = _load_check_suite()
    mock = MockGitHubCheckRunAPI(
        check_run=_load_check_run(),
        contents_error=RuntimeError("unexpected"),
    )

    with pytest.raises(RuntimeError, match="unexpected"):
        await GitHubConfigsCheck.create_check_run_and_validate(
            github_client=cast("GitHubAPI", mock),
            repo=payload.repository,
            head_sha=payload.check_suite.head_sha,
        )
