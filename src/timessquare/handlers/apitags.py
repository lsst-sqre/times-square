"""Tags for the API documentation."""

from __future__ import annotations

from enum import Enum

__all__ = ["ApiTags"]


class ApiTags(Enum):
    """OpenAPI tags."""

    pages = "Pages"
    github = "GitHub Notebooks"
    pr = "Pull Requests"
    v1 = "v1"
