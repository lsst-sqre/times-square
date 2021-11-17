"""Tests for the timessquare.handlers.external module and routes."""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from timessquare.config import config

if TYPE_CHECKING:
    from httpx import AsyncClient


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

    external_docs_url = data["api_docs"]["root"]
    external_docs_response = await client.get(external_docs_url)
    assert external_docs_response.status_code == 200

    v1_docs_url = data["api_docs"]["v1"]
    v1_docs_response = await client.get(v1_docs_url)
    assert v1_docs_response.status_code == 200
