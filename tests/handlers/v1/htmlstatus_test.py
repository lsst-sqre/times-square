"""Tests for the htmlstatus endpoint's execution-failure handling."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
import respx
from httpx import AsyncClient, Response

from timessquare.config import config

NOTEBURST_URL = "https://test.example.com/noteburst/v1/notebooks/"
JOB_URL = "https://test.example.com/noteburst/v1/notebooks/xyz"


def _queued_post_response() -> Response:
    return Response(
        202,
        json={
            "job_id": "xyz",
            "kernel_name": "",
            "enqueue_time": datetime.now(tz=UTC).isoformat(),
            "status": "queued",
            "self_url": JOB_URL,
        },
    )


async def _create_page(client: AsyncClient) -> dict[str, str]:
    data_path = Path(__file__).parent.joinpath("../../data")
    demo_path = data_path / "demo.ipynb"
    page_req_data = {"title": "Demo", "ipynb": demo_path.read_text()}
    r = await client.post(f"{config.path_prefix}/v1/pages", json=page_req_data)
    assert r.status_code == 201
    return r.json()


@pytest.mark.asyncio
async def test_htmlstatus_execution_failure(
    client: AsyncClient, respx_mock: respx.Router
) -> None:
    """A terminal Noteburst execution failure surfaces as 200 with
    execution_error, and does not trigger a re-execution storm.
    """
    post_route = respx_mock.post(NOTEBURST_URL).mock(
        return_value=_queued_post_response()
    )

    data = await _create_page(client)
    html_status_url = data["html_status_url"]

    # First poll for a fresh page instance (A=2) requests a new execution.
    respx_mock.get(JOB_URL).mock(return_value=_queued_post_response())
    r = await client.get(html_status_url, params={"A": 2})
    assert r.status_code == 200
    assert r.json()["available"] is False
    post_count_after_request = post_route.call_count

    # Noteburst now reports a terminal execution failure (timeout).
    respx_mock.get(JOB_URL).mock(
        return_value=Response(
            200,
            json={
                "job_id": "xyz",
                "kernel_name": "",
                "enqueue_time": "2022-03-15T04:12:00Z",
                "status": "complete",
                "self_url": JOB_URL,
                "start_time": "2022-03-15T04:13:00Z",
                "finish_time": "2022-03-15T04:13:10Z",
                "success": False,
                "ipynb": None,
                "timeout": 30.0,
                "error": {"code": "timeout", "message": "timed out"},
            },
        )
    )
    r = await client.get(html_status_url, params={"A": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["execution_error"] is not None
    assert body["execution_error"]["code"] == "timeout"
    assert body["execution_error"]["message"]
    post_count_after_failure = post_route.call_count

    # A subsequent poll must not request a new execution (re-execution guard).
    r = await client.get(html_status_url, params={"A": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["execution_error"]["code"] == "timeout"
    assert post_route.call_count == post_count_after_failure
    # And no new execution was requested when the failure was first observed.
    assert post_count_after_failure == post_count_after_request


@pytest.mark.asyncio
async def test_htmlstatus_result_expiry(
    client: AsyncClient, respx_mock: respx.Router
) -> None:
    """A success=None (arq result expiry) result is a terminal failure."""
    respx_mock.post(NOTEBURST_URL).mock(return_value=_queued_post_response())

    data = await _create_page(client)
    html_status_url = data["html_status_url"]

    respx_mock.get(JOB_URL).mock(return_value=_queued_post_response())
    r = await client.get(html_status_url, params={"A": 3})
    assert r.status_code == 200

    respx_mock.get(JOB_URL).mock(
        return_value=Response(
            200,
            json={
                "job_id": "xyz",
                "kernel_name": "",
                "enqueue_time": "2022-03-15T04:12:00Z",
                "status": "complete",
                "self_url": JOB_URL,
                "start_time": "2022-03-15T04:13:00Z",
                "finish_time": "2022-03-15T04:13:10Z",
                "success": None,
                "ipynb": None,
            },
        )
    )
    r = await client.get(html_status_url, params={"A": 3})
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["execution_error"]["code"] == "result_unavailable"


@pytest.mark.asyncio
async def test_htmlstatus_normal_is_backward_compatible(
    client: AsyncClient, respx_mock: respx.Router
) -> None:
    """execution_error is null in the normal pending case."""
    respx_mock.post(NOTEBURST_URL).mock(return_value=_queued_post_response())
    respx_mock.get(JOB_URL).mock(return_value=_queued_post_response())

    data = await _create_page(client)
    html_status_url = data["html_status_url"]

    r = await client.get(html_status_url, params={"A": 2})
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert body["execution_error"] is None


@pytest.mark.asyncio
async def test_htmlstatus_contract_violation(
    client: AsyncClient, respx_mock: respx.Router
) -> None:
    """The impossible success=true + ipynb=None state raises a hard error."""
    respx_mock.post(NOTEBURST_URL).mock(return_value=_queued_post_response())

    data = await _create_page(client)
    html_status_url = data["html_status_url"]

    respx_mock.get(JOB_URL).mock(return_value=_queued_post_response())
    r = await client.get(html_status_url, params={"A": 4})
    assert r.status_code == 200

    respx_mock.get(JOB_URL).mock(
        return_value=Response(
            200,
            json={
                "job_id": "xyz",
                "kernel_name": "",
                "enqueue_time": "2022-03-15T04:12:00Z",
                "status": "complete",
                "self_url": JOB_URL,
                "start_time": "2022-03-15T04:13:00Z",
                "finish_time": "2022-03-15T04:13:10Z",
                "success": True,
                "ipynb": None,
            },
        )
    )
    with pytest.raises(RuntimeError):
        await client.get(html_status_url, params={"A": 4})
