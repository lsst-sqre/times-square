"""Tests for the githubtree domain models."""

from __future__ import annotations

from timessquare.domain.githubtree import (
    GitHubNode,
    GitHubNodeType,
    GitHubTreeQueryResult,
)


def test_githubtreenode() -> None:
    """Test the construction of a GitHubNode from mock GitHubTreeInputs with
    a null GitHub commit.
    """
    mock_sql_results = [
        [
            "lsst-sqre",
            "times-square-demo",
            None,
            "",
            "Alpha",
            "alpha",
        ],
        [
            "lsst-sqre",
            "times-square-demo",
            None,
            "",
            "Beta",
            "beta",
        ],
        [
            "lsst-sqre",
            "times-square-demo",
            None,
            "subdir",
            "Gamma",
            "gamma",
        ],
    ]
    tree_inputs = [
        GitHubTreeQueryResult(
            github_owner=str(row[0]),
            github_repo=str(row[1]),
            github_commit=row[2],
            path_prefix=str(row[3]),
            title=str(row[4]),
            path_stem=str(row[5]),
        )
        for row in mock_sql_results
    ]

    owner_node = GitHubNode(
        node_type=GitHubNodeType.owner,
        title="lsst-sqre",
        path_segments=["lsst-sqre"],
        github_commit=None,
        contents=[],
    )
    for tree_input in tree_inputs:
        owner_node.insert_node(tree_input)

    assert owner_node.title == "lsst-sqre"
    assert owner_node.contents[0].title == "times-square-demo"
    repo_node = owner_node.contents[0]
    assert repo_node.node_type == GitHubNodeType.repo

    assert repo_node.contents[0].title == "Alpha"
    assert repo_node.contents[0].squareone_path == (
        "lsst-sqre/times-square-demo/alpha"
    )

    assert repo_node.contents[1].title == "Beta"

    assert repo_node.contents[2].title == "subdir"
    dir_node = repo_node.contents[2]
    assert dir_node.contents[0].title == "Gamma"
    assert dir_node.contents[0].squareone_path == (
        "lsst-sqre/times-square-demo/subdir/gamma"
    )


def test_githubprtreenode() -> None:
    """Test the construction of a GitHubPrNode from mock inputs."""
    mock_sql_results = [
        [
            "lsst-sqre",
            "times-square-demo",
            "e35e1d5c485531ba9e99081c52dbdc5579e00556",
            "",
            "Alpha",
            "alpha",
        ],
        [
            "lsst-sqre",
            "times-square-demo",
            "e35e1d5c485531ba9e99081c52dbdc5579e00556",
            "",
            "Beta",
            "beta",
        ],
        [
            "lsst-sqre",
            "times-square-demo",
            "e35e1d5c485531ba9e99081c52dbdc5579e00556",
            "subdir",
            "Gamma",
            "gamma",
        ],
    ]
    tree_inputs = [
        GitHubTreeQueryResult(
            github_owner=str(row[0]),
            github_repo=str(row[1]),
            github_commit=row[2],
            path_prefix=str(row[3]),
            title=str(row[4]),
            path_stem=str(row[5]),
        )
        for row in mock_sql_results
    ]

    repo_node = GitHubNode(
        node_type=GitHubNodeType.repo,
        title="times-square-demo",
        path_segments=["lsst-sqre", "times-square-demo"],
        github_commit="e35e1d5c485531ba9e99081c52dbdc5579e00556",
        contents=[],
    )
    for tree_input in tree_inputs:
        repo_node.insert_node(tree_input)

    assert repo_node.contents[0].title == "Alpha"
    assert repo_node.contents[0].squareone_path == (
        "lsst-sqre/times-square-demo/e35e1d5c485531ba9e99081c52dbdc5579e00556"
        "/alpha"
    )
    assert repo_node.contents[1].title == "Beta"
    assert repo_node.contents[1].squareone_path == (
        "lsst-sqre/times-square-demo/e35e1d5c485531ba9e99081c52dbdc5579e00556"
        "/beta"
    )
    assert repo_node.contents[2].title == "subdir"
    dir_node = repo_node.contents[2]
    assert dir_node.contents[0].title == "Gamma"
    assert dir_node.contents[0].squareone_path == (
        "lsst-sqre/times-square-demo/e35e1d5c485531ba9e99081c52dbdc5579e00556"
        "/subdir/gamma"
    )


def _make_tree_inputs(
    prefixes_and_stems: list[tuple[str, str]], github_commit: str | None
) -> list[GitHubTreeQueryResult]:
    return [
        GitHubTreeQueryResult(
            github_owner="lsst-sqre",
            github_repo="times-square-demo",
            github_commit=github_commit,
            path_prefix=prefix,
            title=stem.capitalize(),
            path_stem=stem,
        )
        for prefix, stem in prefixes_and_stems
    ]


