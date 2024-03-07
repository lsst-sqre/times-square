"""Request and response models for the v1 API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from urllib.parse import urlencode

from fastapi import Request
from markdown_it import MarkdownIt
from pydantic import AnyHttpUrl, BaseModel, EmailStr, Field, HttpUrl
from safir.github.models import (
    GitHubCheckRunConclusion,
    GitHubCheckRunModel,
    GitHubCheckRunStatus,
    GitHubPullRequestModel,
    GitHubPullState,
)
from safir.metadata import Metadata as SafirMetadata

from timessquare.domain.githubtree import GitHubNode, GitHubNodeType
from timessquare.domain.nbhtml import NbHtmlModel
from timessquare.domain.page import PageModel, PageSummaryModel, PersonModel


class Index(BaseModel):
    """Metadata returned by the external root URL of the application."""

    metadata: SafirMetadata = Field(..., title="Package metadata")

    api_docs: AnyHttpUrl = Field(..., title="Browsable API documentation")


page_name_field = Field(
    ...,
    examples=["summit-weather"],
    title="Page name",
    description="The name is used as the page's API URL slug.",
)

page_title_field = Field(
    ...,
    examples=["Summit Weather"],
    title="Page title",
    description="The display title (plain text).",
)

page_description_field = Field(
    ...,
    title="Page description",
    description=(
        "The description is available as both HTML and GitHub-flavored "
        "Markdown."
    ),
)

page_cache_ttl_field: int | None = Field(
    None,
    examples=[864000],
    title="Page title",
    description="The display title (plain text).",
)

page_date_added_field = Field(
    ...,
    title="Date added",
    description="Date when the page was originally added.",
)

page_authors_field = Field(
    default_factory=list,
    title="Page authors",
    description="Authors of the page",
)

page_tags_field = Field(default_factory=list, title="Tags (keywords)")

page_url_field = Field(
    ...,
    examples=["https://example.com/v1/pages/summit-weather"],
    title="Page resource URL.",
    description="API URL for the page's metadata resource.",
)

page_source_field = Field(
    ...,
    examples=["https://example.com/v1/pages/summit-weather/source"],
    title="Source ipynb URL",
    description="The URL for the source ipynb file (JSON-formatted)",
)

page_parameters_field = Field(
    ...,
    examples=[
        {"units": {"enum": ["metric", "imperial"], "default": "metric"}}
    ],
    title="Parameters",
    description="Parameters and their JSON Schema descriptions.",
)

page_rendered_field = Field(
    ...,
    examples=["https://example.com/v1/pages/summit-weather/rendered"],
    title="Rendered notebook template URL",
    description=(
        "The URL for the source notebook rendered with parameter values "
        "(JSON-formatted)."
    ),
)

page_html_field = Field(
    ...,
    examples=["https://example.com/v1/pages/summit-weather/html"],
    title="HTML view of computed notebook",
    description=(
        "The URL for the HTML-rendering of the notebook, computed with "
        "parameter values."
    ),
)

page_html_status_field = Field(
    ...,
    examples=["https://example.com/v1/pages/summit-weather/htmlstatus"],
    title="URL for the status of the HTML view of a notebook",
    description=(
        "The status URL for the HTML-rendering of the notebook, computed with "
        "parameter values."
    ),
)

ipynb_field = Field(
    ...,
    examples=["{...}"],
    title="ipynb",
    description="The JSON-encoded notebook content.",
)


class FormattedText(BaseModel):
    """Text that is formatted in both markdown and HTML."""

    gfm: str = Field(title="The GitHub-flavored Markdown-formatted text.")

    html: str = Field(title="The HTML-formatted text.")

    @classmethod
    def from_gfm(cls, gfm_text: str, *, inline: bool = False) -> FormattedText:
        """Create formatted text from GitHub-flavored markdown.

        Parameters
        ----------
        gfm_text : `str`
            GitHub flavored markdown.
        inline : `bool`
            If `True`, no paragraph tags are added to the HTML content.

        Returns
        -------
        `FormattedText`
            The formatted text, containing both markdown and HTML renderings.
        """
        md_parser = MarkdownIt("gfm-like")
        if inline:
            html_text = md_parser.renderInline(gfm_text)
        else:
            html_text = md_parser.render(gfm_text)
        return cls(gfm=gfm_text, html=html_text)


class Person(BaseModel):
    """A description of a person, such as an author."""

    name: str = Field(..., examples=["Vera Rubin"], title="Display name")

    username: str | None = Field(None, examples=["vera"], title="RSP username")
    """A person's RSP username."""

    affiliation_name: str | None = Field(None, examples=["Rubin/AURA"])
    """Display name of a person's main affiliation."""

    email: EmailStr | None = Field(None, title="Email")
    """A person's email."""

    slack_name: str | None = Field(None, title="LSSTC Slack username")
    """A person's Slack handle."""

    @classmethod
    def from_domain(cls, *, person: PersonModel) -> Person:
        return cls(
            name=person.name,
            username=person.username,
            affiliation_name=person.affiliation_name,
            slack_name=person.slack_name,
        )

    def to_domain(self) -> PersonModel:
        return PersonModel(
            name=self.name,
            username=self.username,
            email=self.email,
            slack_name=self.slack_name,
        )


