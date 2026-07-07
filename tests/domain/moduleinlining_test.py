"""Tests for the moduleinlining domain."""

from __future__ import annotations

import base64
import re
import sys
from collections.abc import Sequence
from typing import cast

import nbformat
import pytest
from gidgethub.httpx import GitHubAPI
from nbformat.v4 import new_code_cell, new_markdown_cell, new_notebook
from safir.github.models import GitHubBlobModel

from timessquare.domain.githubcheckout import (
    GitHubRepositoryCheckout,
    RepositoryTree,
)
from timessquare.domain.moduleinlining import (
    LocalModuleCache,
    _order_modules,
    _ResolvedModule,
    extract_imports,
    find_local_module,
    prepare_notebook_for_execution,
    rewrite_relative_imports,
)
from timessquare.exceptions import (
    CircularModuleImportError,
    PageModuleInlineError,
)
from timessquare.storage.github.apimodels import (
    GitTreeItem,
    GitTreeMode,
    RecursiveGitTreeModel,
)
from timessquare.storage.github.settingsfiles import RepositorySettingsFile


def make_tree(paths: Sequence[str]) -> RepositoryTree:
    """Build a RepositoryTree whose git tree contains ``paths`` as files."""
    return RepositoryTree(
        github_tree=RecursiveGitTreeModel.model_validate(
            {
                "sha": "root",
                "url": "https://example.com/root",
                "truncated": False,
                "tree": [
                    {
                        "path": p,
                        "mode": "100644",
                        "type": "blob",
                        "sha": f"sha-{i}",
                        "url": f"https://example.com/{i}",
                    }
                    for i, p in enumerate(paths)
                ],
            }
        )
    )


def make_tree_item(path: str, *, sha: str = "sha") -> GitTreeItem:
    """Build a single git tree item for a file path."""
    return GitTreeItem(
        path=path,
        mode=GitTreeMode.file,
        sha=sha,
        url="https://example.com/item",  # type: ignore[arg-type]
    )


class FakeModuleCache(LocalModuleCache):
    """A module cache that serves source from a path-keyed dict, never
    touching the network.
    """

    def __init__(self, sources: dict[str, str]) -> None:
        super().__init__()
        self._path_sources = sources

    async def get_source(
        self,
        *,
        item: GitTreeItem,
        checkout: GitHubRepositoryCheckout,
        github_client: GitHubAPI,
    ) -> str:
        return self._path_sources[item.path]


def make_checkout() -> GitHubRepositoryCheckout:
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


def make_notebook_source(cell_sources: Sequence[str]) -> str:
    """Build ipynb JSON with a leading markdown cell then given code cells."""
    nb = new_notebook()
    cells: list[nbformat.NotebookNode] = [new_markdown_cell("# Title")]
    cells.extend(new_code_cell(source) for source in cell_sources)
    nb.cells = cells
    return nbformat.writes(nb)


def decode_module_cell(source: str) -> str:
    """Extract and decode the base64 module source from an inlined cell."""
    match = re.search(r'b64decode\("([^"]+)"\)', source)
    assert match is not None
    return base64.b64decode(match.group(1)).decode("utf-8")


# ---------------------------------------------------------------------------
# Tests for extract_imports
# ---------------------------------------------------------------------------


def test_extract_imports_plain() -> None:
    """A plain ``import`` reports the module name."""
    imports = extract_imports("import helpers")
    assert imports is not None
    assert len(imports) == 1
    assert imports[0].module_name == "helpers"
    assert imports[0].is_from is False
    assert imports[0].names == []


def test_extract_imports_aliased() -> None:
    """An aliased import reports the real module name, not the alias."""
    imports = extract_imports("import numpy as np")
    assert imports is not None
    assert [i.module_name for i in imports] == ["numpy"]


def test_extract_imports_from() -> None:
    """A from-import reports the module and imported names."""
    imports = extract_imports("from pkg import VALUE, other")
    assert imports is not None
    assert len(imports) == 1
    assert imports[0].module_name == "pkg"
    assert imports[0].is_from is True
    assert imports[0].names == ["VALUE", "other"]


