"""Inlining of local module imports into GitHub-synced notebooks.

Times Square delegates notebook execution to Noteburst, which receives only
the notebook's ipynb content — not the rest of the GitHub repository the
notebook came from. A notebook that imports a sibling Python module in its
repository would therefore fail at execution time. This module rewrites such
notebooks at sync time: imports of modules found in the repository are
"inlined" as generated code cells that reconstruct those modules in
``sys.modules`` before the notebook's own (untouched) import statements run.

Module resolution is purely path-based against the repository's git tree,
checking the notebook's own directory first and then the repository root.
A deliberate consequence is that a repository file that shadows an installed
package's name (e.g. a sibling ``json.py``) is treated as local and shadows
the real package — matching what happens when running the notebook
interactively in JupyterLab with the same working directory.
"""

from __future__ import annotations

import ast
import base64
import re
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from nbformat.v4 import new_code_cell

from timessquare.exceptions import (
    CircularModuleImportError,
    PageModuleInlineError,
)

from .page import PageModel, mark_notebook_parameters_cell

if TYPE_CHECKING:
    import nbformat
    from gidgethub.httpx import GitHubAPI

    from timessquare.storage.github.apimodels import GitTreeItem

    from .githubcheckout import GitHubRepositoryCheckout, RepositoryTree

__all__ = [
    "ImportInfo",
    "LocalModuleCache",
    "extract_imports",
    "find_local_module",
    "prepare_notebook_for_execution",
    "rewrite_relative_imports",
]


@dataclass(kw_only=True)
class ImportInfo:
    """An import statement found in Python source."""

    module_name: str
    """Dotted name of the imported module (for a from-import, the module
    named after ``from``).
    """

    names: list[str] = field(default_factory=list)
    """Imported names for a from-import (may include ``"*"``); empty for a
    plain import.
    """

    is_from: bool = False
    """Whether this is a ``from ... import ...`` statement."""


class LocalModuleCache:
    """A cache of decoded module source, keyed by git blob SHA.

    Because blobs are content-addressed, a shared module imported by many
    notebooks in one sync pass is fetched from GitHub only once. Create a
    fresh instance per sync/check-run pass so there is no cross-request
    staleness.
    """

    def __init__(self) -> None:
        self._sources: dict[str, str] = {}

    async def get_source(
        self,
        *,
        item: GitTreeItem,
        checkout: GitHubRepositoryCheckout,
        github_client: GitHubAPI,
    ) -> str:
        """Get the decoded source of a git tree item, fetching the blob
        from GitHub on a cache miss.

        Returns
        -------
        str
            The module's source code.
        """
        if item.sha not in self._sources:
            blob = await checkout.load_git_blob(
                github_client=github_client, sha=item.sha
            )
            self._sources[item.sha] = blob.decode()
        return self._sources[item.sha]


_PYTHON_BODY_CELL_MAGICS = frozenset(
    {"time", "timeit", "capture", "prun", "debug"}
)
"""Cell magics whose body is executed as Python, and so may wrap real
import statements. Other cell magics (``%%bash``, ``%%writefile``, ...) treat
their body as non-Python and are not parsed.
"""

_INLINE_MAGIC_ASSIGNMENT = re.compile(
    r"^(?P<prefix>\s*[A-Za-z_][\w.\[\], ]*=\s*)[%!]"
)
"""Matches an assignment whose right-hand side is an IPython inline magic
(``x = %sx ls``) or shell escape (``y = !ls``); the RHS begins at the
``%`` or ``!`` immediately after the prefix.
"""


def _neutralize_ipython_line(line: str) -> str:
    """Rewrite an IPython-only line into valid Python so the surrounding
    cell still parses, leaving ordinary Python lines untouched.
    """
    stripped = line.lstrip()
    if stripped.startswith(("%", "!")):
        indent = line[: len(line) - len(stripped)]
        return indent + "pass"
    match = _INLINE_MAGIC_ASSIGNMENT.match(line)
    if match:
        return match.group("prefix") + "None"
    return line