class GitHubSourceMetadata(BaseModel):
    """Information about a page's source on GitHub."""

    owner: str = Field(title="GitHub owner name (organization or username)")

    repository: str = Field(title="GitHub repository name")

    source_path: str = Field(title="Repository path of the source notebook")

    sidecar_path: str = Field(title="Repository path of the sidecar YAML file")

    @classmethod
    def from_domain(cls, *, page: PageModel) -> GitHubSourceMetadata:
        # Checks are to help mypy distinguish a GitHub-based page
        if page.github_owner is None:
            raise RuntimeError("GitHub owner is None")
        if page.github_repo is None:
            raise RuntimeError("GitHub repo is None")
        sidecar_path = page.repository_sidecar_path
        source_path = page.repository_source_path
        if sidecar_path is None:
            raise RuntimeError("Sidecar path is None")
        if source_path is None:
            raise RuntimeError("Source path is None")
        return cls(
            owner=page.github_owner,
            repository=page.github_repo,
            source_path=source_path,
            sidecar_path=sidecar_path,
        )


class Page(BaseModel):
    """A webpage that is rendered from a parameterized notebook."""

    name: str = page_name_field

    title: str = page_title_field

    description: FormattedText | None = page_description_field

    cache_ttl: int | None = page_cache_ttl_field

    date_added: datetime = page_date_added_field

    authors: list[Person] = page_authors_field

    tags: list[str] = page_tags_field

    uploader_username: str | None = Field(
        ...,
        title="Username of person that uploaded the page.",
        description=(
            "This field is only set for user uploads, not for GitHub-backed "
            "pages."
        ),
    )

    self_url: AnyHttpUrl = page_url_field

    source_url: AnyHttpUrl = page_source_field

    rendered_url: AnyHttpUrl = page_rendered_field

    html_url: AnyHttpUrl = page_html_field

    html_status_url: AnyHttpUrl = page_html_status_field

    parameters: dict[str, dict[str, Any]] = page_parameters_field

    github: GitHubSourceMetadata | None = Field(
        ...,
        title="Repository source metadata for GitHub-backed pages",
        description=(
            "This field is only set for GitHub-backed pages, not user/API "
            "uploads."
        ),
    )

    @classmethod
    def from_domain(cls, *, page: PageModel, request: Request) -> Page:
        """Create a page resource from the domain model."""
        parameters = {
            name: parameter.schema
            for name, parameter in page.parameters.items()
        }

        if page.description is not None:
            description = FormattedText.from_gfm(page.description)
        else:
            description = None

        authors = [Person.from_domain(person=p) for p in page.authors]

        if page.github_backed:
            github_metadata = GitHubSourceMetadata.from_domain(page=page)
        else:
            github_metadata = None

        return cls(
            name=page.name,
            title=page.title,
            description=description,
            cache_ttl=page.cache_ttl,
            date_added=page.date_added,
            authors=authors,
            tags=page.tags,
            uploader_username=page.uploader_username,
            parameters=parameters,
            self_url=AnyHttpUrl(
                str(request.url_for("get_page", page=page.name)),
            ),
            source_url=AnyHttpUrl(
                str(request.url_for("get_page_source", page=page.name)),
            ),
            rendered_url=AnyHttpUrl(
                str(request.url_for("get_rendered_notebook", page=page.name)),
            ),
            html_url=AnyHttpUrl(
                str(request.url_for("get_page_html", page=page.name)),
            ),
            html_status_url=AnyHttpUrl(
                str(request.url_for("get_page_html_status", page=page.name)),
            ),
            github=github_metadata,
        )


