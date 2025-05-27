"""Models for Times Square settings files in a GitHub repository."""

from __future__ import annotations

from typing import Annotated

import yaml
from pydantic import BaseModel, Field
from safir.pydantic import HumanTimedelta

from timessquare.domain.page import PersonModel
from timessquare.domain.pageparameters import PageParameters

from ._parameterschema import ParameterSchemaModel
from ._person import SidecarPersonModel

__all__ = [
    "NotebookSidecarFile",
]


class NotebookSidecarFile(BaseModel):
    """A Pydantic model for a ``{notebook}.yaml`` notebook settings sidecar
    file.
    """

    authors: Annotated[
        list[SidecarPersonModel],
        Field(title="Authors of the notebook", default_factory=list),
    ]

    title: Annotated[
        str | None,
        Field(
            title="Title of a notebook (default is to use the filename)",
        ),
    ] = None

    description: Annotated[
        str | None,
        Field(
            title="Description of a notebook",
            description="Can be markdown-formatted.",
        ),
    ] = None

    enabled: Annotated[
        bool,
        Field(
            title=(
                "Toggle for activating a notebook's inclusion in Times Square"
            )
        ),
    ] = True

    cache_ttl: Annotated[
        int | None, Field(title="Lifetime (seconds) of notebook page renders")
    ] = None

    tags: Annotated[
        list[str],
        Field(
            title="Tag keywords associated with the notebook",
            default_factory=list,
        ),
    ]

    timeout: Annotated[
        HumanTimedelta | None,
        Field(
            title="Timeout for notebook execution",
            description="If not set, the default execution timeout is used.",
        ),
    ] = None

    parameters: Annotated[
        dict[str, ParameterSchemaModel],
        Field(title="Parameters and their schemas", default_factory=dict),
    ]

    @classmethod
    def parse_yaml(cls, content: str) -> NotebookSidecarFile:
        """Create a NotebookSidecarFile from the YAML content."""
        return cls.model_validate(yaml.safe_load(content))

    def export_parameters(self) -> PageParameters:
        """Export the `parameters` attribute to `PageParameterSchema` used
        by the PageModel.
        """
        return PageParameters(
            {k: v.to_parameter_schema(k) for k, v in self.parameters.items()}
        )

    def export_authors(self) -> list[PersonModel]:
        return [a.to_person_model() for a in self.authors]
