"""Tests for adding and managing pages with the /v1/ API."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timezone
from pathlib import Path

import nbformat
import pytest
import respx
from httpx import AsyncClient, Response

from timessquare.config import config


@pytest.mark.asyncio
async def test_pages(client: AsyncClient, respx_mock: respx.Router) -> None:
    """Test creating and managing pages."""
    data_path = Path(__file__).parent.joinpath("../../data")
    demo_path = data_path / "demo.ipynb"
    page_req_data = {"title": "Demo", "ipynb": demo_path.read_text()}

    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=Response(
            202,
            json={
                "job_id": "xyz",
                "kernel_name": "",
                "enqueue_time": datetime.now(tz=UTC).isoformat(),
                "status": "queued",
                "self_url": (
                    "https://test.example.com/noteburst/v1/notebooks/xyz"
                ),
            },
        )
    )

    r = await client.post(f"{config.path_prefix}/v1/pages", json=page_req_data)
    assert r.status_code == 201
    page_url = r.headers["location"]
    data = r.json()
    assert page_url == (
        f"https://example.com/times-square/v1/pages/{data['name']}"
    )
    assert data["self_url"] == page_url
    source_url = data["source_url"]
    rendered_url = data["rendered_url"]
    html_url = data["html_url"]
    html_status_url = data["html_status_url"]

    assert data["parameters"] == {
        "A": {
            "type": "number",
            "minimum": 0,
            "description": "Amplitude",
            "default": 4,
        },
        "boolflag": {
            "type": "boolean",
            "description": "A boolean flag",
            "default": True,
        },
        "lambd": {
            "type": "number",
            "minimum": 0,
            "description": "Wavelength",
            "default": 2,
        },
        "mydate": {
            "type": "string",
            "description": "A date value",
            "format": "date",
            "default": "2025-02-21",
        },
        "mydatetime": {
            "type": "string",
            "description": "A datetime value",
            "format": "date-time",
            "default": "2025-02-22T12:00:00+00:00",
        },
        "title": {
            "default": "hello world",
            "description": "A string value",
            "type": "string",
        },
        "y0": {"type": "number", "description": "Y-axis offset", "default": 0},
    }

    # List page summaries
    r = await client.get(f"{config.path_prefix}/v1/pages")
    assert r.status_code == 200
    pages_data = r.json()
    assert len(pages_data) == 1
    assert pages_data[0]["title"] == "Demo"
    assert pages_data[0]["self_url"] == page_url

    # Get the page resource itself
    r = await client.get(page_url)
    assert r.status_code == 200
    data2 = r.json()
    assert data == data2

    r = await client.get(source_url)
    assert r.status_code == 200
    assert r.headers["location"] == source_url
    source_notebook_data = r.json()
    assert "metadata" in source_notebook_data  # check it's a notebook

    # Try getting a page that doesn't exist
    r = await client.get(
        f"{config.path_prefix}/v1/pages/my-page",
    )
    assert r.status_code == 404

    # Try adding an invalid notebook (bad parameters)
    invalid_demo_path = data_path / "demo-invalid-params.ipynb"
    r = await client.post(
        f"{config.path_prefix}/v1/pages",
        json={"title": "demo-invalid", "ipynb": invalid_demo_path.read_text()},
    )
    assert r.status_code == 422
    error_data = r.json()
    assert error_data["detail"][0]["type"] == "parameter_default_invalid"
    assert error_data["detail"][0]["msg"] == (
        "Parameter A's default is invalid: -1."
    )

    # Render the page template with defaults
    r = await client.get(rendered_url)
    assert r.status_code == 200
    notebook = nbformat.reads(r.text, as_version=4)
    assert notebook.cells[0].source == (
        "# Times Square demo\n"
        "\n"
        "Plot parameters:\n"
        "\n"
        "- Amplitude: A = 4\n"
        "- Y offset: y0 = 0\n"
        "- Wavelength: lambd = 2\n"
        "- Title: hello world\n"
        "- Flag: True"
    )
    assert notebook.metadata["times-square"]["values"] == {
        "A": 4,
        "y0": 0,
        "lambd": 2,
        "mydate": "2025-02-21",
        "mydatetime": "2025-02-22T12:00:00+00:00",
        "title": "hello world",
        "boolflag": True,
    }

    # Render the page template with some parameters set
    r = await client.get(
        rendered_url,
        params={
            "A": 2,
            "boolflag": False,
            "mydate": "2025-05-01",
            "mydatetime": "2025-05-01T12:00:00+00:00",
        },
    )
    assert r.status_code == 200
    notebook = nbformat.reads(r.text, as_version=4)
    assert notebook.cells[0].source == (
        "# Times Square demo\n"
        "\n"
        "Plot parameters:\n"
        "\n"
        "- Amplitude: A = 2\n"
        "- Y offset: y0 = 0\n"
        "- Wavelength: lambd = 2\n"
        "- Title: hello world\n"
        "- Flag: False"
    )
    assert notebook.metadata["times-square"]["values"] == {
        "A": 2,
        "y0": 0,
        "lambd": 2,
        "mydate": "2025-05-01",
        "mydatetime": "2025-05-01T12:00:00+00:00",
        "title": "hello world",
        "boolflag": False,
    }
    assert "kernelspec" not in notebook.metadata

    # Try to get HTML rendering; should be unavailable right now.
    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=Response(
            202,
            json={
                "job_id": "xyz",
                "kernel_name": "",
                "enqueue_time": datetime.now(tz=UTC).isoformat(),
                "status": "queued",
                "self_url": (
                    "https://test.example.com/noteburst/v1/notebooks/xyz"
                ),
            },
        )
    )
    r = await client.get(html_url, params={"A": 2})
    assert r.status_code == 404

    # Check the htmlstatus
    respx_mock.get("https://test.example.com/noteburst/v1/notebooks/xyz").mock(
        return_value=Response(
            200,
            json={
                "job_id": "xyz",
                "kernel_name": "",
                "enqueue_time": datetime.now(tz=UTC).isoformat(),
                "status": "queued",
                "self_url": (
                    "https://test.example.com/noteburst/v1/notebooks/xyz"
                ),
            },
        )
    )
    r = await client.get(html_status_url, params={"A": 2})
    assert r.status_code == 200
    data = r.json()
    assert data["available"] is False

    # Try to get noteburst job while still queued
    respx_mock.get("https://test.example.com/noteburst/v1/notebooks/xyz").mock(
        return_value=Response(
            200,
            json={
                "job_id": "xyz",
                "kernel_name": "",
                "enqueue_time": datetime.now(tz=UTC).isoformat(),
                "status": "queued",
                "self_url": (
                    "https://test.example.com/noteburst/v1/notebooks/xyz"
                ),
            },
        )
    )
    r = await client.get(html_url, params={"A": 2})
    assert r.status_code == 404

    # Get completed noteburst job
    respx_mock.get("https://test.example.com/noteburst/v1/notebooks/xyz").mock(
        return_value=Response(
            200,
            json={
                "job_id": "xyz",
                "kernel_name": "",
                "enqueue_time": "2022-03-15T04:12:00Z",
                "status": "complete",
                "self_url": (
                    "https://test.example.com/noteburst/v1/notebooks/xyz"
                ),
                "start_time": "2022-03-15T04:13:00Z",
                "finish_time": "2022-03-15T04:13:10Z",
                "success": True,
                "ipynb": demo_path.read_text(),
            },
        )
    )
    r = await client.get(html_url, params={"A": 2})
    assert r.status_code == 200

    # Check the htmlstatus
    r = await client.get(html_status_url, params={"A": 2})
    assert r.status_code == 200
    data = r.json()
    assert data["available"] is True


@pytest.mark.asyncio
async def test_dynamic_default_handling(
    client: AsyncClient,
    respx_mock: respx.Router,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that dynamic defaults are resolved when accessing pages."""

    # Mock datetime.now to return a fixed date: May 2, 2025 12:00:00 UTC
    class MockDatetime:
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            return datetime(2025, 5, 2, 12, 0, 0, tzinfo=tz)

    # Mock the noteburst response
    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=Response(
            202,
            json={
                "job_id": "xyz",
                "kernel_name": "",
                "enqueue_time": datetime.now(tz=UTC).isoformat(),
                "status": "queued",
                "self_url": (
                    "https://test.example.com/noteburst/v1/notebooks/xyz"
                ),
            },
        )
    )

    # Create a notebook with a dynamic default parameter
    notebook_content = {
        "cells": [
            {
                "cell_type": "markdown",
                "id": "test-cell",
                "metadata": {},
                "source": ["# Test notebook with dynamic date"],
            }
        ],
        "metadata": {
            "times-square": {
                "parameters": {
                    "date": {
                        "type": "string",
                        "format": "date",
                        "description": "A date parameter with dynamic default",
                        "X-Dynamic-Default": "yesterday",
                    }
                }
            }
        },
        "nbformat": 4,
        "nbformat_minor": 5,
    }

    page_req_data = {
        "title": "Dynamic Default Test",
        "ipynb": json.dumps(notebook_content),
    }

    with monkeypatch.context() as m:
        m.setattr(
            "timessquare.domain.pageparameters._datedynamicdefault.datetime",
            MockDatetime,
        )

        # Add the page
        r = await client.post(
            f"{config.path_prefix}/v1/pages", json=page_req_data
        )
        assert r.status_code == 201
        page_url = r.headers["location"]

        # Access the page resource
        r = await client.get(page_url)
        assert r.status_code == 200
        data = r.json()

        # Check that the date parameter has the resolved default value
        date_param = data["parameters"]["date"]
        # yesterday from 2025-05-02
        assert date_param["default"] == "2025-05-01"
        assert date_param["type"] == "string"
        assert date_param["format"] == "date"
        assert date_param["description"] == (
            "A date parameter with dynamic default"
        )
        # The X-Dynamic-Default field should not be present in the response
        assert "X-Dynamic-Default" not in date_param
