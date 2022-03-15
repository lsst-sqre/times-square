"""Tests for adding and managing pages with the /v1/ API."""

from __future__ import annotations

from datetime import datetime
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
    page_req_data = {"name": "demo", "ipynb": demo_path.read_text()}

    r = await client.post(f"{config.path_prefix}/v1/pages", json=page_req_data)
    assert r.status_code == 201
    page_url = r.headers["location"]
    assert page_url == "https://example.com/times-square/v1/pages/demo"
    data = r.json()
    assert data["name"] == "demo"
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
        "y0": {"type": "number", "description": "Y-axis offset", "default": 0},
        "lambd": {
            "type": "number",
            "minimum": 0,
            "description": "Wavelength",
            "default": 2,
        },
    }

    # List page summaries
    r = await client.get(f"{config.path_prefix}/v1/pages")
    assert r.status_code == 200
    pages_data = r.json()
    assert len(pages_data) == 1
    assert pages_data[0]["name"] == "demo"
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
    assert "metadata" in source_notebook_data.keys()  # check it's a notebook

    # Try getting a page that doesn't exist
    r = await client.get(
        f"{config.path_prefix}/v1/pages/my-page",
    )
    assert r.status_code == 404

    # Try adding an invalid notebook (bad parameters)
    invalid_demo_path = data_path / "demo-invalid-params.ipynb"
    r = await client.post(
        f"{config.path_prefix}/v1/pages",
        json={"name": "demo-invalid", "ipynb": invalid_demo_path.read_text()},
    )
    assert r.status_code == 422
    error_data = r.json()
    assert error_data["detail"][0]["type"] == "parameter_default_invalid"
    assert error_data["detail"][0]["name"] == "A"
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
        "- Wavelength: lambd = 2"
    )
    assert notebook.metadata["times-square"]["values"] == {
        "A": 4,
        "y0": 0,
        "lambd": 2,
    }

    # Render the page template with some parameters set
    r = await client.get(rendered_url, params={"A": 2})
    assert r.status_code == 200
    notebook = nbformat.reads(r.text, as_version=4)
    assert notebook.cells[0].source == (
        "# Times Square demo\n"
        "\n"
        "Plot parameters:\n"
        "\n"
        "- Amplitude: A = 2\n"
        "- Y offset: y0 = 0\n"
        "- Wavelength: lambd = 2"
    )
    assert notebook.metadata["times-square"]["values"] == {
        "A": 2,
        "y0": 0,
        "lambd": 2,
    }

    # Try to get HTML rendering; should be unavailable right now.
    respx_mock.post("https://test.example.com/noteburst/v1/notebooks/").mock(
        return_value=Response(
            202,
            json={
                "job_id": "xyz",
                "kernel_name": "LSST",
                "enqueue_time": datetime.utcnow().isoformat(),
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
                "kernel_name": "LSST",
                "enqueue_time": datetime.utcnow().isoformat(),
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
                "kernel_name": "LSST",
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
