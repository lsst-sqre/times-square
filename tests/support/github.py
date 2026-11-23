"""Mock GitHub API client."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping, Sequence
from contextlib import suppress
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import quote, unquote, urlsplit

import gidgethub.abc as gh_abc
import respx
from gidgethub import sansio
from httpx import Response

__all__ = [
    "CHECK_RUN_GIT_TREE",
    "DATA",
    "SAMPLE_PRIVATE_KEY",
    "MockGitHubAPI",
    "MockGitHubCheckRunAPI",
    "MockGitHubRepoSyncAPI",
    "github_repository_payload",
    "mock_github_app_repository",
    "mock_github_repository_by_id",
]

DATA = Path(__file__).parent.parent / "data"
"""The directory holding the test data files."""


SAMPLE_PRIVATE_KEY = """-----BEGIN RSA PRIVATE KEY-----
MIIEpQIBAAKCAQEA1HgzBfJv2cOjQryCwe8NEelriOTNFWKZUivevUrRhlqcmZJd
CvuCJRr+xCN+OmO8qwgJJR98feNujxVg+J9Ls3/UOA4HcF9nYH6aqVXELAE8Hk/A
Lvxi96ms1DDuAvQGaYZ+lANxlvxeQFOZSbjkz/9mh8aLeGKwqJLp3p+OhUBQpwvA
UAPg82+OUtgTW3nSljjeFr14B8qAneGSc/wl0ni++1SRZUXFSovzcqQOkla3W27r
rLfrD6LXgj/TsDs4vD1PnIm1zcVenKT7TfYI17bsG/O/Wecwz2Nl19pL7gDosNru
F3ogJWNq1Lyn/ijPQnkPLpZHyhvuiycYcI3DiQIDAQABAoIBAQCt9uzwBZ0HVGQs
lGULnUu6SsC9iXlR9TVMTpdFrij4NODb7Tc5cs0QzJWkytrjvB4Se7XhK3KnMLyp
cvu/Fc7J3fRJIVN98t+V5pOD6rGAxlIPD4Vv8z6lQcw8wQNgb6WAaZriXh93XJNf
YBO2hSj0FU5CBZLUsxmqLQBIQ6RR/OUGAvThShouE9K4N0vKB2UPOCu5U+d5zS3W
44Q5uatxYiSHBTYIZDN4u27Nfo5WA+GTvFyeNsO6tNNWlYfRHSBtnm6SZDY/5i4J
fxP2JY0waM81KRvuHTazY571lHM/TTvFDRUX5nvHIu7GToBKahfVLf26NJuTZYXR
5c09GAXBAoGBAO7a9M/dvS6eDhyESYyCjP6w61jD7UYJ1fudaYFrDeqnaQ857Pz4
BcKx3KMmLFiDvuMgnVVj8RToBGfMV0zP7sDnuFRJnWYcOeU8e2sWGbZmWGWzv0SD
+AhppSZThU4mJ8aa/tgsepCHkJnfoX+3wN7S9NfGhM8GDGxTHJwBpxINAoGBAOO4
ZVtn9QEblmCX/Q5ejInl43Y9nRsfTy9lB9Lp1cyWCJ3eep6lzT60K3OZGVOuSgKQ
vZ/aClMCMbqsAAG4fKBjREA6p7k4/qaMApHQum8APCh9WPsKLaavxko8ZDc41kZt
hgKyUs2XOhW/BLjmzqwGryidvOfszDwhH7rNVmRtAoGBALYGdvrSaRHVsbtZtRM3
imuuOCx1Y6U0abZOx9Cw3PIukongAxLlkL5G/XX36WOrQxWkDUK930OnbXQM7ZrD
+5dW/8p8L09Zw2VHKmb5eK7gYA1hZim4yJTgrdL/Y1+jBDz+cagcfWsXZMNfAZxr
VLh628x0pVF/sof67pqVR9UhAoGBAMcQiLoQ9GJVhW1HMBYBnQVnCyJv1gjBo+0g
emhrtVQ0y6+FrtdExVjNEzboXPWD5Hq9oKY+aswJnQM8HH1kkr16SU2EeN437pQU
zKI/PtqN8AjNGp3JVgLioYp/pHOJofbLA10UGcJTMpmT9ELWsVA8P55X1a1AmYDu
y9f2bFE5AoGAdjo95mB0LVYikNPa+NgyDwLotLqrueb9IviMmn6zKHCwiOXReqXD
X9slB8RA15uv56bmN04O//NyVFcgJ2ef169GZHiRFIgIy0Pl8LYkMhCYKKhyqM7g
xN+SqGqDTKDC22j00S7jcvCaa1qadn1qbdfukZ4NXv7E2d/LO0Y2Kkc=
-----END RSA PRIVATE KEY-----