def extract_imports(source: str) -> list[ImportInfo] | None:
    """Extract import statements from Python source.

    Handles IPython cell source on a best-effort basis so real imports are
    not hidden behind a `SyntaxError`:

    - Line magics (``%matplotlib``) and shell escapes (``!pip``) are
      neutralized, including when they form the right-hand side of an
      assignment (``x = %sx ls``, ``y = !ls``).
    - A cell opening with one of a known set of "Python-body" cell magics
      (``%%time``, ``%%timeit``, ``%%capture``, ``%%prun``, ``%%debug``) has
      its magic line stripped and its body parsed, since those magics
      execute their body as Python.

    Returns
    -------
    list of ImportInfo or None
        The imports found, or `None` if the source could not be parsed
        (including cells that open with a non-Python cell magic such as
        ``%%bash`` or ``%%writefile``). Callers should treat `None` as
        "no imports". Relative imports are not reported; they are only
        meaningful inside packages and are handled by
        `rewrite_relative_imports`.
    """
    lines = source.splitlines()
    if source.lstrip().startswith("%%"):
        magic_index = next(i for i, line in enumerate(lines) if line.strip())
        tokens = lines[magic_index].lstrip()[2:].split(maxsplit=1)
        magic_name = tokens[0] if tokens else ""
        if magic_name not in _PYTHON_BODY_CELL_MAGICS:
            return None
        lines = lines[magic_index + 1 :]
    cleaned_lines = [_neutralize_ipython_line(line) for line in lines]
    try:
        parsed = ast.parse("\n".join(cleaned_lines))
    except SyntaxError:
        return None

    imports: list[ImportInfo] = []
    for node in ast.walk(parsed):
        if isinstance(node, ast.Import):
            imports.extend(
                ImportInfo(module_name=alias.name) for alias in node.names
            )
        elif (
            isinstance(node, ast.ImportFrom)
            and node.level == 0
            and node.module
        ):
            imports.append(
                ImportInfo(
                    module_name=node.module,
                    names=[alias.name for alias in node.names],
                    is_from=True,
                )
            )
    return imports


def find_local_module(
    module_name: str,
    *,
    search_roots: Sequence[str],
    tree: RepositoryTree,
) -> GitTreeItem | None:
    """Resolve a dotted module name to a file in the repository git tree.

    For a name ``a.b``, checks ``{root}/a/b/__init__.py`` and then
    ``{root}/a/b.py`` for each root in ``search_roots``, in order; the first
    match wins. The package ``__init__.py`` is checked before the like-named
    plain module, mirroring CPython, which imports a package in preference to
    a module of the same name in the same directory.

    Parameters
    ----------
    module_name
        The dotted module name to resolve.
    search_roots
        Repository-relative directories to search, in order. Use ``""``
        for the repository root.
    tree
        The repository's git tree.

    Returns
    -------
    GitTreeItem or None
        The tree item for the module's source file, or `None` if the name
        does not resolve to a file in the repository.
    """
    relative_path = module_name.replace(".", "/")
    for root in search_roots:
        prefix = f"{root}/" if root else ""
        for candidate in (
            f"{prefix}{relative_path}/__init__.py",
            f"{prefix}{relative_path}.py",
        ):
            item = tree.get_file(candidate)
            if item is not None:
                return item
    return None


class _RelativeImportRewriter(ast.NodeTransformer):
    """Rewrite relative from-imports to absolute imports, anchored on the
    module's own dotted name.
    """

    def __init__(self, module_name: str, *, is_package: bool) -> None:
        self._module_name = module_name
        self._parts = module_name.split(".")
        self._is_package = is_package
        self.changed = False

    def visit_ImportFrom(self, node: ast.ImportFrom) -> ast.ImportFrom:
        if node.level == 0:
            return node
        # A package's __init__.py is anchored at the package itself; a
        # plain submodule is anchored at its parent package.
        drop = node.level - 1 if self._is_package else node.level
        base_length = len(self._parts) - drop
        if base_length < 1:
            dots = "." * node.level
            raise PageModuleInlineError(
                f"Cannot inline module {self._module_name}: the relative "
                f"import 'from {dots}{node.module or ''} import ...' "
                "extends above the top-level package in the repository."
            )
        base_parts = self._parts[:base_length]
        if node.module:
            base_parts = [*base_parts, node.module]
        self.changed = True
        return ast.copy_location(
            ast.ImportFrom(
                module=".".join(base_parts), names=node.names, level=0
            ),
            node,
        )


