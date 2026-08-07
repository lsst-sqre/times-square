"""Tests for the process context and factory."""

from __future__ import annotations

import pytest
import structlog
from gidgethub.httpx import GitHubAPI
from httpx import Timeout
from safir.database import create_database_engine
from safir.github import GitHubAppClientFactory

from timessquare.config import Config, config
from timessquare.domain.executionoutcome import (
    NotebookExecutionErrorCode,
    NotebookExecutionFailure,
)
from timessquare.domain.page import PageInstanceIdModel
from timessquare.factory import Factory, ProcessContext


def test_http_client_timeout_default() -> None:
    """The HTTP client timeout config defaults to 30 seconds."""
    assert config.http_client_timeout == 30


def test_execution_failure_lifetime_default() -> None:
    """The execution-failure lifetime config defaults to 600 seconds."""
    assert config.execution_failure_lifetime == 600


def test_execution_failure_lifetime_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The execution-failure lifetime is set from the environment."""
    monkeypatch.setenv("TS_EXECUTION_FAILURE_LIFETIME", "1200")
    assert Config().execution_failure_lifetime == 1200


@pytest.mark.asyncio
async def test_process_context_http_client_timeout() -> None:
    """ProcessContext.create() builds the shared client with the configured
    timeout.
    """
    process_context = await ProcessContext.create()
    try:
        assert process_context.http_client.timeout == Timeout(
            config.http_client_timeout
        )
    finally:
        await process_context.aclose()


@pytest.mark.asyncio
async def test_execution_failure_store_lifetime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Factory.create_nb_execution_failure_store() builds a store that caches
    failures with the configured lifetime.
    """
    monkeypatch.setattr(config, "execution_failure_lifetime", 42)
    logger = structlog.get_logger(config.logger_name)
    engine = create_database_engine(
        config.database_url, config.database_password.get_secret_value()
    )
    async with Factory.create_standalone(
        logger=logger, engine=engine
    ) as factory:
        store = factory.create_nb_execution_failure_store()
        page_id = PageInstanceIdModel(
            name="factory-lifetime", parameter_values={"a": "1"}
        )
        await store.store_failure(
            failure=NotebookExecutionFailure(
                code=NotebookExecutionErrorCode.timeout,
                title="Notebook execution timeout",
                message="The notebook execution timed out.",
            ),
            page_id=page_id,
        )
        ttl = await factory.redis.ttl(f"execution-failure/{page_id.cache_key}")
        assert 0 < ttl <= 42
    await engine.dispose()


@pytest.mark.asyncio
async def test_repo_service_authenticates_by_installation_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A GitHubRepoService built from a webhook payload's installation ID
    authenticates as that installation directly, rather than resolving the
    installation from owner/repo name strings that a rename invalidates.
    """
    monkeypatch.setattr(config, "github_app_id", 12345)

    installation_ids: list[int] = []

    async def _by_id(
        self: GitHubAppClientFactory, installation_id: int
    ) -> GitHubAPI:
        installation_ids.append(installation_id)
        return self.create_anonymous_client()

    async def _by_name(
        self: GitHubAppClientFactory, owner: str, repo: str
    ) -> GitHubAPI:
        raise AssertionError(
            "The installation must not be resolved by repository name."
        )

    monkeypatch.setattr(
        GitHubAppClientFactory, "create_installation_client", _by_id
    )
    monkeypatch.setattr(
        GitHubAppClientFactory, "create_installation_client_for_repo", _by_name
    )

    logger = structlog.get_logger(config.logger_name)
    engine = create_database_engine(
        config.database_url, config.database_password.get_secret_value()
    )
    async with Factory.create_standalone(
        logger=logger, engine=engine
    ) as factory:
        await factory.create_github_repo_service_for_installation(
            installation_id=4242
        )
    await engine.dispose()

    assert installation_ids == [4242]