def test_extract_imports_relative_not_reported() -> None:
    """Relative from-imports are not reported."""
    assert extract_imports("from . import a, b") == []


def test_extract_imports_with_line_magic() -> None:
    """Line magics are stripped so real imports are still found."""
    source = "%matplotlib inline\nimport helpers\n!pip install x"
    imports = extract_imports(source)
    assert imports is not None
    assert [i.module_name for i in imports] == ["helpers"]


def test_extract_imports_cell_magic_none() -> None:
    """A ``%%`` cell-magic cell returns None."""
    assert extract_imports("%%bash\necho hello") is None


def test_extract_imports_unparsable_none() -> None:
    """Genuinely unparsable source returns None."""
    assert extract_imports("def broken(:\n    pass") is None


# ---------------------------------------------------------------------------
# Tests for rewrite_relative_imports
# ---------------------------------------------------------------------------


def test_rewrite_submodule_relative() -> None:
    """A relative import in a plain submodule anchors on the parent."""
    result = rewrite_relative_imports(
        "from .sub import X", "pkg.mod", is_package=False
    )
    assert result == "from pkg.sub import X"


def test_rewrite_package_init_relative() -> None:
    """A relative import in a package __init__ anchors on the package."""
    result = rewrite_relative_imports(
        "from .sub import X", "pkg", is_package=True
    )
    assert result == "from pkg.sub import X"


def test_rewrite_from_dot_import_submodule() -> None:
    """``from . import X`` in a submodule becomes the parent package."""
    result = rewrite_relative_imports(
        "from . import X", "pkg.mod", is_package=False
    )
    assert result == "from pkg import X"


def test_rewrite_double_dot() -> None:
    """``from .. import X`` climbs two levels from a nested submodule."""
    result = rewrite_relative_imports(
        "from .. import X", "pkg.sub.mod", is_package=False
    )
    assert result == "from pkg import X"


def test_rewrite_climbs_above_root_package() -> None:
    """A relative import above a top-level package raises."""
    with pytest.raises(PageModuleInlineError):
        rewrite_relative_imports("from .. import X", "pkg", is_package=True)


def test_rewrite_relative_in_top_level_module() -> None:
    """Any relative import in a top-level plain module raises."""
    with pytest.raises(PageModuleInlineError):
        rewrite_relative_imports("from . import X", "mod", is_package=False)


def test_rewrite_multiline_parenthesized() -> None:
    """A multi-line parenthesized relative import rewrites correctly."""
    source = "from . import (\n    a,\n    b,\n    c,\n)"
    result = rewrite_relative_imports(source, "pkg.mod", is_package=False)
    imports = extract_imports(result)
    assert imports is not None
    assert imports[0].module_name == "pkg"
    assert imports[0].names == ["a", "b", "c"]


def test_rewrite_no_relative_imports_byte_for_byte() -> None:
    """Source without relative imports is returned unchanged."""
    source = "# a comment\nimport os\n\nx = 1  # trailing\n"
    assert rewrite_relative_imports(source, "mod", is_package=False) == source


# ---------------------------------------------------------------------------
# find_local_module
# ---------------------------------------------------------------------------


def test_find_local_module_py() -> None:
    """A ``.py`` file resolves."""
    tree = make_tree(["helpers.py"])
    item = find_local_module("helpers", search_roots=[""], tree=tree)
    assert item is not None
    assert item.path == "helpers.py"


def test_find_local_module_package() -> None:
    """A package ``__init__.py`` resolves."""
    tree = make_tree(["pkg/__init__.py"])
    item = find_local_module("pkg", search_roots=[""], tree=tree)
    assert item is not None
    assert item.path == "pkg/__init__.py"


def test_find_local_module_external_none() -> None:
    """A stdlib/external name does not resolve."""
    tree = make_tree(["helpers.py"])
    assert find_local_module("numpy", search_roots=[""], tree=tree) is None


