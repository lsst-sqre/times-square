"""The Page database model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Integer, Unicode, UnicodeText
from sqlalchemy.orm import Mapped, mapped_column

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

    name: Mapped[str] = mapped_column(
        Unicode(32), primary_key=True, default=lambda: uuid.uuid4().hex
    )
    """The primary key, and also the ID for the Page REST API."""

    ipynb: Mapped[str] = mapped_column(UnicodeText, nullable=False)
    """The Jinja-parameterized notebook, as a JSON-formatted string."""

    parameters: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    """Parameters and their jsonschema descriptors."""

    title: Mapped[str] = mapped_column(UnicodeText, nullable=False)
    """Display title of the notebook."""

    date_added: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    """Date when the page is registered through the Times Square API."""

    authors: Mapped[list[dict[str, Any]]] = mapped_column(JSON, nullable=False)
    """Authors of the notebook.

    The schema for this column is described by the NotebookSidecarFile
    authors field schema.
    """

    tags: Mapped[list[str]] = mapped_column(JSON, nullable=False)
    """Tags (keywords) assigned to this page."""

    execution_timeout: Mapped[int | None] = mapped_column(
        Integer, nullable=True
    )
    """The execution timeout configured for this page, in seconds."""

    schedule_rruleset: Mapped[str | None] = mapped_column(
        UnicodeText, nullable=True
    )
    """The schedule rruleset for this page, if it is scheduled to run
    periodically.
    """

    schedule_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    """Whether the page's schedule is enabled."""

    uploader_username: Mapped[str | None] = mapped_column(
        UnicodeText, nullable=True
    )
    """Username of the uploader, if this page is uploaded without GitHub
    backing.
    """

    date_deleted: Mapped[datetime | None] = mapped_column(DateTime)
    """A nullable datetime that is set to the datetime when the page is
    soft-deleted.
    """

    description: Mapped[str | None] = mapped_column(UnicodeText)
    """Description of a page (markdown-formatted)."""

    cache_ttl: Mapped[int | None] = mapped_column(Integer)
    """The cache TTL (seconds) for HTML renders, or None to retain renders
    indefinitely.
    """

    github_owner: Mapped[str | None] = mapped_column(UnicodeText)
    """The GitHub repository owner (username or organization name) for
    GitHub-backed pages.
    """

    github_repo: Mapped[str | None] = mapped_column(UnicodeText)
    """The GitHub repository name for GitHub-backed pages."""

    github_commit: Mapped[str | None] = mapped_column(Unicode(40))
    """The SHA of the commit this page corresponds to; only used for pages
    associated with a GitHub Check Run.
    """

    repository_path_prefix: Mapped[str | None] = mapped_column(UnicodeText)
    """The repository path prefix, relative to the root of the directory."""

    repository_display_path_prefix: Mapped[str | None] = mapped_column(
        UnicodeText
    )
    """The repository path prefix, relative to the configured root of Times
    Square notebooks in a repository.
    """

    repository_path_stem: Mapped[str | None] = mapped_column(UnicodeText)
    """The filename stem (without prefix and without extension) of the
    source file in the GitHub repository for GitHub-backed pages.

    The repository_source_filename_extension and
    repository_sidecar_filename_extension columns provide the extensions for
    the corresponding files.
    """

    repository_source_extension: Mapped[str | None] = mapped_column(
        UnicodeText
    )
    """The filename extension of the source file in the GitHub
    repository for GitHub-backed pages.

    Combine with repository_path_stem to get the file path.
    """

    repository_sidecar_extension: Mapped[str | None] = mapped_column(
        UnicodeText
    )
    """The filename extension of the sidecar YAML file in the GitHub
    repository for GitHub-backed pages.

    Combine with repository_path_stem to get the file path.
    """

    repository_source_sha: Mapped[str | None] = mapped_column(Unicode(40))
    """The git tree sha of the source file for GitHub-backed pages."""

    repository_sidecar_sha: Mapped[str | None] = mapped_column(Unicode(40))
    """The git tree sha of the sidecar YAML file for GitHub-backed pages."""
