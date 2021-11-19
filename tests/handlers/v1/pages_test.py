"""Tests for adding and managing pages with the /v1/ API."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from timessquare.config import config

if TYPE_CHECKING:
    from httpx import AsyncClient


@pytest.mark.asyncio
async def test_pages(client: AsyncClient) -> None:
    """Test creating and managing pages."""
    demo_path = Path(__file__).parent.joinpath("../../data/demo.ipynb")
    page_req_data = {"name": "demo", "ipynb": demo_path.read_text()}

    r = await client.post(f"{config.path_prefix}/v1/pages", json=page_req_data)
    assert r.status_code == 201
    page_url = r.headers["location"]
    assert page_url == "https://example.com/times-square/v1/pages/demo"
    data = r.json()
    assert data["name"] == "demo"
    assert data["self_url"] == page_url

    r = await client.get(page_url)
    assert r.status_code == 200
    data2 = r.json()
    assert data == data2

    source_url = f"{page_url}/source"
    r = await client.get(source_url)
    assert r.status_code == 200
    assert r.headers["location"] == source_url
    source_notebook_data = r.json()
    assert "metadata" in source_notebook_data.keys()  # check it's a notebook