def test_find_local_module_first_root_wins() -> None:
    """The notebook directory is searched before the repository root."""
    tree = make_tree(["notebooks/helpers.py", "helpers.py"])
    item = find_local_module(
        "helpers", search_roots=["notebooks", ""], tree=tree
    )
    assert item is not None
    assert item.path == "notebooks/helpers.py"


# ---------------------------------------------------------------------------
# _order_modules
# ---------------------------------------------------------------------------


def resolved(name: str, deps: set[str]) -> _ResolvedModule:
    """Build a _ResolvedModule with dummy tree item and source."""
    return _ResolvedModule(
        name=name,
        tree_item=make_tree_item(f"{name}.py"),
        source="",
        is_package=False,
        dependencies=deps,
    )


def test_order_modules_linear_chain() -> None:
    """A linear dependency chain orders dependencies first."""
    modules = {
        "a": resolved("a", {"b"}),
        "b": resolved("b", {"c"}),
        "c": resolved("c", set()),
    }
    order = _order_modules(modules)
    assert order.index("c") < order.index("b") < order.index("a")


def test_order_modules_diamond() -> None:
    """A diamond dependency orders the shared base first, apex last."""
    modules = {
        "a": resolved("a", {"b", "c"}),
        "b": resolved("b", {"d"}),
        "c": resolved("c", {"d"}),
        "d": resolved("d", set()),
    }
    order = _order_modules(modules)
    assert order.index("d") < order.index("b")
    assert order.index("d") < order.index("c")
    assert order.index("b") < order.index("a")
    assert order.index("c") < order.index("a")


def test_order_modules_cycle_raises() -> None:
    """A real 2-cycle raises with both names in the message."""
    modules = {
        "a": resolved("a", {"b"}),
        "b": resolved("b", {"a"}),
    }
    with pytest.raises(CircularModuleImportError) as excinfo:
        _order_modules(modules)
    message = str(excinfo.value)
    assert "a" in message
    assert "b" in message


# ---------------------------------------------------------------------------
# prepare_notebook_for_execution
# ---------------------------------------------------------------------------


def params_cell_index(notebook: nbformat.NotebookNode) -> int:
    """Index of the marked parameters cell."""
    return next(
        i
        for i, cell in enumerate(notebook.cells)
        if cell.cell_type == "code"
        and cell.metadata.get("times_square", {}).get("cell_type")
        == "parameters"
    )


@pytest.mark.asyncio
async def test_prepare_no_local_imports(github_client: GitHubAPI) -> None:
    """A notebook with no local imports is marked and left otherwise as-is,
    and a second pass is byte-identical.
    """
    source = make_notebook_source(["import numpy as np\nnp.array([1])"])
    cache = FakeModuleCache({})
    ipynb, inlined = await prepare_notebook_for_execution(
        notebook_source=source,
        notebook_path_prefix="notebooks",
        tree=make_tree([]),
        checkout=make_checkout(),
        github_client=github_client,
        module_cache=cache,
    )
    assert inlined == []
    notebook = nbformat.reads(ipynb, as_version=4)
    # markdown + single code cell (marked); no new cells inserted.
    assert len(notebook.cells) == 2
    assert (
        notebook.cells[1].metadata["times_square"]["cell_type"] == "parameters"
    )
    # Idempotent for the no-imports case.
    ipynb2, _ = await prepare_notebook_for_execution(
        notebook_source=ipynb,
        notebook_path_prefix="notebooks",
        tree=make_tree([]),
        checkout=make_checkout(),
        github_client=github_client,
        module_cache=FakeModuleCache({}),
    )
    assert ipynb2 == ipynb


