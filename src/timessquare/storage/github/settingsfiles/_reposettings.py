from __future__ import annotations

from typing import Annotated

import yaml
from pydantic import BaseModel, Field

__all__ = [
    "RepositorySettingsFile",
]


class RepositorySettingsFile(BaseModel):
    """A Pydantic model for a Times Square times-square.yaml repository
    settings file.
    """

    description: Annotated[
        str | None,
        Field(
            title="Description of the repository",
            description="Can be markdown-formatted.",
        ),
    ] = None

    ignore: Annotated[
        list[str],
        Field(
            title="Paths to ignore (supports globs)",
            default_factory=list,
            description="Relative to the repository root.",
        ),
    ]

    root: Annotated[
        str,
        Field(
            title="Root directory where Times Square notebooks are located.",
            description=(
                "An empty string corresponds to the root being the same as "
                "the repository root."
            ),
        ),
    ] = ""

    enabled: Annotated[
        bool,
        Field(
            title=(
                "Toggle for activating a repository's inclusion in Times "
                "Square"
            ),
            description=(
                "Normally a repository is synced into Times Square if the "
                "Times Square GitHub App is installed and the repository "
                "includes a times-square.yaml file. You can set this field "
                "to `False` to temporarily prevent it from being synced by "
                "Times Square."
            ),
        ),
    ] = True

    @classmethod
    def parse_yaml(cls, content: str) -> RepositorySettingsFile:
        """Create a RepositorySettingsFile from the YAML content."""
        return cls.model_validate(yaml.safe_load(content))
