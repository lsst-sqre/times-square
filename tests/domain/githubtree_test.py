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
    print(owner_node)

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