def rewrite_relative_imports(
    source: str, module_name: str, *, is_package: bool
) -> str:
    """Rewrite a local module's relative imports as absolute imports.

    Parameters
    ----------
    source
        The module's source code.
    module_name
        The dotted name the module is imported as.
    is_package
        Whether the module is a package's ``__init__.py`` (the anchor for
        relative imports differs by one level).

    Returns
    -------
    str
        The rewritten source (via `ast.unparse`, so comments are dropped),
        or the original source byte-for-byte if it has no relative imports
        or cannot be parsed (an unparsable module is inlined verbatim so it
        fails at execution time exactly as it would when imported
        normally).

    Raises
    ------
    PageModuleInlineError
        Raised if a relative import climbs above the resolvable package
        root.
    """
    try:
        parsed = ast.parse(source)
    except SyntaxError:
        return source
    rewriter = _RelativeImportRewriter(module_name, is_package=is_package)
    rewritten = rewriter.visit(parsed)
    if not rewriter.changed:
        return source
    return ast.unparse(ast.fix_missing_locations(rewritten))


@dataclass(kw_only=True)
class _ResolvedModule:
    """A local module resolved in the repository tree, with its rewritten
    source and its dependencies on other local modules.
    """

    name: str
    tree_item: GitTreeItem
    source: str
    is_package: bool
    dependencies: set[str] = field(default_factory=set)


def _candidate_module_names(imports: list[ImportInfo]) -> set[str]:
    """Expand import statements into module names that may resolve locally.

    A ``from x import y`` contributes both ``x`` and ``x.y``, since ``y``
    may itself be a submodule of a local package ``x``.
    """
    names: set[str] = set()
    for import_info in imports:
        names.add(import_info.module_name)
        if import_info.is_from:
            names.update(
                f"{import_info.module_name}.{name}"
                for name in import_info.names
                if name != "*"
            )
    return names


async def _collect_modules(
    candidates: set[str],
    *,
    search_roots: Sequence[str],
    tree: RepositoryTree,
    checkout: GitHubRepositoryCheckout,
    github_client: GitHubAPI,
    module_cache: LocalModuleCache,
) -> dict[str, _ResolvedModule]:
    """Resolve candidate module names against the repository tree and
    transitively collect every local module that needs inlining.
    """
    modules: dict[str, _ResolvedModule] = {}
    queue = deque(sorted(candidates))
    while queue:
        name = queue.popleft()
        if name in modules:
            continue
        item = find_local_module(name, search_roots=search_roots, tree=tree)
        if item is None:
            continue
        raw_source = await module_cache.get_source(
            item=item, checkout=checkout, github_client=github_client
        )
        is_package = item.path.rsplit("/", 1)[-1] == "__init__.py"
        source = rewrite_relative_imports(
            raw_source, name, is_package=is_package
        )
        dependencies: set[str] = set()
        for candidate in sorted(
            _candidate_module_names(extract_imports(source) or [])
        ):
            if candidate == name:
                continue
            if (
                find_local_module(
                    candidate, search_roots=search_roots, tree=tree
                )
                is not None
            ):
                dependencies.add(candidate)
                queue.append(candidate)
        # Python always imports a module's parent package first, so pull
        # parents in even when nothing imports them explicitly.
        parent = name.rpartition(".")[0]
        if (
            parent
            and find_local_module(parent, search_roots=search_roots, tree=tree)
            is not None
        ):
            queue.append(parent)
        modules[name] = _ResolvedModule(
            name=name,
            tree_item=item,
            source=source,
            is_package=is_package,
            dependencies=dependencies,
        )
    return modules


