"""Tests for the githubcheckout domain."""

from __future__ import annotations

import base64
import json
from collections.abc import Sequence
from pathlib import Path

import nbformat
import pytest
import respx
from gidgethub.httpx import GitHubAPI
from httpx import Response
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook

from timessquare.domain.githubcheckout import (
    GitHubRepositoryCheckout,
    RepositoryNotebookTreeRef,
    RepositoryTree,
)
from timessquare.domain.moduleinlining import (
    LocalModuleCache,
    prepare_notebook_for_execution,
)
from timessquare.storage.github.apimodels import RecursiveGitTreeModel
from timessquare.storage.github.settingsfiles import RepositorySettingsFile


def _make_tree(paths: Sequence[tuple[str, str]]) -> RepositoryTree:
    """Build a RepositoryTree from ``(path, sha)`` pairs."""
    return RepositoryTree(
        github_tree=RecursiveGitTreeModel.model_validate(
            {
                "sha": "root",
                "url": "https://example.com/root",
                "truncated": False,
                "tree": [
                    {
                        "path": path,
                        "mode": "100644",
                        "type": "blob",
                        "sha": sha,
                        "url": f"https://example.com/{sha}",
                    }
                    for path, sha in paths
                ],
            }
        )
    )


def _blob_json(source: str, sha: str) -> dict[str, object]:
    """Build a GitHubBlobModel-shaped JSON response for source content."""
    content = base64.b64encode(source.encode("utf-8")).decode("ascii")
    return {
        "content": content,
        "encoding": "base64",
        "url": f"https://api.github.com/blobs/{sha}",
        "sha": sha,
        "size": len(source),
        "node_id": "",
    }


class _DictModuleCache(LocalModuleCache):
    """A module cache that serves source from a path-keyed dict."""

    def __init__(self, sources: dict[str, str]) -> None:
        super().__init__()
        self._path_sources = sources

    async def get_source(
        self, *, item: object, checkout: object, github_client: object
    ) -> str:
        return self._path_sources[item.path]  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_repository_git_tree(
    github_client: GitHubAPI, respx_mock: respx.Router
) -> None:
    """Test that GitHubRepositoryCheckout.get_git_tree() calls the tree URL
    with the ``?recursive=1`` query string.

    Uses the lsst-sqre/rsp_broadcast repo as a simple test dataset.
    """
    json_path = Path(__file__).parent.joinpath(
        "../data/rsp_broadcast/recursive_tree.json"
    )
    repo = GitHubRepositoryCheckout(
        owner_name="lsst-sqre",
        name="rsp_broadcast",
        settings=RepositorySettingsFile(ignore=[]),
        git_ref="refs/heads/main",
        head_sha="46372dfa5a432026d68d262899755ef0333ef8c0",
        trees_url=(
            "https://api.github.com/repos/lsst-sqre/rsp_broadcast/git/trees/"
            "46372dfa5a432026d68d262899755ef0333ef8c0"
        ),
        blobs_url=(
            "https://api.github.com/repos/lsst-sqre/rsp_broadcast/git/blobs/"
            "46372dfa5a432026d68d262899755ef0333ef8c0"
        ),
    )

    # respx_mock
    respx_mock.get(
        "https://api.github.com/repos/lsst-sqre/rsp_broadcast/git/trees/"
        "46372dfa5a432026d68d262899755ef0333ef8c0?recursive=1"
    ).mock(return_value=Response(200, json=json.loads(json_path.read_text())))
    repo_tree = await repo.get_git_tree(github_client)
    assert (
        repo_tree.github_tree.sha == "46372dfa5a432026d68d262899755ef0333ef8c0"
    )


@pytest.mark.asyncio
async def test_recursive_git_tree_find_notebooks() -> None:
    """Test RepositoryTree using the times-square-time dataset."""
    json_path = Path(__file__).parent.joinpath(
        "../data/times-square-demo/recursive_tree.json"
    )
    repo_tree = RepositoryTree(
        github_tree=RecursiveGitTreeModel.model_validate_json(
            json_path.read_text()
        )
    )
    settings = RepositorySettingsFile(ignore=[])
    notebook_refs = list(repo_tree.find_notebooks(settings))
    assert len(notebook_refs) == 2

    # Apply ignore settings to reduce number of detected notebooks
    settings2 = RepositorySettingsFile(ignore=["matplotlib/*"])
    notebook_refs2 = list(repo_tree.find_notebooks(settings2))
    assert len(notebook_refs2) == 1


def test_repository_tree_get_file() -> None:
    """Test RepositoryTree.get_file() for a hit, a miss, and a directory."""
    json_path = Path(__file__).parent.joinpath(
        "../data/times-square-demo/recursive_tree.json"
    )
    repo_tree = RepositoryTree(
        github_tree=RecursiveGitTreeModel.model_validate_json(
            json_path.read_text()
        )
    )
    # Hit: a real file.
    item = repo_tree.get_file("demo.ipynb")
    assert item is not None
    assert item.path == "demo.ipynb"
    # Miss: a nonexistent path.
    assert repo_tree.get_file("does-not-exist.py") is None
    # A directory path is not a file and returns None.
    assert repo_tree.get_file("matplotlib") is None