def test_owner_tree_dedups_nested_directories() -> None:
    """Multiple pages sharing a multi-segment prefix produce a single
    directory node per path segment in an owner-rooted tree.
    """
    tree_inputs = _make_tree_inputs(
        [
            ("sst/mtm1m3", "alpha"),
            ("sst/mtm1m3", "beta"),
            ("sst/mtm1m3", "gamma"),
        ],
        github_commit=None,
    )
    root = GitHubNode.create_with_owner_root(tree_inputs)

    repo_node = root.contents[0]
    assert len(repo_node.contents) == 1
    sst_node = repo_node.contents[0]
    assert sst_node.node_type == GitHubNodeType.directory
    assert sst_node.title == "sst"

    assert len(sst_node.contents) == 1
    mtm1m3_node = sst_node.contents[0]
    assert mtm1m3_node.node_type == GitHubNodeType.directory
    assert mtm1m3_node.title == "mtm1m3"

    assert len(mtm1m3_node.contents) == 3
    assert [page.title for page in mtm1m3_node.contents] == [
        "Alpha",
        "Beta",
        "Gamma",
    ]
    assert mtm1m3_node.contents[0].squareone_path == (
        "lsst-sqre/times-square-demo/sst/mtm1m3/alpha"
    )


def test_owner_tree_dedups_deeply_nested_directories() -> None:
    """Pages nested 3+ directory levels deep share directory nodes with
    pages at shallower levels of the same path.
    """
    tree_inputs = _make_tree_inputs(
        [
            ("sst/mtm1m3/actuators", "alpha"),
            ("sst/mtm1m3/actuators", "beta"),
            ("sst/mtm1m3", "gamma"),
            ("sst", "delta"),
        ],
        github_commit=None,
    )
    root = GitHubNode.create_with_owner_root(tree_inputs)

    repo_node = root.contents[0]
    assert len(repo_node.contents) == 1
    sst_node = repo_node.contents[0]
    assert sst_node.title == "sst"

    # sst contains one mtm1m3 directory and the delta page
    assert len(sst_node.contents) == 2
    mtm1m3_node = sst_node.contents[0]
    assert mtm1m3_node.node_type == GitHubNodeType.directory
    assert mtm1m3_node.title == "mtm1m3"
    assert sst_node.contents[1].title == "Delta"

    # mtm1m3 contains one actuators directory and the gamma page
    assert len(mtm1m3_node.contents) == 2
    actuators_node = mtm1m3_node.contents[0]
    assert actuators_node.node_type == GitHubNodeType.directory
    assert actuators_node.title == "actuators"
    assert mtm1m3_node.contents[1].title == "Gamma"

    assert len(actuators_node.contents) == 2
    assert [page.title for page in actuators_node.contents] == [
        "Alpha",
        "Beta",
    ]
    assert actuators_node.contents[0].squareone_path == (
        "lsst-sqre/times-square-demo/sst/mtm1m3/actuators/alpha"
    )


def test_repo_tree_dedups_nested_directories() -> None:
    """Multiple pages sharing a multi-segment prefix produce a single
    directory node per path segment in a repo-rooted (PR preview) tree.
    """
    commit = "e35e1d5c485531ba9e99081c52dbdc5579e00556"
    tree_inputs = _make_tree_inputs(
        [
            ("sst/mtm1m3", "alpha"),
            ("sst/mtm1m3", "beta"),
            ("sst/mtm1m3/actuators", "gamma"),
            ("sst/mtm1m3/actuators", "delta"),
        ],
        github_commit=commit,
    )
    root = GitHubNode.create_with_repo_root(tree_inputs)

    assert len(root.contents) == 1
    sst_node = root.contents[0]
    assert sst_node.node_type == GitHubNodeType.directory
    assert sst_node.title == "sst"

    assert len(sst_node.contents) == 1
    mtm1m3_node = sst_node.contents[0]
    assert mtm1m3_node.node_type == GitHubNodeType.directory
    assert mtm1m3_node.title == "mtm1m3"

    # mtm1m3 contains the alpha and beta pages and one actuators directory
    assert len(mtm1m3_node.contents) == 3
    assert mtm1m3_node.contents[0].title == "Alpha"
    assert mtm1m3_node.contents[1].title == "Beta"
    actuators_node = mtm1m3_node.contents[2]
    assert actuators_node.node_type == GitHubNodeType.directory
    assert actuators_node.title == "actuators"

    assert len(actuators_node.contents) == 2
    assert [page.title for page in actuators_node.contents] == [
        "Gamma",
        "Delta",
    ]
    assert actuators_node.contents[0].squareone_path == (
        f"lsst-sqre/times-square-demo/{commit}/sst/mtm1m3/actuators/gamma"
    )