class PageSummary(BaseModel):
    """Summary information about a Page."""

    name: str = page_name_field

    title: str = page_title_field

    self_url: AnyHttpUrl = page_url_field

    @classmethod
    def from_domain(
        cls, *, summary: PageSummaryModel, request: Request
    ) -> PageSummary:
        """Create a PageSummary response from the domain model."""
        return cls(
            name=summary.name,
            title=summary.title,
            self_url=AnyHttpUrl(
                str(request.url_for("get_page", page=summary.name)),
            ),
        )


class HtmlStatus(BaseModel):
    """Information about the availability of an HTML rendering for a given
    set of parameters.
    """

    available: bool = Field(
        ...,
        title="Html availability",
        description=(
            "If true, HTML is available in the cache for this set of "
            "parameters."
        ),
    )

    html_url: AnyHttpUrl = page_html_field

    html_hash: str | None = Field(
        ...,
        title="HTML content hash",
        description=(
            "A SHA256 hash of the HTML content. Clients can use this "
            "hash to determine if they are showing the current version of the "
            "HTML rendering. This field is null if the HTML is not available."
        ),
    )

    @classmethod
    def from_html(
        cls, *, html: NbHtmlModel | None, request: Request
    ) -> HtmlStatus:
        base_html_url = str(
            request.url_for("get_page_html", page=request.path_params["page"])
        )

        if html is None:
            # resolved parameters aren't available, so use the request URL
            qs = urlencode(request.query_params)
            html_url = f"{base_html_url}?{qs}" if qs else base_html_url

            return cls(
                available=False,
                html_url=AnyHttpUrl(html_url),
                html_hash=None,
            )
        else:
            query_params: dict[str, Any] = {}
            query_params.update(html.values)
            # Add display settings
            if html.hide_code:
                query_params["ts_hide_code"] = "1"
            else:
                query_params["ts_hide_code"] = "0"
            qs = urlencode(query_params)
            html_url = f"{base_html_url}?{qs}" if qs else base_html_url
            return cls(
                available=True,
                html_hash=html.html_hash,
                html_url=AnyHttpUrl(html_url),
            )


class PostPageRequest(BaseModel):
    """A payload for creating a new page."""

    title: str = page_title_field

    ipynb: str = ipynb_field

    authors: list[Person] = page_authors_field

    tags: list[str] = page_tags_field

    # This description is different from the output, page_description_field,
    # because a user only ever submits markdown, whereas the API serves up
    # both markdown and pre-rendered HTML
    description: str | None = Field(
        None,
        title="Page description",
        description="The description can use Markdown formatting.",
    )

    cache_ttl: int | None = page_cache_ttl_field


class GitHubContentsNode(BaseModel):
    """Information about a node in a GitHub contents tree."""

    node_type: GitHubNodeType = Field(
        ...,
        title="Node type",
        description="Type of node in the GitHub contents tree.",
        examples=["page"],
    )

    path: str = Field(
        ...,
        title="Path",
        description="Squareone URL path",
        examples=["lsst-sqre/times-square-demo/demo"],
    )

    title: str = Field(
        ...,
        title="Title",
        description="Presentation title of the node.",
        examples=["Demo"],
    )

    contents: list[GitHubContentsNode] = Field(
        ..., title="Contents", description="Children of this node"
    )

    @classmethod
    def from_domain_model(cls, node: GitHubNode) -> GitHubContentsNode:
        return cls(
            node_type=node.node_type,
            path=node.squareone_path,
            title=node.title,
            contents=[cls.from_domain_model(n) for n in node.contents],
        )


class GitHubContentsRoot(BaseModel):
    """The tree of GitHub contents."""

    contents: list[GitHubContentsNode] = Field(
        title="Contents", description="Content nodes"
    )

    @classmethod
    def from_tree(
        cls,
        *,
        tree: list[GitHubNode],
    ) -> GitHubContentsRoot:
        return cls(
            contents=[GitHubContentsNode.from_domain_model(n) for n in tree],
        )


class GitHubContributor(BaseModel):
    """A GitHub contributor."""

    username: str = Field(..., title="Username", description="GitHub username")

    html_url: HttpUrl = Field(
        ..., title="HTML URL", description="The user's homepage on GitHub."
    )

    avatar_url: HttpUrl = Field(..., title="Avatar image URL")


class GitHubPrState(str, Enum):
    """The state of a GitHub PR."""

    draft = "draft"
    open = "open"
    merged = "merged"
    closed = "closed"


