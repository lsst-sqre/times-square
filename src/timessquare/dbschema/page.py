"""The Page database model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, Integer, Unicode, UnicodeText

from .base import Base

__all__ = ["SqlPage"]


class SqlPage(Base):
    """The SQLAlchemy model for a Page, which is a parameterized notebook that
    is available as a website.

    Notes
    -----
    Pages can be backed by GitHub or can be added directly through the API.
    GitHub-backed pages use extra columns to describe their GitHub context
    and version.

    .. todo::

       API-added notebooks use additional columns to describe the user that
       uploaded the content.
    """

    __tablename__ = "pages"

    name: str = Column(
        Unicode(32), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    """The primary key, and also the ID for the Page REST API."""

    ipynb: str = Column(UnicodeText, nullable=False)
    """The Jinja-parameterized notebook, as a JSON-formatted string."""

    parameters: dict[str, Any] = Column(JSON, nullable=False)
    """Parameters and their jsonschema descriptors."""

    title: str = Column(UnicodeText, nullable=False)
    """Display title of the notebook."""

    date_added: datetime = Column(DateTime, nullable=False)
    """Date when the page is registered through the Times Square API."""

    authors: list[dict[str, Any]] = Column(JSON, nullable=False)
    """Authors of the notebook.

    The schema for this column is described by the NotebookSidecarFile
    authors field schema.
    """

    tags: list[str] = Column(JSON, nullable=False)
    """Tags (keywords) assigned to this page."""

    uploader_username: str | None = Column(Unicode(64), nullable=True)
    """Username of the uploader, if this page is uploaded without GitHub
    backing.
    """

    date_deleted: datetime | None = Column(DateTime)
    """A nullable datetime that is set to the datetime when the page is
    soft-deleted.
    """

    description: str | None = Column(UnicodeText)
    """Description of a page (markdown-formatted)."""

    cache_ttl: int | None = Column(Integer)
    """The cache TTL (seconds) for HTML renders, or None to retain renders
    indefinitely.
    """

    github_owner: str | None = Column(Unicode(255))
    """The GitHub repository owner (username or organization name) for
    GitHub-backed pages.
    """

    github_repo: str | None = Column(Unicode(255))
    """The GitHub repository name for GitHub-backed pages."""

    github_commit: str | None = Column(Unicode(40))
    """The SHA of the commit this page corresponds to; only used for pages
    associated with a GitHub Check Run.
    """

    repository_path_prefix: str | None = Column(Unicode(2048))
    """The repository path prefix, relative to the root of the directory."""

    repository_display_path_prefix: str | None = Column(Unicode(2048))
    """The repository path prefix, relative to the configured root of Times
    Square notebooks in a repository.
    """

    repository_path_stem: str | None = Column(Unicode(255))
    """The filename stem (without prefix and without extension) of the
    source file in the GitHub repository for GitHub-backed pages.

    The repository_source_filename_extension and
    repository_sidecar_filename_extension columns provide the extensions for
    the corresponding files.
    """

    repository_source_extension: str | None = Column(Unicode(255))
    """The filename extension of the source file in the GitHub
    repository for GitHub-backed pages.

    Combine with repository_path_stem to get the file path.
    """

    repository_sidecar_extension: str | None = Column(Unicode(255))
    """The filename extension of the sidecar YAML file in the GitHub
    repository for GitHub-backed pages.

    Combine with repository_path_stem to get the file path.
    """

    repository_source_sha: str | None = Column(Unicode(40))
    """The git tree sha of the source file for GitHub-backed pages."""

    repository_sidecar_sha: str | None = Column(Unicode(40))
    """The git tree sha of the sidecar YAML file for GitHub-backed pages."""