def _depends_transitively(
    edges: dict[str, set[str]], start: str, target: str
) -> bool:
    """Test whether ``start`` transitively depends on ``target``."""
    stack = [start]
    seen: set[str] = set()
    while stack:
        node = stack.pop()
        if node == target:
            return True
        if node in seen:
            continue
        seen.add(node)
        stack.extend(edges.get(node, ()))
    return False


def _order_modules(modules: dict[str, _ResolvedModule]) -> list[str]:
    """Order modules so that each module's dependencies execute first.

    Edges come from real import statements, plus a synthetic "submodule
    depends on its parent package" edge (Python executes ``__init__.py``
    before any submodule). The synthetic edge is skipped when the parent
    already depends on the child — the common case of an ``__init__.py``
    re-exporting from its own submodules, where the child's body must
    execute first — since sys.modules scaffolding makes either order valid
    for the parent binding itself.

    Raises
    ------
    CircularModuleImportError
        Raised if the real import edges form a cycle.
    """
    edges: dict[str, set[str]] = {
        name: {
            dep
            for dep in module.dependencies
            if dep in modules and dep != name
        }
        for name, module in modules.items()
    }
    for name in sorted(modules):
        parent = name.rpartition(".")[0]
        if (
            parent
            and parent in modules
            and not _depends_transitively(edges, parent, name)
        ):
            edges[name].add(parent)

    ordered: list[str] = []
    done: set[str] = set()
    path: list[str] = []
    path_set: set[str] = set()

    def visit(node: str) -> None:
        if node in done:
            return
        if node in path_set:
            cycle = [*path[path.index(node) :], node]
            raise CircularModuleImportError.for_cycle(cycle)
        path.append(node)
        path_set.add(node)
        for dep in sorted(edges[node]):
            visit(dep)
        path.pop()
        path_set.remove(node)
        done.add(node)
        ordered.append(node)

    for name in sorted(edges):
        visit(name)
    return ordered


def _build_scaffolding_source(modules: dict[str, _ResolvedModule]) -> str:
    """Generate the source of the scaffolding cell that creates a module
    object in ``sys.modules`` for every inlined module and package prefix,
    before any module body executes.
    """
    all_names: set[str] = set(modules)
    for name in modules:
        parts = name.split(".")
        all_names.update(".".join(parts[:i]) for i in range(1, len(parts)))
    package_names = sorted(
        name
        for name in all_names
        if name not in modules or modules[name].is_package
    )
    creation_order = sorted(all_names, key=lambda n: (n.count("."), n))
    dotted_names = [name for name in creation_order if "." in name]

    lines = [
        "# Scaffolding for local repository modules inlined by Times Square.",
        "import sys as _ts_sys",
        "import types as _ts_types",
        "",
        f"for _ts_name in {creation_order!r}:",
        "    _ts_sys.modules[_ts_name] = _ts_types.ModuleType(_ts_name)",
    ]
    if package_names:
        lines.extend(
            [
                f"for _ts_name in {package_names!r}:",
                "    _ts_sys.modules[_ts_name].__path__ = []",
            ]
        )
    cleanup = "del _ts_sys, _ts_types, _ts_name"
    if dotted_names:
        lines.extend(
            [
                f"for _ts_name in {dotted_names!r}:",
                '    _ts_parent, _, _ts_child = _ts_name.rpartition(".")',
                "    setattr(",
                "        _ts_sys.modules[_ts_parent],",
                "        _ts_child,",
                "        _ts_sys.modules[_ts_name],",
                "    )",
            ]
        )
        cleanup = "del _ts_sys, _ts_types, _ts_name, _ts_parent, _ts_child"
    lines.append(cleanup)
    return "\n".join(lines)


def _build_module_cell_source(module: _ResolvedModule) -> str:
    """Generate the source of the cell that executes an inlined module's
    body into its pre-scaffolded module object.

    The module source is base64-encoded to avoid any quoting or escaping
    issues.
    """
    encoded = base64.b64encode(module.source.encode("utf-8")).decode("ascii")
    return "\n".join(
        [
            f"# Times Square inlined local module: {module.name}",
            f"# Source: {module.tree_item.path}",
            "import base64 as _ts_base64",
            "import sys as _ts_sys",
            "",
            "exec(",
            "    compile(",
            f'        _ts_base64.b64decode("{encoded}").decode("utf-8"),',
            f'        "<times-square-inlined:{module.name}>",',
            '        "exec",',
            "    ),",
            f'    _ts_sys.modules["{module.name}"].__dict__,',
            ")",
            "del _ts_base64, _ts_sys",
        ]
    )


