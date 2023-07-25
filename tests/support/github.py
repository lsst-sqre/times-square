"""Mock GitHub API client."""

from __future__ import annotations

import json
from collections.abc import Mapping
from contextlib import suppress

import gidgethub.abc as gh_abc
from gidgethub import sansio

__all__ = ["MockGitHubAPI", "SAMPLE_PRIVATE_KEY"]


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
