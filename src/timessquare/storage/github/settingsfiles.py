"""Models for Times Square settings files in a GitHub repository."""

from __future__ import annotations

from enum import Enum
from typing import Annotated, Self

import yaml
from pydantic import BaseModel, EmailStr, Field, model_validator

from timessquare.domain.page import PersonModel
from timessquare.domain.pageparameters import (
    PageParameters,
    PageParameterSchema,
)

__all__ = [
    "JsonSchemaTypeEnum",
    "NotebookSidecarFile",
    "ParameterSchemaModel",
    "RepositorySettingsFile",
    "SidecarPersonModel",
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


class SidecarPersonModel(BaseModel):
    """A Pydantic model for a person's identity encoded in YAML."""

    name: Annotated[str | None, Field(title="Display name")] = None

    username: Annotated[str | None, Field(title="RSP username")] = None

    affiliation_name: Annotated[
        str | None,
        Field(
            title="Affiliation name",
            description="Display name of a person's main affiliation",
        ),
    ] = None

    email: Annotated[EmailStr | None, Field(title="Email")] = None

    slack_name: Annotated[str | None, Field(title="Slack username")] = None

    @model_validator(mode="after")
    def check_names(self) -> Self:
        """Either of name or username must be set."""
        if not (self.name or self.username):
            raise ValueError(
                "Either name or username must be set for a person"
            )
        return self

    def to_person_model(self) -> PersonModel:
        """Convert to the domain version of this object."""
        if self.name is not None:
            display_name = self.name
        elif self.username is not None:
            display_name = self.username
        else:
            # Shouldn't be possible thanks to the model validator
            raise RuntimeError("Cannot resolve a display name for person")

        return PersonModel(
            name=display_name,
            username=self.username,
            affiliation_name=self.affiliation_name,
            email=self.email,
            slack_name=self.slack_name,
        )


class JsonSchemaTypeEnum(str, Enum):
    """JSON schema types that are supported."""

    string = "string"
    number = "number"
    integer = "integer"
    boolean = "boolean"


class ParameterSchemaModel(BaseModel):
    """A Pydantic model for a notebook's parameter schema value.

    This model represents how a parameter is formatted in JSON. The
    corresponding domain model that's actually used by the PageModel is
    `PageParameterSchema`.
    """

    type: Annotated[
        JsonSchemaTypeEnum,
        Field(
            title="The JSON schema type.",
            description=(
                "Note that Times Square parameters can only be a subset of "
                "types describable by JSON schema."
            ),
        ),
    ]

    default: Annotated[
        int | float | str | bool,
        Field(title="Default value, when the user does not override a value"),
    ]

    description: Annotated[str, Field(title="Short description of a field")]

    minimum: Annotated[
        int | float | None,
        Field(title="Minimum value for number or integer types."),
    ] = None

    maximum: Annotated[
        int | float | None,
        Field(title="Maximum value for number or integer types."),
    ] = None

    exclusiveMinimum: Annotated[  # noqa: N815
        int | float | None,
        Field(title="Exclusive minimum value for number or integer types."),
    ] = None

    exclusiveMaximum: Annotated[  # noqa: N815
        int | float | None,
        Field(title="Exclusive maximum value for number or integer types."),
    ] = None

    multipleOf: Annotated[  # noqa: N815
        int | float | None,
        Field(title="Required factor for number of integer types."),
    ] = None

    def to_parameter_schema(self, name: str) -> PageParameterSchema:
        """Convert to the domain version of this object."""
        return PageParameterSchema.create_and_validate(
            name=name, json_schema=self.model_dump(exclude_none=True)
        )


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