"""


class MockGitHubAPI(gh_abc.GitHubAPI):
    """A mock GitHub API client."""

    def __init__(
        self,
        oauth_token: str | None = None,
        cache: gh_abc.CACHE_TYPE | None = None,
        base_url: str = sansio.DOMAIN,
    ) -> None:
        super().__init__(
            "test_abc",
            oauth_token=oauth_token,
            cache=cache,
            base_url=base_url,
        )

    def create_response(
        self, method: str, url: str, request_json: dict | None
    ) -> tuple[int, Any, dict]:
        """Create a response to a request."""
        raise NotImplementedError(
            "create_response() must be implemented by subclasses"
        )

    async def _request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes = b"",
    ) -> tuple[int, Mapping[str, str], bytes]:
        """Make an HTTP request."""
        response_headers = self.default_headers
        request_json = (
            json.loads(body.decode("utf-8")) if body != b"" else None
        )
        response_code, response_obj, headers = self.create_response(
            method, url, request_json
        )
        response_headers.update(headers)
        response_body = json.dumps(response_obj).encode("utf-8")
        with suppress(KeyError):
            # Don't loop forever.
            del response_headers["link"]
        return response_code, response_headers, response_body

    async def sleep(self, seconds: float) -> None:
        """Sleep for the specified number of seconds."""
        self.slept = seconds

    @property
    def default_headers(self) -> dict[str, str]:
        """Get the default headers."""
        return {
            "x-ratelimit-limit": "2",
            "x-ratelimit-remaining": "1",
            "x-ratelimit-reset": "0",
            "content-type": gh_abc.JSON_UTF_8_CHARSET,
        }


CHECK_RUN_GIT_TREE: dict[str, Any] = {
    "sha": "abc123",
    "url": "https://api.github.com/repos/x/y/git/trees/abc123",
    "truncated": False,
    "tree": [
        {
            "path": "demo.ipynb",
            "mode": "100644",
            "sha": "notebooksha",
            "url": "https://api.github.com/repos/x/y/git/blobs/notebooksha",
        },
        {
            "path": "demo.yaml",
            "mode": "100644",
            "sha": "sidecarsha",
            "url": "https://api.github.com/repos/x/y/git/blobs/sidecarsha",
        },
    ],
}
"""Canned recursive git tree with a single notebook/sidecar pair, enough for
`GitHubRepositoryCheckout` to find one notebook to load.
"""


def _blob(content: bytes) -> dict[str, Any]:
    """Build a GitHub git blob response body carrying ``content``."""
    encoded = base64.b64encode(content).decode()
    return {
        "content": encoded,
        "encoding": "base64",
        "url": "https://api.github.com/repos/x/y/git/blobs/abc123",
        "sha": "abc123",
        "size": len(encoded),
    }


class MockGitHubCheckRunAPI(MockGitHubAPI):
    """A concrete `MockGitHubAPI` for exercising the GitHub check-run flow.

    It records every request, returns a canned check-run object for the
    check-run POST/PATCH calls, and can be configured to raise a persistent
    error on the ``times-square.yaml`` Contents GET (``contents_error``), on
    the recursive git tree GET (``tree_error``), or on the git blob GETs that
    back notebook and sidecar loading (``blob_error``). Passing an
    ``httpx.ReadTimeout`` (or another transient error) simulates GitHub
    slowness that outlasts the retry budget; passing a non-transient error
    simulates an unexpected failure that should propagate.

    When ``contents_error`` is not set, the Contents GET returns a valid,
    empty ``times-square.yaml`` blob so the checkout succeeds. When
    ``tree_error`` is not set, the git tree GET returns `CHECK_RUN_GIT_TREE`,
    so the check reaches the notebook-loading blob GETs. Pass
    ``sidecar_content`` to serve that YAML as the body of every git blob GET,
    which is what the configs check reads as the notebook's sidecar file;
    without it there is no canned content behind those GETs and they are only
    meaningful with ``blob_error`` set.

    The installed repository's branches, which decide whether a commit's
    notebooks may be checked at all, are modeled on what GitHub returns:

    ``branches``
        Maps each branch of the installed repository to its history, newest
        commit first. A commit that is only in a fork is in none of them.
        This backs the "list branches for HEAD commit", "get a branch", and
        "compare two commits" GETs. Compare reports ``identical`` or
        ``behind`` when the head commit is in the base commit's history,
        ``ahead`` when the base commit is in the head commit's history, and
        otherwise ``diverged``. Compared against a branch of the base
        repository, a fork's commit is ``ahead`` if it was made on top of the
        branch's tip, and ``diverged`` if the branch has moved on since or
        the commit shares none of its history.
    ``renamed_branches``
        Maps the old names of renamed branches to their new names. As on
        GitHub, "get a branch" answers an old name with a 301 redirect to
        the new name, and the old name is not otherwise a branch.
    ``fork_commits``
        Maps commits that are only in a fork to their parent commits, which
        may be on a branch of the installed repository. A fork's commit that
        is not listed here shares no history with the installed repository.
    ``pull_heads``
        Maps pull request numbers to head commits. GitHub keeps a
        ``refs/pull/N/head`` ref in the base repository for every pull
        request, including one from a fork, and the compare GET resolves
        ``pull/N/head`` through it just as GitHub does. "Get a branch" does
        not, since that ref is not a branch.
    ``check_suite_head_branch``
        The ``head_branch`` that the "get a check suite" GET reports. For a
        fork's commit, GitHub reports `None` for a third-party app's check
        suite, such as Times Square's. Only GitHub Actions' own check suites
        report the name of the fork's branch.
    ``commit_pulls``
        Maps commits to what the "list pull requests associated with a
        commit" GET returns for them, which is no pull requests by default.
        Through the base repository, that is also what GitHub returns for the
        head commit of an open pull request from a fork. Times Square doesn't
        use this endpoint, which is exactly why: tests set it to what GitHub
        returns so that they fail if the check run service goes back to
        judging a commit's source by its pull requests.
    ``error_statuses``
        Maps regular expressions to HTTP error statuses. A GET of one of the
        endpoints above whose URL path matches an expression responds with
        that status instead.
    """

    def __init__(
        self,
        *,
        check_run: dict[str, Any],
        branches: Mapping[str, Sequence[str]] | None = None,
        renamed_branches: Mapping[str, str] | None = None,
        fork_commits: Mapping[str, str] | None = None,
        pull_heads: Mapping[int, str] | None = None,
        check_suite_head_branch: str | None = None,
        commit_pulls: Mapping[str, list[dict[str, Any]]] | None = None,
        error_statuses: Mapping[str, int] | None = None,
        contents_error: BaseException | None = None,
        tree_error: BaseException | None = None,
        blob_error: BaseException | None = None,
        sidecar_content: str | None = None,
        oauth_token: str | None = None,
        cache: gh_abc.CACHE_TYPE | None = None,
        base_url: str = sansio.DOMAIN,
    ) -> None:
        super().__init__(
            oauth_token=oauth_token, cache=cache, base_url=base_url
        )
        self._check_run = check_run
        self._branches = {
            name: list(history) for name, history in (branches or {}).items()
        }
        self._renamed_branches = dict(renamed_branches or {})
        self._fork_commits = dict(fork_commits or {})
        self._pull_heads = dict(pull_heads or {})
        self._check_suite_head_branch = check_suite_head_branch
        self._commit_pulls = dict(commit_pulls or {})
        self._error_statuses = dict(error_statuses or {})
        self._contents_error = contents_error
        self._tree_error = tree_error
        self._blob_error = blob_error
        self._sidecar_content = sidecar_content
        self.requests: list[tuple[str, str]] = []
        self.posted: list[dict[str, Any]] = []
        self.patched: list[dict[str, Any]] = []

    async def _request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes = b"",
    ) -> tuple[int, Mapping[str, str], bytes]:
        self.requests.append((method, url))
        if (
            self._contents_error is not None
            and method == "GET"
            and "times-square.yaml" in url
        ):
            raise self._contents_error
        if (
            self._tree_error is not None
            and method == "GET"
            and "git/trees" in url
        ):
            raise self._tree_error
        if (
            self._blob_error is not None
            and method == "GET"
            and "git/blobs" in url
        ):
            raise self._blob_error
        return await super()._request(method, url, headers, body)

    def create_response(
        self, method: str, url: str, request_json: dict | None
    ) -> tuple[int, Any, dict]:
        """Return the canned check-run object for every call, recording the
        bodies of POST requests (check run creation) and PATCH requests (the
        in-progress and conclusion updates).

        The ``times-square.yaml`` Contents GET instead returns a valid,
        empty settings-file blob so a checkout can succeed, the recursive
        git tree GET returns `CHECK_RUN_GIT_TREE`, and the git blob GETs
        return ``sidecar_content`` when it was provided. The branch, compare,
        check suite, and commit pull request GETs are answered from the
        modeled repository state.
        """
        if method == "GET" and (
            response := self._repository_state_response(url)
        ):
            return response
        if method == "GET" and "times-square.yaml" in url:
            return 200, _blob(b'root: ""\n'), {}
        if method == "GET" and "git/trees" in url:
            return 200, CHECK_RUN_GIT_TREE, {}
        if (
            method == "GET"
            and "git/blobs" in url
            and self._sidecar_content is not None
        ):
            return 200, _blob(self._sidecar_content.encode()), {}
        if method == "POST" and request_json is not None:
            self.posted.append(request_json)
        if method == "PATCH" and request_json is not None:
            self.patched.append(request_json)
        return 200, self._check_run, {}

    def _repository_state_response(
        self, url: str
    ) -> tuple[int, Any, dict] | None:
        """Answer a GET from the modeled repository state, or return `None`
        if the URL is not one of the modeled endpoints.
        """
        path = urlsplit(url).path
        repo_url = "/".join(url.split("/")[:6])
        for pattern, status in self._error_statuses.items():
            if re.search(pattern, path):
                return status, {"message": HTTPStatus(status).phrase}, {}
        if m := re.search(r"/commits/(\w+)/branches-where-head$", path):
            return (
                200,
                [
                    self._branch_object(repo_url, name)
                    for name, history in self._branches.items()
                    if history[0] == m[1]
                ],
                {},
            )
        if m := re.search(r"/commits/(\w+)/pulls$", path):
            return 200, self._commit_pulls.get(m[1], []), {}
        if m := re.search(r"/branches/(.+)$", path):
            name = unquote(m[1])
            if name in self._renamed_branches:
                new_url = (
                    f"{repo_url}/branches/"
                    f"{quote(self._renamed_branches[name], safe='')}"
                )
                return (
                    301,
                    {
                        "message": "Moved Permanently",
                        "url": new_url,
                        "documentation_url": (
                            "https://docs.github.com/rest/guides/"
                            "best-practices-for-using-the-rest-api"
                            "#follow-redirects"
                        ),
                    },
                    {"location": new_url},
                )
            if name not in self._branches:
                return 404, {"message": "Branch not found"}, {}
            return 200, self._branch_object(repo_url, name), {}
        if m := re.search(r"/compare/(.+)\.\.\.(.+)$", path):
            base = self._resolve_ref(unquote(m[1]))
            head = self._resolve_ref(unquote(m[2]))
            if base is None or head is None:
                return 404, {"message": "Not Found"}, {}
            return 200, self._compare(base, head), {}
        if m := re.search(r"/check-suites/(\d+)$", path):
            return (
                200,
                {
                    "id": int(m[1]),
                    "head_branch": self._check_suite_head_branch,
                },
                {},
            )
        return None

    def _branch_object(self, repo_url: str, name: str) -> dict[str, Any]:
        sha = self._branches[name][0]
        return {
            "name": name,
            "commit": {"sha": sha, "url": f"{repo_url}/commits/{sha}"},
            "protected": False,
        }

    def _resolve_ref(self, ref: str) -> str | None:
        """Resolve a branch name, pull request ref, or commit SHA to a commit
        the way the compare API does.
        """
        if ref in self._branches:
            return self._branches[ref][0]
        if m := re.fullmatch(r"(?:refs/)?pull/(\d+)/head", ref):
            return self._pull_heads.get(int(m[1]))
        if re.fullmatch(r"[0-9a-f]{40}", ref):
            # GitHub resolves any commit in the repository's fork network.
            return ref
        return None

    def _history(self, sha: str) -> list[str]:
        """Get the commits reachable from a commit, newest first."""
        if sha in self._fork_commits:
            return [sha, *self._history(self._fork_commits[sha])]
        for history in self._branches.values():
            if sha in history:
                return history[history.index(sha) :]
        return [sha]

    def _compare(self, base: str, head: str) -> dict[str, Any]:
        base_history = self._history(base)
        head_history = self._history(head)
        if head == base:
            status, ahead_by, behind_by = "identical", 0, 0
        elif head in base_history:
            status, ahead_by, behind_by = (
                "behind",
                0,
                base_history.index(head),
            )
        elif base in head_history:
            status, ahead_by, behind_by = "ahead", head_history.index(base), 0
        else:
            status, ahead_by, behind_by = "diverged", 1, 1
        return {"status": status, "ahead_by": ahead_by, "behind_by": behind_by}


class MockGitHubRepoSyncAPI(MockGitHubAPI):
    """A concrete `MockGitHubAPI` serving the reads a repository sync makes.

    A sync reads the ``times-square.yaml`` settings file, the recursive git
    tree (`CHECK_RUN_GIT_TREE`, which holds one ``demo.ipynb`` /
    ``demo.yaml`` pair), and the git blobs behind that pair. When
    ``repository`` is given, the repository resource and its default
    branch are served too, which is what the app-installation sync path
    reads before it builds a checkout.
    """

    def __init__(
        self,
        *,
        notebook_source: str,
        sidecar_content: str,
        settings_content: str = 'root: ""\n',
        repository: dict[str, Any] | None = None,
        head_sha: str = "abc123",
        oauth_token: str | None = None,
        cache: gh_abc.CACHE_TYPE | None = None,
        base_url: str = sansio.DOMAIN,
    ) -> None:
        super().__init__(
            oauth_token=oauth_token, cache=cache, base_url=base_url
        )
        self._notebook_source = notebook_source
        self._sidecar_content = sidecar_content
        self._settings_content = settings_content
        self._repository = repository
        self._head_sha = head_sha
        self.requests: list[tuple[str, str]] = []

    async def _request(
        self,
        method: str,
        url: str,
        headers: Mapping[str, str],
        body: bytes = b"",
    ) -> tuple[int, Mapping[str, str], bytes]:
        self.requests.append((method, url))
        return await super()._request(method, url, headers, body)

    def create_response(
        self, method: str, url: str, request_json: dict | None
    ) -> tuple[int, dict, dict]:
        """Serve the settings file, git tree, git blobs, repository, and
        default branch that a repository sync reads.
        """
        if "times-square.yaml" in url:
            return 200, _blob(self._settings_content.encode()), {}
        if "git/trees" in url:
            return 200, CHECK_RUN_GIT_TREE, {}
        if "git/blobs/notebooksha" in url:
            return 200, _blob(self._notebook_source.encode()), {}
        if "git/blobs/sidecarsha" in url:
            return 200, _blob(self._sidecar_content.encode()), {}
        if "/branches/" in url and self._repository is not None:
            return (
                200,
                {
                    "name": self._repository["default_branch"],
                    "commit": {
                        "sha": self._head_sha,
                        "url": (
                            "https://api.github.com/repos/x/y/commits/"
                            f"{self._head_sha}"
                        ),
                    },
                },
                {},
            )
        if self._repository is not None:
            return 200, self._repository, {}
        raise AssertionError(f"Unexpected GitHub request: {method} {url}")


def github_repository_payload(
    *, owner: str, repo: str, repository_id: int, owner_id: int
) -> dict[str, Any]:
    """Build a GitHub repository resource, based on the recorded push event
    fixture, under the given names and numeric IDs.
    """
    payload = json.loads(
        (DATA / "github_webhooks" / "push_event.json").read_text()
    )["repository"]
    payload["id"] = repository_id
    payload["name"] = repo
    payload["full_name"] = f"{owner}/{repo}"
    payload["owner"]["login"] = owner
    payload["owner"]["id"] = owner_id
    return payload


def mock_github_app_repository(
    respx_mock: respx.Router,
    *,
    owner: str,
    repo: str,
    installation_id: int,
    repository_id: int,
    owner_id: int,
) -> None:
    """Route the three GitHub App calls that resolve one repository's numeric
    identity: its installation, that installation's access token, and the
    repository resource itself.
    """
    respx_mock.get(
        f"https://api.github.com/repos/{owner}/{repo}/installation"
    ).mock(return_value=Response(200, json={"id": installation_id}))
    respx_mock.post(
        "https://api.github.com/app/installations/"
        f"{installation_id}/access_tokens"
    ).mock(
        return_value=Response(
            201,
            json={"token": "installation-token", "expires_at": "2100-01-01"},
        )
    )
    respx_mock.get(f"https://api.github.com/repos/{owner}/{repo}").mock(
        return_value=Response(
            200,
            json=github_repository_payload(
                owner=owner,
                repo=repo,
                repository_id=repository_id,
                owner_id=owner_id,
            ),
        )
    )


def mock_github_repository_by_id(
    respx_mock: respx.Router,
    *,
    repository_id: int,
    installation_id: int,
    owner: str,
    repo: str,
    owner_id: int,
) -> None:
    """Route the two GitHub App calls that re-read one repository by its
    numeric ID: the installation's access token, and the repository resource
    itself, which answers under whatever names the repository carries now.
    """
    respx_mock.post(
        "https://api.github.com/app/installations/"
        f"{installation_id}/access_tokens"
    ).mock(
        return_value=Response(
            201,
            json={"token": "installation-token", "expires_at": "2100-01-01"},
        )
    )
    respx_mock.get(
        f"https://api.github.com/repositories/{repository_id}"
    ).mock(
        return_value=Response(
            200,
            json=github_repository_payload(
                owner=owner,
                repo=repo,
                repository_id=repository_id,
                owner_id=owner_id,
            ),
        )
    )
