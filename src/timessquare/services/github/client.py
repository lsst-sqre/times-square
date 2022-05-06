"""Factories for creating GitHub API clients based on the application
configuration.
"""

from __future__ import annotations

from typing import Optional

import gidgethub.apps
import httpx
from gidgethub.httpx import GitHubAPI

from timessquare.config import config

__all__ = [
    "GitHubClientConfigError",
    "get_app_jwt",
    "create_github_installation_client",
]


class GitHubClientConfigError(Exception):
    """Raised if there is an error with the GitHub App's configuration."""


def get_app_jwt() -> str:
    """Create the GitHub App's JWT based on application configuration.

    This token is for authenticating as the GitHub App itself, as opposed to
    an installation of the app. See
    https://docs.github.com/en/developers/apps/building-github-apps/authenticating-with-github-apps#authenticating-as-a-github-app

    Parameters
    ----------
    http_client : httpx.AsyncClient
        The httpx client.

    Returns
    -------
    str
        The JWT token.

    Raises
    ------
    GitHubClientError
        Raised if there is an issue with the GitHub App configuration.
    """
    if config.github_app_private_key is None:
        raise GitHubClientConfigError(
            "The GitHub app private key is not configured."
        )
    private_key = config.github_app_private_key.get_secret_value()

    if config.github_app_id is None:
        raise GitHubClientConfigError("The GitHub app id is not configured.")
    app_id = config.github_app_id

    return gidgethub.apps.get_jwt(app_id=app_id, private_key=private_key)


def create_github_client(
    *, http_client: httpx.AsyncClient, oauth_token: Optional[str] = None
) -> GitHubAPI:
    """Create an HTTPx GitHub client.

    Parameters
    ----------
    http_client : httpx.AsyncClient
        The httpx client.
    oauth_token : str, optional
        If set, the client is authenticated with the oauth token (common
        for clients acting as an app installation or on behalf of a user).

    Returns
    -------
    gidgethub.httpx.GitHubAPI
    """
    return GitHubAPI(
        http_client, "lsst-sqre/times-square", oauth_token=oauth_token
    )


async def create_github_installation_client(
    *, http_client: httpx.AsyncClient, installation_id: str
) -> GitHubAPI:
    """Create a GitHub API client authorized as a GitHub App installation,
    with specific permissions on the repository/organization the app is
    installed into.

    Parameters
    ----------
    http_client : httpx.AsyncClient
        The httpx client.
    installation_id : str
        The installation ID, often obtained from a webhook payload
        (``installation.id`` path), or from the ``id`` key returned by
        `iter_installations`.

    Returns
    -------
    gidgethub.httpx.GitHubAPI
        The GitHub client with an embedded OAuth token that authenticates
        all requests as the GitHub app installation.
    """
    token = get_app_jwt()

    if config.github_app_id is None:
        raise GitHubClientConfigError("The GitHub app id is not configured.")
    app_id = config.github_app_id

    if config.github_app_private_key is None:
        raise GitHubClientConfigError(
            "The GitHub app private key is not configured."
        )
    private_key = config.github_app_private_key.get_secret_value()

    anon_gh_app = create_github_client(http_client=http_client)
    token_info = await gidgethub.apps.get_installation_access_token(
        anon_gh_app,
        installation_id=installation_id,
        app_id=app_id,
        private_key=private_key,
    )
    token = token_info["token"]

    # Generate a new client with the embedded OAuth token.
    gh = create_github_client(http_client=http_client, oauth_token=token)
    return gh
