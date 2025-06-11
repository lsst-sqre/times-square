from __future__ import annotations

from enum import Enum
from typing import Annotated, Literal, Self

from pydantic import BaseModel, Field, model_validator

from timessquare.domain.pageparameters import (
    DYNAMIC_DATE_PATTERN,
    PageParameterSchema,
    create_and_validate_parameter_schema,
)

__all__ = [
    "JsonSchemaTypeEnum",
    "ParameterSchemaModel",
]


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

    format: Annotated[
        Literal["date", "date-time", "dayobs", "dayobs-date"] | None,
        Field(
            title="The JSON schema format",
            description=(
                "For example, the format of a date or time. Only used for "
                "the string type. Times Square also supports extensions to "
                "format: 'dayobs' for Rubin DayObs dates and 'dayobs-date' "
                "for Rubin DayObs dates with dashes."
            ),
        ),
    ] = None

    default: Annotated[
        int | float | str | bool | None,
        Field(
            title="Default value",
            description=(
                "The default value is applied when the parameter value is "
                "not set by the viewer. The default must be a valid value "
                "for the parameter's type. Instead of a static value, "
                "you can also use a dynamic default value (see "
                "`dynamic_default` field)."
            ),
        ),
    ] = None

    dynamic_default: Annotated[
        str | None,
        Field(
            title="Dynamic default value",
            description=(
                "A dynamic default value for the parameter. With a date "
                "format parameter, this can be a string like `today`, "
                "'yesterday', 'tomorrow', '+7d', '-1month_start'. "
            ),
            serialization_alias="X-Dynamic-Default",
        ),
    ] = None

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
        json_schema = self.model_dump(
            exclude_none=True, mode="json", by_alias=True
        )
        # Move custom formats to X-TS-Format
        if "format" in json_schema and json_schema["format"] == "dayobs":
            del json_schema["format"]
            json_schema["X-TS-Format"] = "dayobs"
        elif (
            "format" in json_schema and json_schema["format"] == "dayobs-date"
        ):
            del json_schema["format"]
            json_schema["X-TS-Format"] = "dayobs-date"
        return create_and_validate_parameter_schema(
            name=name, json_schema=json_schema
        )

    @model_validator(mode="after")
    def check_dynamic_default(self) -> Self:
        """Ensure dynamic_default is only set for string type with
        date format.
        """
        if self.dynamic_default is not None:
            if self.type != JsonSchemaTypeEnum.string or self.format not in {
                "date",
                "dayobs",
                "dayobs-date",
            }:
                raise ValueError(
                    "dynamic_default can only be set when type is 'string' "
                    "and format is 'date', 'dayobs', or 'dayobs-date'. "
                )
        return self

    @model_validator(mode="after")
    def check_dynamic_default_pattern(self) -> Self:
        """Ensure dynamic_default matches the expected pattern for date
        types.
        """
        if (
            self.dynamic_default is not None
            and self.type == JsonSchemaTypeEnum.string
            and self.format in {"date", "dayobs", "dayobs-date"}
        ):
            if not DYNAMIC_DATE_PATTERN.match(self.dynamic_default):
                raise ValueError(
                    f"Invalid dynamic_default format: {self.dynamic_default}. "
                    "Must match pattern for date dynamic defaults."
                )
        return self

    @model_validator(mode="after")
    def check_default_and_dynamic_default(self) -> Self:
        """Ensure default is only None when dynamic_default is set."""
        if self.default is None and self.dynamic_default is None:
            raise ValueError("Either default or dynamic_default must be set")
        if all((self.default is not None, self.dynamic_default is not None)):
            raise ValueError(
                "Either default or dynamic_default must be set, but not both"
            )
        return self
