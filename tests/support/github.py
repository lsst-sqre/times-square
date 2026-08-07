"""Mock GitHub API client."""

from __future__ import annotations

import base64
import json
from collections.abc import Mapping
from contextlib import suppress
from pathlib import Path
from typing import Any

import gidgethub.abc as gh_abc
import respx
from gidgethub import sansio
from httpx import Response

__all__ = [
    "CHECK_RUN_GIT_TREE",
    "SAMPLE_PRIVATE_KEY",
    "MockGitHubAPI",
    "MockGitHubCheckRunAPI",
    "MockGitHubRepoSyncAPI",
    "github_repository_payload",
    "mock_github_app_repository",
]

DATA = Path(__file__).parent.parent / "data"


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
    ) -> tuple[int, dict, dict]:
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
    """

    def __init__(
        self,
        *,
        check_run: dict[str, Any],
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
        self._contents_error = contents_error
        self._tree_error = tree_error
        self._blob_error = blob_error
        self._sidecar_content = sidecar_content
        self.requests: list[tuple[str, str]] = []
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
    ) -> tuple[int, dict, dict]:
        """Return the canned check-run object for every call, recording the
        bodies of PATCH requests (the in-progress and conclusion updates).

        The ``times-square.yaml`` Contents GET instead returns a valid,
        empty settings-file blob so a checkout can succeed, the recursive
        git tree GET returns `CHECK_RUN_GIT_TREE`, and the git blob GETs
        return ``sidecar_content`` when it was provided.
        """
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
        if method == "PATCH" and request_json is not None:
            self.patched.append(request_json)
        return 200, self._check_run, {}


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
