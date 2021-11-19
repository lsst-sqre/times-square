"""Domain model for a parameterized notebook page."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass
class PageModel:
    """The domain model for a page, which is a parameterized notebook that
    is available as a web page.
    """

    name: str
    """The name of the page, which is used as a URL path component (slug)."""

    ipynb: str
    """The Jinja-parameterized notebook (a JSON-formatted string)."""

    parameters: Dict[str, Dict[str, Any]]
    """The notebook's parameters and jsonschema descriptions."""