class GitHubPr(BaseModel):
    """Information about a pull request."""

    number: int = Field(
        title="PR number", description="The pull request number."
    )

    title: str = Field(title="Title of the pull request")

    conversation_url: HttpUrl = Field(
        title="URL for the PR's conversation page on GitHub."
    )

    contributor: GitHubContributor

    state: GitHubPrState

    @classmethod
    def from_github_pr(cls, pull_request: GitHubPullRequestModel) -> GitHubPr:
        # Consolidate github state information
        if pull_request.merged:
            state = GitHubPrState.merged
        elif pull_request.draft:
            state = GitHubPrState.draft
        elif pull_request.state == GitHubPullState.closed:
            state = GitHubPrState.closed
        else:
            state = GitHubPrState.open

        return cls(
            number=pull_request.number,
            title=pull_request.title,
            conversation_url=pull_request.html_url,
            state=state,
            contributor=GitHubContributor(
                username=pull_request.user.login,
                html_url=pull_request.user.html_url,
                avatar_url=pull_request.user.avatar_url,
            ),
        )


class GitHubCheckRunSummary(BaseModel):
    """Summary info about a check run."""

    status: GitHubCheckRunStatus

    conclusion: GitHubCheckRunConclusion | None

    external_id: str | None = Field(
        description="Identifier set by the check runner."
    )

    head_sha: str = Field(
        title="Head sha",
        description="The SHA of the most recent commit for this check suite.",
    )

    name: str = Field(description="Name of the check run.")

    html_url: HttpUrl = Field(
        description="URL of the check run webpage on GitHub."
    )

    report_title: str | None = Field(
        None,
        title="Report title",
    )

    report_summary: FormattedText | None = Field(
        None,
        title="Report summary",
    )

    report_text: FormattedText | None = Field(
        None,
        title="Report body text",
    )

    @classmethod
    def from_checkrun(
        cls, check_run: GitHubCheckRunModel
    ) -> GitHubCheckRunSummary:
        """Create a check run summary API model from the GitHub API
        model.
        """
        report_title: str | None = None
        report_summary: FormattedText | None = None
        report_text: FormattedText | None = None

        if check_run.output:
            output = check_run.output
            if output.title:
                report_title = output.title
            if output.summary:
                report_summary = FormattedText.from_gfm(output.summary)
            if output.text:
                report_text = FormattedText.from_gfm(output.text)

        return cls(
            status=check_run.status,
            conclusion=check_run.conclusion,
            external_id=check_run.external_id,
            head_sha=check_run.head_sha,
            name=check_run.name,
            html_url=check_run.html_url,
            report_title=report_title,
            report_summary=report_summary,
            report_text=report_text,
        )


class GitHubPrContents(GitHubContentsRoot):
    """The contents of a GitHub pull request, along with information
    about the check run and pull request.
    """

    owner: str = Field(
        ...,
        title="GitHub owner",
        description=(
            "The GitHub owner for this tree, if this tree applies to a single "
            "GitHub owner."
        ),
    )

    repo: str = Field(
        ...,
        title="GitHub repo",
        description=(
            "The GitHub repo for this tree, if this tree applies to a single "
            "GitHub repo."
        ),
    )

    commit: str = Field(
        ...,
        title="GitHub commit",
        description=(
            "The GitHub commit for this tree, if this tree is specific to a "
            "commit, such as for a PR preview."
        ),
    )

    yaml_check: GitHubCheckRunSummary | None = Field(
        ..., description="Summary of notebook execution check run."
    )

    nbexec_check: GitHubCheckRunSummary | None = Field(
        ..., description="Summary of notebook execution check run."
    )

    pull_requests: list[GitHubPr] = Field(
        ...,
        title="Pull Requests",
    )

    @classmethod
    def create(
        cls,
        *,
        tree: list[GitHubNode],
        owner: str,
        repo: str,
        commit: str,
        check_runs: list[GitHubCheckRunModel],
        pull_requests: list[GitHubPullRequestModel],
    ) -> GitHubPrContents:
        yaml_check: GitHubCheckRunSummary | None = None
        nbexec_check: GitHubCheckRunSummary | None = None
        for check_run in check_runs:
            if check_run.external_id == "times-square/nbexec":
                nbexec_check = GitHubCheckRunSummary.from_checkrun(check_run)
            elif check_run.external_id == "times-square/yaml-check":
                yaml_check = GitHubCheckRunSummary.from_checkrun(check_run)

        return cls(
            contents=[GitHubContentsNode.from_domain_model(n) for n in tree],
            owner=owner,
            repo=repo,
            commit=commit,
            yaml_check=yaml_check,
            nbexec_check=nbexec_check,
            pull_requests=[GitHubPr.from_github_pr(p) for p in pull_requests],
        )
