"""Tests for adding and managing pages with the /v1/ API."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import nbformat
import pytest

from timessquare.config import config

if TYPE_CHECKING:
    from httpx import AsyncClient


@pytest.mark.asyncio
async def test_pages(client: AsyncClient) -> None:
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
    r = await client.get(f"{page_url}/rendered")
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
    r = await client.get(f"{page_url}/rendered", params={"A": 2})
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
