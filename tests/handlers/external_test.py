"""Tests for the timessquare.handlers.external module and routes."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import structlog
from gidgethub.routing import Router
from gidgethub.sansio import Event
from httpx import AsyncClient
from pytest_mock import MockerFixture
from safir.arq import MockArqQueue
from safir.github import GitHubAppClientFactory
from structlog.stdlib import BoundLogger
from structlog.testing import capture_logs

from tests.support.arq import RecordingArqQueue
from tests.support.github import SAMPLE_PRIVATE_KEY, MockGitHubAPI
from timessquare.config import config
from timessquare.handlers.external.githubwebhooks import (
    filter_installation_owner,
)
from timessquare.handlers.external.githubwebhooks import (
    router as webhook_router,
)

DATA = Path(__file__).parent / ".." / "data" / "github_webhooks"


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
        id=1234,
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


def _client_factory_for_owner(
    mocker: MockerFixture, http_client: AsyncClient, owner: str
) -> GitHubAppClientFactory:
    """Build a client factory whose installation lookup resolves to ``owner``,
    which is what ``filter_installation_owner`` gates events on.
    """

    class OwnerGitHubAPI(MockGitHubAPI):
        def create_response(
            self, method: str, url: str, request_json: dict | None
        ) -> tuple[int, dict, dict]:
            return 200, {"account": {"login": owner}}, {}

    factory = GitHubAppClientFactory(
        id=1234,
        key=SAMPLE_PRIVATE_KEY,
        name="lsst-sqre/times-square",
        http_client=http_client,
    )
    mocker.patch.object(
        factory, "create_anonymous_client"
    ).return_value = OwnerGitHubAPI()
    return factory


@pytest.mark.asyncio
async def test_handle_repository_renamed(
    mocker: MockerFixture, http_client: AsyncClient
) -> None:
    """A ``repository`` (renamed) webhook enqueues a ``repo_renamed`` task
    carrying the parsed payload.
    """
    payload = json.loads((DATA / "repository_renamed.json").read_text())
    event = Event(payload, event="repository", delivery_id="1234")
    arq_queue = RecordingArqQueue()

    await webhook_router.dispatch(
        event,
        structlog.get_logger(__name__),
        arq_queue,
        _client_factory_for_owner(mocker, http_client, "lsst-sqre"),
    )

    assert len(arq_queue.calls) == 1
    task_name, task_kwargs = arq_queue.calls[0]
    assert task_name == "repo_renamed"
    enqueued = task_kwargs["payload"]
    assert enqueued.old_repo_name == "Hello-World"
    assert enqueued.repository.name == "Hello-World-Renamed"
    assert enqueued.repository.id == 186853002


@pytest.mark.asyncio
async def test_handle_repository_renamed_unaccepted_org(
    mocker: MockerFixture, http_client: AsyncClient
) -> None:
    """A rename from an organization outside the allowlist is ignored."""
    payload = json.loads((DATA / "repository_renamed.json").read_text())
    event = Event(payload, event="repository", delivery_id="1234")
    arq_queue = RecordingArqQueue()

    await webhook_router.dispatch(
        event,
        structlog.get_logger(__name__),
        arq_queue,
        _client_factory_for_owner(mocker, http_client, "not-accepted"),
    )

    assert arq_queue.calls == []


def _installation_target_renamed_payload(
    *, old_login: str, new_login: str
) -> dict:
    """Re-point the recorded installation target rename fixture at a given
    pair of old and new logins.
    """
    payload = json.loads(
        (DATA / "installation_target_renamed.json").read_text()
    )
    payload["changes"]["login"]["from"] = old_login
    payload["account"]["login"] = new_login
    return payload


@pytest.mark.asyncio
async def test_handle_installation_target_renamed_old_login_accepted(
    mocker: MockerFixture, http_client: AsyncClient
) -> None:
    """An ``installation_target`` (renamed) webhook is processed when only the
    *old* login is in the allowlist, which is the normal case:
    ``TS_GITHUB_ORGS`` still names the account Times Square knew before the
    rename.

    The client factory here resolves to an unaccepted owner to prove the gate
    reads the payload's logins rather than the installation's account.
    """
    payload = _installation_target_renamed_payload(
        old_login="lsst-sqre", new_login="lsst-so"
    )
    event = Event(payload, event="installation_target", delivery_id="1234")
    arq_queue = RecordingArqQueue()

    await webhook_router.dispatch(
        event,
        structlog.get_logger(__name__),
        arq_queue,
        _client_factory_for_owner(mocker, http_client, "not-accepted"),
    )

    assert len(arq_queue.calls) == 1
    task_name, task_kwargs = arq_queue.calls[0]
    assert task_name == "owner_renamed"
    enqueued = task_kwargs["payload"]
    assert enqueued.old_login == "lsst-sqre"
    assert enqueued.new_login == "lsst-so"
    assert enqueued.account.id == 30830384


@pytest.mark.asyncio
async def test_handle_installation_target_renamed_new_login_accepted(
    mocker: MockerFixture, http_client: AsyncClient
) -> None:
    """An ``installation_target`` (renamed) webhook is processed when only the
    *new* login is in the allowlist, which is the case when an operator
    updated ``TS_GITHUB_ORGS`` ahead of the rename.
    """
    payload = _installation_target_renamed_payload(
        old_login="lsst-sitcom", new_login="lsst-sqre"
    )
    event = Event(payload, event="installation_target", delivery_id="1234")
    arq_queue = RecordingArqQueue()

    await webhook_router.dispatch(
        event,
        structlog.get_logger(__name__),
        arq_queue,
        _client_factory_for_owner(mocker, http_client, "not-accepted"),
    )

    assert len(arq_queue.calls) == 1
    task_name, task_kwargs = arq_queue.calls[0]
    assert task_name == "owner_renamed"
    assert task_kwargs["payload"].old_login == "lsst-sitcom"


@pytest.mark.asyncio
async def test_handle_installation_target_renamed_neither_login_accepted(
    mocker: MockerFixture, http_client: AsyncClient
) -> None:
    """A rename where neither login is in the allowlist is ignored, with a
    debug log rather than an enqueued task.
    """
    payload = _installation_target_renamed_payload(
        old_login="lsst-sitcom", new_login="lsst-so"
    )
    event = Event(payload, event="installation_target", delivery_id="1234")
    arq_queue = RecordingArqQueue()

    with capture_logs() as logs:
        await webhook_router.dispatch(
            event,
            structlog.get_logger(__name__),
            arq_queue,
            _client_factory_for_owner(mocker, http_client, "lsst-sqre"),
        )

    assert arq_queue.calls == []
    assert [entry["log_level"] for entry in logs] == ["debug"]


@pytest.mark.asyncio
async def test_handle_installation_target_renamed_without_login_change(
    mocker: MockerFixture, http_client: AsyncClient
) -> None:
    """GitHub does not mark ``changes.login`` as required, so a payload with
    no login change is ignored rather than enqueuing a task that has no old
    login to rename pages from.
    """
    payload = _installation_target_renamed_payload(
        old_login="lsst-sqre", new_login="lsst-so"
    )
    payload["changes"] = {"slug": {"from": "old-slug"}}
    event = Event(payload, event="installation_target", delivery_id="1234")
    arq_queue = RecordingArqQueue()

    with capture_logs() as logs:
        await webhook_router.dispatch(
            event,
            structlog.get_logger(__name__),
            arq_queue,
            _client_factory_for_owner(mocker, http_client, "lsst-sqre"),
        )

    assert arq_queue.calls == []
    assert [entry["log_level"] for entry in logs] == ["debug"]


@pytest.mark.asyncio
async def test_handle_repository_transferred(
    mocker: MockerFixture, http_client: AsyncClient
) -> None:
    """A ``repository`` (transferred) webhook enqueues a ``repo_transferred``
    task carrying the parsed payload.
    """
    payload = json.loads((DATA / "repository_transferred.json").read_text())
    event = Event(payload, event="repository", delivery_id="1234")
    arq_queue = RecordingArqQueue()

    await webhook_router.dispatch(
        event,
        structlog.get_logger(__name__),
        arq_queue,
        _client_factory_for_owner(mocker, http_client, "lsst-sqre"),
    )

    assert len(arq_queue.calls) == 1
    task_name, task_kwargs = arq_queue.calls[0]
    assert task_name == "repo_transferred"
    enqueued = task_kwargs["payload"]
    assert enqueued.old_owner_login == "Codertocat"
    assert enqueued.repository.owner.login == "lsst-sqre"
    assert enqueued.repository.owner.id == 30830384
    assert enqueued.repository.name == "times-square-demo"
    assert enqueued.repository.id == 186853002


@pytest.mark.asyncio
async def test_handle_repository_transferred_unaccepted_org(
    mocker: MockerFixture, http_client: AsyncClient
) -> None:
    """A transfer to an owner outside the allowlist is still enqueued: the
    repository has left Times Square's remit, and the worker task is what
    soft-deletes its pages.
    """
    payload = json.loads((DATA / "repository_transferred.json").read_text())
    payload["repository"]["owner"]["login"] = "not-accepted"
    event = Event(payload, event="repository", delivery_id="1234")
    arq_queue = RecordingArqQueue()

    await webhook_router.dispatch(
        event,
        structlog.get_logger(__name__),
        arq_queue,
        _client_factory_for_owner(mocker, http_client, "not-accepted"),
    )

    assert len(arq_queue.calls) == 1
    assert arq_queue.calls[0][0] == "repo_transferred"