def _cell_id_for_module(module_name: str) -> str:
    """Generate a deterministic cell id for an inlined module's cell.

    Deterministic ids keep the prepared ipynb byte-identical across
    re-syncs of the same repository content (nbformat's default is a
    random UUID per generated cell). Cell ids must match
    ``^[a-zA-Z0-9-_]+$`` and be at most 64 characters.
    """
    return f"ts-mod-{module_name.replace('.', '-')}"[:64]


def _parameters_cell_index(notebook: nbformat.NotebookNode) -> int:
    """Find the index of the marked parameters cell (0 if none exists,
    which can only happen for a notebook without code cells).
    """
    return next(
        (
            i
            for i, cell in enumerate(notebook.cells)
            if cell.cell_type == "code"
            and cell.metadata.get("times_square", {}).get("cell_type")
            == "parameters"
        ),
        0,
    )


async def prepare_notebook_for_execution(
    *,
    notebook_source: str,
    notebook_path_prefix: str,
    tree: RepositoryTree,
    checkout: GitHubRepositoryCheckout,
    github_client: GitHubAPI,
    module_cache: LocalModuleCache,
) -> tuple[str, list[str]]:
    """Mark the parameters cell and inline local module imports for a
    freshly-fetched GitHub notebook.

    Local modules are searched for in the notebook's own directory first
    and then at the repository root, mirroring how the notebook would
    resolve imports when run interactively in JupyterLab.

    Parameters
    ----------
    notebook_source
        The raw ipynb JSON fetched from GitHub.
    notebook_path_prefix
        Repository-relative directory containing the notebook (``""`` for
        the repository root).
    tree
        The repository's full git tree.
    checkout
        The repository checkout, used to fetch module blobs.
    github_client
        GitHub client, ideally authorized as a GitHub installation.
    module_cache
        Blob-content cache shared across one sync or check-run pass.

    Returns
    -------
    tuple
        The final ipynb JSON string, and the dotted names of the inlined
        modules in execution order (empty if the notebook has no local
        imports).

    Raises
    ------
    timessquare.exceptions.PageNotebookFormatError
        Raised if the notebook source is not valid ipynb.
    PageModuleInlineError
        Raised if a local module's relative imports cannot be rewritten.
    CircularModuleImportError
        Raised if the local modules' imports form a cycle.
    """
    notebook = PageModel.read_ipynb(notebook_source)
    mark_notebook_parameters_cell(notebook)

    search_roots = [notebook_path_prefix]
    if notebook_path_prefix:
        search_roots.append("")

    candidates: set[str] = set()
    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue
        imports = extract_imports(cell.source)
        if imports:
            candidates.update(_candidate_module_names(imports))

    modules = await _collect_modules(
        candidates,
        search_roots=search_roots,
        tree=tree,
        checkout=checkout,
        github_client=github_client,
        module_cache=module_cache,
    )
    if not modules:
        return PageModel.write_ipynb(notebook), []

    ordered_names = _order_modules(modules)
    new_cells = [
        new_code_cell(
            source=_build_scaffolding_source(modules),
            metadata={"times_square": {"cell_type": "module_scaffolding"}},
            id="ts-module-scaffolding",
        )
    ]
    new_cells.extend(
        new_code_cell(
            source=_build_module_cell_source(modules[name]),
            metadata={
                "times_square": {
                    "cell_type": "inlined_module",
                    "module_name": name,
                    "source_path": modules[name].tree_item.path,
                }
            },
            id=_cell_id_for_module(name),
        )
        for name in ordered_names
    )
    insert_index = _parameters_cell_index(notebook)
    notebook.cells[insert_index:insert_index] = new_cells
    return PageModel.write_ipynb(notebook), ordered_names
