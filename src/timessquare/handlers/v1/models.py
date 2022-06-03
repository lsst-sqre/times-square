"""Request and response models for the v1 API."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlencode

from fastapi import Request
from markdown_it import MarkdownIt
from pydantic import AnyHttpUrl, BaseModel, EmailStr, Field
from safir.metadata import Metadata as SafirMetadata

from timessquare.domain.githubtree import GitHubNode
from timessquare.domain.nbhtml import NbHtmlModel
from timessquare.domain.page import PageModel, PageSummaryModel, PersonModel


class Index(BaseModel):
    """Metadata returned by the external root URL of the application."""

    metadata: SafirMetadata = Field(..., title="Package metadata")

    api_docs: AnyHttpUrl = Field(..., tile="Browsable API documentation")


page_name_field = Field(
    ...,
    example="summit-weather",
    title="Page name",
    description="The name is used as the page's API URL slug.",
)

page_title_field = Field(
    ...,
    example="Summit Weather",
    title="Page title",
    description="The display title (plain text).",
)

page_description_field = Field(
    ...,
    title="Page description",
    descrition=(
        "The description is available as both HTML and GitHub-flavored "
        "Markdown."
    ),
)

page_cache_ttl_field = Field(
    None,
    example=864000,
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
    example="https://example.com/v1/pages/summit-weather",
    title="Page resource URL.",
    description="API URL for the page's metadata resource.",
)

page_source_field = Field(
    ...,
    example="https://example.com/v1/pages/summit-weather/source",
    title="Source ipynb URL",
    description="The URL for the source ipynb file (JSON-formatted)",
)

page_parameters_field = Field(
    ...,
    example={"units": {"enum": ["metric", "imperial"], "default": "metric"}},
    title="Parameters",
    description="Parameters and their JSON Schema descriptions.",
)

page_rendered_field = Field(
    ...,
    example="https://example.com/v1/pages/summit-weather/rendered",
    title="Rendered notebook template URL",
    description=(
        "The URL for the source notebook rendered with parameter values "
        "(JSON-formatted)."
    ),
)

page_html_field = Field(
    ...,
    example="https://example.com/v1/pages/summit-weather/html",
    title="HTML view of computed notebook",
    description=(
        "The URL for the HTML-rendering of the notebook, computed with "
        "parameter values."
    ),
)

page_html_status_field = Field(
    ...,
    example="https://example.com/v1/pages/summit-weather/htmlstatus",
    title="URL for the status of the HTML view of a notebook",
    description=(
        "The status URL for the HTML-rendering of the notebook, computed with "
        "parameter values."
    ),
)

ipynb_field = Field(
    ...,
    example="{...}",
    title="ipynb",
    description="The JSON-encoded notebook content.",
)


class FormattedText(BaseModel):
    """Text that is formatted in both markdown and HTML."""

    gfm: str = Field(title="The GitHub-flavored Markdown-formatted text.")

    html: str = Field(title="The HTML-formatted text.")

    @classmethod
    def from_gfm(cls, gfm_text: str, inline: bool = False) -> FormattedText:
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

    name: str = Field(..., example="Vera Rubin", title="Display name")

    username: Optional[str] = Field(None, example="vera", title="RSP username")
    """A person's RSP username."""

    affiliation_name: Optional[str] = Field(None, example="Rubin/AURA")
    """Display name of a person's main affiliation."""

    email: Optional[EmailStr] = Field(None, title="Email")
    """A person's email."""

    slack_name: Optional[str] = Field(None, title="LSSTC Slack username")
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
        assert page.github_owner is not None
        assert page.github_repo is not None
        sidecar_path = page.repository_sidecar_path
        source_path = page.repository_source_path
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

    description: Optional[FormattedText] = page_description_field

    cache_ttl: Optional[int] = page_cache_ttl_field

    date_added: datetime = page_date_added_field

    authors: List[Person] = page_authors_field

    tags: List[str] = page_tags_field

    uploader_username: Optional[str] = Field(
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

    parameters: Dict[str, Dict[str, Any]] = page_parameters_field

    github: Optional[GitHubSourceMetadata] = Field(
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
            self_url=request.url_for("get_page", page=page.name),
            source_url=request.url_for("get_page_source", page=page.name),
            rendered_url=request.url_for(
                "get_rendered_notebook", page=page.name
            ),
            html_url=request.url_for("get_page_html", page=page.name),
            html_status_url=request.url_for(
                "get_page_html_status", page=page.name
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
            self_url=request.url_for("get_page", page=summary.name),
        )


class HtmlStatus(BaseModel):
    """Information about the availability of an HTML rendering for a given
    set of parameters.
    """

    available: bool = Field(
        ...,
        title="Html availability",
        description="If true, HTML is available in the cache for this set of "
        "parameters.",
    )

    html_url: AnyHttpUrl = page_html_field

    html_hash: Optional[str] = Field(
        ...,
        title="HTML content hash",
        description="A SHA256 hash of the HTML content. Clients can use this "
        "hash to determine if they are showing the current version of the "
        "HTML rendering. This field is null if the HTML is not available.",
    )

    @classmethod
    def from_html(
        cls, *, html: Optional[NbHtmlModel], request: Request
    ) -> HtmlStatus:
        base_html_url = request.url_for(
            "get_page_html", page=request.path_params["page"]
        )

        if html is None:
            # resolved parameters aren't available, so use the request URL
            qs = urlencode(request.query_params)
            if qs:
                html_url = f"{base_html_url}?{qs}"
            else:
                html_url = base_html_url

            return cls(available=False, html_url=html_url, html_hash=None)
        else:
            query_params: Dict[str, Any] = {}
            query_params.update(html.values)
            # Add display settings
            if html.hide_code:
                query_params["ts_hide_code"] = "1"
            else:
                query_params["ts_hide_code"] = "0"
            qs = urlencode(query_params)
            if qs:
                html_url = f"{base_html_url}?{qs}"
            else:
                html_url = base_html_url
            return cls(
                available=True, html_hash=html.html_hash, html_url=html_url
            )


class PostPageRequest(BaseModel):
    """A payload for creating a new page."""

    title: str = page_title_field

    ipynb: str = ipynb_field

    authors: List[Person] = page_authors_field

    tags: List[str] = page_tags_field

    # This description is different from the output, page_description_field,
    # because a user only ever submits markdown, whereas the API serves up
    # both markdown and pre-rendered HTML
    description: Optional[str] = Field(
        None,
        title="Page description",
        description="The description can use Markdown formatting.",
    )

    cache_ttl: Optional[int] = page_cache_ttl_field


class GitHubTreeRoot(BaseModel):
    """The GitHub-backed pages, organized hierarchically."""

    contents: List[GitHubNode]

    @classmethod
    def from_tree(cls, *, tree: List[GitHubNode]) -> GitHubTreeRoot:
        return cls(contents=tree)
