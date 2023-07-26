from pathlib import Path
from urllib.parse import quote, urlencode

from documenteer.conf.guide import *


def create_github_app_qs(domain="data-dev.lsst.cloud"):
    """Create a URL query string with the GitHub App configuration.

    See
    https://docs.github.com/en/apps/creating-github-apps/setting-up-a-github-app/creating-a-github-app-using-url-parameters

    Parameters
    ----------
    domain : `str`, optional
        The domain name of the RSP environment. This is used to template some
        of the GitHub App configuration.

    Returns
    -------
    qs : `str`
        The query string with the GitHub App configuration.
    """
    parameters = [
        ("name", f"Times Square ({domain})"),
        (
            "description",
            "Times Square is a service for parameterized Jupyter Notebooks as "
            "dynamic webpages. An instance of the Times Square app "
            "is associated with each "
            "[RSP environment]("
            "https://phalanx.lsst.io/environments/index.html).",
        ),
        ("url", "https://{domain}/times-square/"),
        ("public", "false"),
        ("webhook_active", "true"),
        ("webhook_url", f"https://{domain}/times-square/api/github/webhook"),
        ("events[]", "push"),
        ("events[]", "check_run"),
        ("events[]", "check_suite"),
        ("events[]", "pull_request"),
        ("events[]", "repository"),
        ("contents", "read"),
        ("pull_requests", "read"),
        ("checks", "write"),
    ]
    return urlencode(parameters, quote_via=quote)


def format_org_url(org="lsst-sqre", domain="data-dev.lsst.cloud"):
    """Format the URL creating the app for an organization.

    Parameters
    ----------
    org : `str`, optional
        The GitHub organization name where the app is created.
    domain : `str`, optional
        The domain name of the RSP environment. This is used to template some
        of the GitHub App configuration.

    Returns
    -------
    url : `str`
        The URL to create the GitHub App.
    """
    qs = create_github_app_qs(domain=domain)
    url = f"https://github.com/organizations/{org}/settings/apps/new?{qs}"
    return url


def format_personal_url(domain="data-dev.lsst.cloud"):
    """Format the URL creating the app for a user account.

    Parameters
    ----------
    domain : `str`, optional
        The domain name of the RSP environment. This is used to template some
        of the GitHub App configuration.

    Returns
    -------
    url : `str`
        The URL to create the GitHub App.
    """
    qs = create_github_app_qs(domain=domain)
    url = f"https://github.com/settings/apps/new?{qs}"
    return url


# Generate the URLs and write them as files that are included as code blocks
# in the Sphinx documentation.
org_install_path = Path("user-guide/_github-app-url-org.txt")
org_install_path.write_text(format_org_url())

personal_install_path = Path("user-guide/_github-app-url-personal.txt")
personal_install_path.write_text(format_personal_url())

exclude_patterns.append("**/_*.txt")
