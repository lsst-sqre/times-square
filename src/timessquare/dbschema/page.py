"""The Page database model."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

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

    parameters: Dict[str, Any] = Column(JSON, nullable=False)
    """Parameters and their jsonschema descriptors."""

    title: str = Column(UnicodeText, nullable=False)
    """Display title of the notebook."""

    date_added: datetime = Column(DateTime, nullable=False)
    """Date when the page is registered through the Times Square API."""

    authors: List[Dict[str, Any]] = Column(JSON, nullable=False)
    """Authors of the notebook.

    The schema for this column is described by the NotebookSidecarFile
    authors field schema.
    """

    tags: List[str] = Column(JSON, nullable=False)
    """Tags (keywords) assigned to this page."""

    uploader_username: Optional[str] = Column(Unicode(64), nullable=True)
    """Username of the uploader, if this page is uploaded without GitHub
    backing.
    """

    date_deleted: Optional[datetime] = Column(DateTime)
    """A nullable datetime that is set to the datetime when the page is
    soft-deleted.
    """

    description: Optional[str] = Column(UnicodeText)
    """Description of a page (markdown-formatted)."""

    cache_ttl: Optional[int] = Column(Integer)
    """The cache TTL (seconds) for HTML renders, or None to retain renders
    indefinitely.
    """

    github_owner: Optional[str] = Column(Unicode(255))
    """The GitHub repository owner (username or organization name) for
    GitHub-backed pages.
    """

    github_repo: Optional[str] = Column(Unicode(255))
    """The GitHub repository name for GitHub-backed pages."""

    github_commit: Optional[str] = Column(Unicode(40))
    """The SHA of the commit this page corresponds to; only used for pages
    associated with a GitHub Check Run.
    """

    repository_path_prefix: Optional[str] = Column(Unicode(2048))
    """The repository path prefix, relative to the root of the directory."""

    repository_display_path_prefix: Optional[str] = Column(Unicode(2048))
    """The repository path prefix, relative to the configured root of Times
    Square notebooks in a repository.
    """

    repository_path_stem: Optional[str] = Column(Unicode(255))
    """The filename stem (without prefix and without extension) of the
    source file in the GitHub repository for GitHub-backed pages.

    The repository_source_filename_extension and
    repository_sidecar_filename_extension columns provide the extensions for
    the corresponding files.
    """

    repository_source_extension: Optional[str] = Column(Unicode(255))
    """The filename extension of the source file in the GitHub
    repository for GitHub-backed pages.

    Combine with repository_path_stem to get the file path.
    """

    repository_sidecar_extension: Optional[str] = Column(Unicode(255))
    """The filename extension of the sidecar YAML file in the GitHub
    repository for GitHub-backed pages.

    Combine with repository_path_stem to get the file path.
    """

    repository_source_sha: Optional[str] = Column(Unicode(40))
    """The git tree sha of the source file for GitHub-backed pages."""

    repository_sidecar_sha: Optional[str] = Column(Unicode(40))
    """The git tree sha of the sidecar YAML file for GitHub-backed pages."""