@pytest.mark.asyncio
async def test_prepare_same_directory_import(
    github_client: GitHubAPI,
) -> None:
    """A sibling module import is inlined."""
    source = make_notebook_source(["import helpers\nhelpers.run()"])
    tree = make_tree(["notebooks/helpers.py"])
    cache = FakeModuleCache({"notebooks/helpers.py": "def run(): pass"})
    ipynb, inlined = await prepare_notebook_for_execution(
        notebook_source=source,
        notebook_path_prefix="notebooks",
        tree=tree,
        checkout=make_checkout(),
        github_client=github_client,
        module_cache=cache,
    )
    assert inlined == ["helpers"]
    notebook = nbformat.reads(ipynb, as_version=4)
    scaffolds = [
        c
        for c in notebook.cells
        if c.metadata.get("times_square", {}).get("cell_type")
        == "module_scaffolding"
    ]
    inlined_cells = [
        c
        for c in notebook.cells
        if c.metadata.get("times_square", {}).get("cell_type")
        == "inlined_module"
    ]
    assert len(scaffolds) == 1
    assert len(inlined_cells) == 1
    assert inlined_cells[0].metadata["times_square"]["module_name"] == (
        "helpers"
    )
    # The inlined cells precede the parameters cell.
    params_idx = params_cell_index(notebook)
    for cell in [*scaffolds, *inlined_cells]:
        assert notebook.cells.index(cell) < params_idx


@pytest.mark.asyncio
async def test_prepare_transitive_import(github_client: GitHubAPI) -> None:
    """A transitive same-directory import orders the dependency first."""
    source = make_notebook_source(["import a\na.go()"])
    tree = make_tree(["notebooks/a.py", "notebooks/b.py"])
    cache = FakeModuleCache(
        {
            "notebooks/a.py": "import b\n\ndef go(): return b",
            "notebooks/b.py": "value = 1",
        }
    )
    ipynb, inlined = await prepare_notebook_for_execution(
        notebook_source=source,
        notebook_path_prefix="notebooks",
        tree=tree,
        checkout=make_checkout(),
        github_client=github_client,
        module_cache=cache,
    )
    assert inlined.index("b") < inlined.index("a")
    notebook = nbformat.reads(ipynb, as_version=4)
    module_names = [
        c.metadata["times_square"]["module_name"]
        for c in notebook.cells
        if c.metadata.get("times_square", {}).get("cell_type")
        == "inlined_module"
    ]
    assert module_names.index("b") < module_names.index("a")


@pytest.mark.asyncio
async def test_prepare_package_relative_import(
    github_client: GitHubAPI,
) -> None:
    """A package whose __init__ re-exports from a submodule orders the
    submodule before the package and rewrites its relative import.
    """
    source = make_notebook_source(["import helpers\nfrom pkg import VALUE"])
    tree = make_tree(["notebooks/helpers.py", "pkg/__init__.py", "pkg/sub.py"])
    cache = FakeModuleCache(
        {
            "notebooks/helpers.py": "def run(): pass",
            "pkg/__init__.py": "from .sub import VALUE",
            "pkg/sub.py": "VALUE = 42",
        }
    )
    ipynb, inlined = await prepare_notebook_for_execution(
        notebook_source=source,
        notebook_path_prefix="notebooks",
        tree=tree,
        checkout=make_checkout(),
        github_client=github_client,
        module_cache=cache,
    )
    assert inlined == ["helpers", "pkg.sub", "pkg"]
    notebook = nbformat.reads(ipynb, as_version=4)
    pkg_cell = next(
        c
        for c in notebook.cells
        if c.metadata.get("times_square", {}).get("module_name") == "pkg"
    )
    decoded = decode_module_cell(pkg_cell.source)
    assert "from pkg.sub import VALUE" in decoded


@pytest.mark.asyncio
async def test_prepare_import_via_repo_root(
    github_client: GitHubAPI,
) -> None:
    """A module resolvable only at the repository root is inlined."""
    source = make_notebook_source(["import shared\nshared.x"])
    tree = make_tree(["shared.py"])
    cache = FakeModuleCache({"shared.py": "x = 1"})
    _, inlined = await prepare_notebook_for_execution(
        notebook_source=source,
        notebook_path_prefix="sub",
        tree=tree,
        checkout=make_checkout(),
        github_client=github_client,
        module_cache=cache,
    )
    assert inlined == ["shared"]


