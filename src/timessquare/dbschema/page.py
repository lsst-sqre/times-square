"""The Page database model."""

from __future__ import annotations

from typing import Any, Dict

from sqlalchemy import JSON, Column, Integer, Unicode, UnicodeText

from .base import Base

__all__ = ["SqlPage"]


class SqlPage(Base):
    """The SQLAlchemy model for a Page, which is a parameterized notebook that
    is available as a website.
    """

    __tablename__ = "pages"

    id: int = Column(Integer, primary_key=True)

    name: str = Column(Unicode(255), index=True, unique=True)
    """The name of the page, which is used as a URL path component (slug)."""

    ipynb: str = Column(UnicodeText)
    """The Jinja-parameterized notebook, as a JSON-formatted string."""

    parameters: Dict[str, Any] = Column(JSON)
    """Parameters and their jsonschema descriptors."""
