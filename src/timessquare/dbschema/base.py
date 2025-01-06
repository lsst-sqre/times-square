"""The base for the table schemas."""

from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase

__all__ = ["Base"]


class Base(DeclarativeBase):
    """The base class for all SQLAlchemy table schemas."""