@pytest.mark.asyncio
async def test_load_notebook_inlines_modules(
    github_client: GitHubAPI, respx_mock: respx.Router
) -> None:
    """load_notebook() prepares a notebook by inlining a sibling module."""
    notebook_source = _write_notebook(["import helper\nhelper.run()"])
    sidecar_source = "title: Demo notebook\n"
    module_source = "def run():\n    return 1\n"

    tree = _make_tree(
        [
            ("nb.ipynb", "nbsha"),
            ("nb.yaml", "sidesha"),
            ("helper.py", "helpersha"),
        ]
    )
    checkout = GitHubRepositoryCheckout(
        owner_name="lsst-sqre",
        name="demo",
        settings=RepositorySettingsFile(ignore=[]),
        git_ref="refs/heads/main",
        head_sha="headsha",
        trees_url="https://api.github.com/repos/lsst-sqre/demo/git/trees{/sha}",
        blobs_url="https://api.github.com/repos/lsst-sqre/demo/git/blobs{/sha}",
    )
    base = "https://api.github.com/repos/lsst-sqre/demo/git/blobs"
    respx_mock.get(f"{base}/sidesha").mock(
        return_value=Response(200, json=_blob_json(sidecar_source, "sidesha"))
    )
    respx_mock.get(f"{base}/nbsha").mock(
        return_value=Response(200, json=_blob_json(notebook_source, "nbsha"))
    )
    respx_mock.get(f"{base}/helpersha").mock(
        return_value=Response(200, json=_blob_json(module_source, "helpersha"))
    )

    notebook_ref = RepositoryNotebookTreeRef(
        notebook_source_path="nb.ipynb",
        sidecar_path="nb.yaml",
        notebook_git_tree_sha="nbsha",
        sidecar_git_tree_sha="sidesha",
    )
    model = await checkout.load_notebook(
        notebook_ref=notebook_ref,
        github_client=github_client,
        tree=tree,
        module_cache=LocalModuleCache(),
    )
    assert model.inlined_modules == ["helper"]
    prepared = nbformat.reads(model.ipynb, as_version=4)
    inlined_cells = [
        c
        for c in prepared.cells
        if c.metadata.get("times_square", {}).get("cell_type")
        == "inlined_module"
    ]
    assert len(inlined_cells) == 1
    assert inlined_cells[0].metadata["times_square"]["module_name"] == (
        "helper"
    )


@pytest.mark.asyncio
async def test_prepare_marker_stable_across_resync(
    github_client: GitHubAPI,
) -> None:
    """Re-syncing the same raw notebook yields identical prepared output,
    with the marker on the original first code cell and inlined cells just
    before it.
    """
    notebook_source = _write_notebook(["import helper\nhelper.run()"])
    tree = _make_tree([("helper.py", "helpersha")])
    sources = {"helper.py": "def run():\n    return 1\n"}

    outputs: list[str] = []
    for _ in range(2):
        ipynb, inlined = await prepare_notebook_for_execution(
            notebook_source=notebook_source,
            notebook_path_prefix="",
            tree=tree,
            checkout=_make_checkout(),
            github_client=github_client,
            module_cache=_DictModuleCache(dict(sources)),
        )
        assert inlined == ["helper"]
        outputs.append(ipynb)

    # Structural invariants: the marker sits on the original first code
    # cell and the inlined-module cell sits directly before it.
    prepared = nbformat.reads(outputs[0], as_version=4)
    params_index = next(
        i
        for i, cell in enumerate(prepared.cells)
        if cell.cell_type == "code"
        and cell.metadata.get("times_square", {}).get("cell_type")
        == "parameters"
    )
    assert "import helper" in prepared.cells[params_index].source
    preceding = prepared.cells[params_index - 1]
    assert preceding.metadata["times_square"]["cell_type"] == "inlined_module"

    # Both re-sync passes must be byte-identical.
    assert outputs[0] == outputs[1]


def _write_notebook(cell_sources: Sequence[str]) -> str:
    """Build ipynb JSON with a leading markdown cell then given code cells."""
    nb = new_notebook()
    cells: list[nbformat.NotebookNode] = [new_markdown_cell("# Title")]
    cells.extend(new_code_cell(source) for source in cell_sources)
    nb.cells = cells
    return nbformat.writes(nb)


def _make_checkout() -> GitHubRepositoryCheckout:
    """Build a checkout suitable as an (unused) argument to prepare."""
    return GitHubRepositoryCheckout(
        owner_name="lsst-sqre",
        name="demo",
        settings=RepositorySettingsFile(ignore=[]),
        git_ref="refs/heads/main",
        head_sha="headsha",
        trees_url="https://example.com/trees{/sha}",
        blobs_url="https://example.com/blobs{/sha}",
    )
