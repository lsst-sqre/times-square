"""Tests for the `/v1/github... endpoints."""

from datetime import datetime, timezone
from pathlib import Path

import pytest
from aioredis import Redis
from httpx import AsyncClient
from safir.database import create_async_session, create_database_engine
from structlog import get_logger

from timessquare.config import config
from timessquare.domain.page import PageModel
from timessquare.services.page import PageService
from timessquare.storage.nbhtmlcache import NbHtmlCacheStore
from timessquare.storage.noteburstjobstore import NoteburstJobStore
from timessquare.storage.page import PageStore


@pytest.mark.asyncio
async def test_github(client: AsyncClient) -> None:
    """Test the /v1/github APIs with mocked sources (i.e. this does not test
    syncing content from GitHub, only reading github-backed apges.
    """
    data_path = Path(__file__).parent.joinpath("../../data")
    demo_path = data_path / "demo.ipynb"

    engine = create_database_engine(
        config.database_url, config.database_password.get_secret_value()
    )
    session = await create_async_session(engine)

    redis = Redis.from_url(config.redis_url)

    page_service = PageService(
        page_store=PageStore(session=session),
        html_cache=NbHtmlCacheStore(redis),
        job_store=NoteburstJobStore(redis),
        http_client=client,
        logger=get_logger(),
    )

    await page_service.add_page(
        PageModel(
            name="1",
            ipynb=demo_path.read_text(),
            parameters={},
            title="Demo",
            date_added=datetime.now(timezone.utc),
            date_deleted=None,
            github_owner="lsst-sqre",
            github_repo="times-square-demo",
            repository_path_prefix="",
            repository_display_path_prefix="",
            repository_path_stem="demo",
            repository_sidecar_extension=".yaml",
            repository_source_extension=".ipynb",
            repository_source_sha="1" * 40,
            repository_sidecar_sha="1" * 40,
        ),
        execute=False,
    )
    await page_service.add_page(
        PageModel(
            name="2",
            ipynb=demo_path.read_text(),
            parameters={},
            title="Gaussian 2D",
            date_added=datetime.now(timezone.utc),
            date_deleted=None,
            github_owner="lsst-sqre",
            github_repo="times-square-demo",
            repository_path_prefix="matplotlib",
            repository_display_path_prefix="matplotlib",
            repository_path_stem="gaussian2d",
            repository_sidecar_extension=".yaml",
            repository_source_extension=".ipynb",
            repository_source_sha="1" * 40,
            repository_sidecar_sha="1" * 40,
        ),
        execute=False,
    )
    await page_service.add_page(
        PageModel(
            name="3",
            ipynb=demo_path.read_text(),
            parameters={},
            title="Tutorial A",
            date_added=datetime.now(timezone.utc),
            date_deleted=None,
            github_owner="lsst",
            github_repo="tutorial-notebooks",
            repository_path_prefix="",
            repository_display_path_prefix="",
            repository_path_stem="tutorialA",
            repository_sidecar_extension=".yaml",
            repository_source_extension=".ipynb",
            repository_source_sha="1" * 40,
            repository_sidecar_sha="1" * 40,
        ),
        execute=False,
    )

    await session.commit()

    # Close the set up database
    await session.remove()
    await engine.dispose()

    # Get data from the API to test tree construction
    r = await client.get(f"{config.path_prefix}/v1/github")
    assert r.status_code == 200
    data = r.json()
    assert "contents" in data.keys()
    print(data)
    assert data["contents"][0]["node_type"] == "owner"
    assert data["contents"][0]["title"] == "lsst"
    assert data["contents"][0]["path"] == "lsst"
    assert data["contents"][0]["contents"] == [
        {
            "node_type": "repo",
            "title": "tutorial-notebooks",
            "path": "lsst/tutorial-notebooks",
            "contents": [
                {
                    "node_type": "page",
                    "title": "Tutorial A",
                    "path": "lsst/tutorial-notebooks/tutorialA",
                    "contents": [],
                }
            ],
        }
    ]
    assert data["contents"][1]["contents"][0] == {
        "node_type": "repo",
        "title": "times-square-demo",
        "path": "lsst-sqre/times-square-demo",
        "contents": [
            {
                "node_type": "page",
                "title": "Demo",
                "path": "lsst-sqre/times-square-demo/demo",
                "contents": [],
            },
            {
                "node_type": "directory",
                "title": "matplotlib",
                "path": "lsst-sqre/times-square-demo/matplotlib",
                "contents": [
                    {
                        "node_type": "page",
                        "title": "Gaussian 2D",
                        "path": (
                            "lsst-sqre/times-square-demo/matplotlib/"
                            "gaussian2d"
                        ),
                        "contents": [],
                    },
                ],
            },
        ],
    }

    r = await client.get(
        f"{config.path_prefix}/v1/github/lsst-sqre/times-square-demo/demo"
    )
    assert r.status_code == 200
    data = r.json()
    assert data["title"] == "Demo"

    # A directory; there shouldn't be a resolved path at the moment
    r = await client.get(
        f"{config.path_prefix}/v1/github/"
        f"lsst-sqre/times-square-demo/matplotlib"
    )
    assert r.status_code == 404
