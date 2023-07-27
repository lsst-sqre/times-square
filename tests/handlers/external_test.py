"""Tests for the timessquare.handlers.external module and routes."""

from __future__ import annotations

import pytest
import structlog
from gidgethub.routing import Router
from gidgethub.sansio import Event
from httpx import AsyncClient
from pytest_mock import MockerFixture
from safir.arq import MockArqQueue
from safir.github import GitHubAppClientFactory
from structlog.stdlib import BoundLogger

from tests.support.github import SAMPLE_PRIVATE_KEY, MockGitHubAPI
from timessquare.config import config
from timessquare.handlers.external.githubwebhooks import (
    filter_installation_owner,
)


@pytest.mark.asyncio
async def test_get_index(client: AsyncClient) -> None:
    """Test ``GET /` for the external API."""
    response = await client.get(f"{config.path_prefix}/")
    assert response.status_code == 200
    data = response.json()
    metadata = data["metadata"]
    assert metadata["name"] == config.name
    assert isinstance(metadata["version"], str)
    assert isinstance(metadata["description"], str)
    assert isinstance(metadata["repository_url"], str)
    assert isinstance(metadata["documentation_url"], str)

    docs_url = data["api_docs"]
    docs_response = await client.get(docs_url)
    assert docs_response.status_code == 200


@pytest.mark.asyncio
async def test_filter_installation_owner(
    mocker: MockerFixture, http_client: AsyncClient
) -> None:
    """Test the ``filter_installation_owner`` decoration."""

    class MockInstallationGitHubApi(MockGitHubAPI):
        """A mock github client api that returns a canned response."""

        def set_response(self, response: dict) -> None:
            self._response = response

        def create_response(
            self, method: str, url: str, request_json: dict | None
        ) -> tuple[int, dict, dict]:
            return 200, self._response, {}

    mock_github_client = MockInstallationGitHubApi()

    mock_client_factory = GitHubAppClientFactory(
        id="1234",
        key=SAMPLE_PRIVATE_KEY,
        name="lsst-sqre/times-square",
        http_client=http_client,
    )
    mocker.patch.object(
        mock_client_factory,
        "create_anonymous_client",
    ).return_value = mock_github_client

    router = Router()
    called = False
    logger = structlog.get_logger(__name__)

    @router.register("push")
    @filter_installation_owner
    async def push_handler(
        event: Event,
        logger: BoundLogger,
        arq_queue: MockArqQueue,
        github_client_factory: GitHubAppClientFactory,
    ) -> None:
        nonlocal called
        called = True

    event = Event(
        {"installation": {"id": 1234}},
        event="push",
        delivery_id="1234",
    )
    mock_github_client.set_response({"account": {"login": "lsst-sqre"}})
    await router.dispatch(event, logger, MockArqQueue(), mock_client_factory)
    assert called is True

    event = Event(
        {"installation": {"id": 5678}},
        event="push",
        delivery_id="1234",
    )
    called = False  # Reset

    mock_github_client.set_response({"account": {"login": "foo"}})
    await router.dispatch(event, logger, MockArqQueue(), mock_client_factory)
    assert called is False