@pytest.mark.asyncio
async def test_prepare_circular_import(github_client: GitHubAPI) -> None:
    """A circular import between two modules raises."""
    source = make_notebook_source(["import a\na.go()"])
    tree = make_tree(["notebooks/a.py", "notebooks/b.py"])
    cache = FakeModuleCache(
        {
            "notebooks/a.py": "import b",
            "notebooks/b.py": "import a",
        }
    )
    with pytest.raises(CircularModuleImportError):
        await prepare_notebook_for_execution(
            notebook_source=source,
            notebook_path_prefix="notebooks",
            tree=tree,
            checkout=make_checkout(),
            github_client=github_client,
            module_cache=cache,
        )


@pytest.mark.asyncio
async def test_prepare_inlined_modules_execute(
    github_client: GitHubAPI,
) -> None:
    """Executing the scaffolding and module cells reconstructs the modules
    so the notebook's own imports resolve at runtime.
    """
    source = make_notebook_source(["import helpers\nfrom pkg import VALUE"])
    tree = make_tree(["notebooks/helpers.py", "pkg/__init__.py", "pkg/sub.py"])
    cache = FakeModuleCache(
        {
            "notebooks/helpers.py": "GREETING = 'hi'",
            "pkg/__init__.py": "from .sub import VALUE",
            "pkg/sub.py": "VALUE = 42",
        }
    )
    ipynb, _ = await prepare_notebook_for_execution(
        notebook_source=source,
        notebook_path_prefix="notebooks",
        tree=tree,
        checkout=make_checkout(),
        github_client=github_client,
        module_cache=cache,
    )
    notebook = nbformat.reads(ipynb, as_version=4)
    generated_cells = [
        c
        for c in notebook.cells
        if c.metadata.get("times_square", {}).get("cell_type")
        in {"module_scaffolding", "inlined_module"}
    ]
    affected = ["helpers", "pkg", "pkg.sub"]
    saved = {name: sys.modules.get(name) for name in affected}
    try:
        namespace: dict[str, object] = {}
        for cell in generated_cells:
            exec(cell.source, namespace)  # noqa: S102
        exec("import helpers\nfrom pkg import VALUE", namespace)  # noqa: S102
        helpers_module: object = namespace["helpers"]
        assert helpers_module.GREETING == "hi"  # type: ignore[attr-defined]
        assert namespace["VALUE"] == 42
    finally:
        for name in affected:
            if saved[name] is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = saved[name]  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# LocalModuleCache
# ---------------------------------------------------------------------------


class CountingCheckout:
    """A fake checkout that counts blob fetches."""

    def __init__(self, source: str) -> None:
        self.calls = 0
        self._source = source

    async def load_git_blob(
        self, *, github_client: GitHubAPI, sha: str
    ) -> GitHubBlobModel:
        self.calls += 1
        content = base64.b64encode(self._source.encode("utf-8")).decode(
            "ascii"
        )
        return GitHubBlobModel(
            content=content,
            encoding="base64",
            url="https://example.com/blob",  # type: ignore[arg-type]
            sha=sha,
            size=len(self._source),
        )


@pytest.mark.asyncio
async def test_local_module_cache_dedup(github_client: GitHubAPI) -> None:
    """The same blob sha is fetched from GitHub only once."""
    cache = LocalModuleCache()
    checkout = CountingCheckout("x = 1")
    item = make_tree_item("helpers.py", sha="blobsha")
    first = await cache.get_source(
        item=item,
        checkout=cast("GitHubRepositoryCheckout", checkout),
        github_client=github_client,
    )
    second = await cache.get_source(
        item=item,
        checkout=cast("GitHubRepositoryCheckout", checkout),
        github_client=github_client,
    )
    assert first == "x = 1"
    assert second == "x = 1"
    assert checkout.calls == 1
