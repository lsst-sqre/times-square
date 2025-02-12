"""Domain of page parameters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

import jsonschema.exceptions
from jsonschema import Draft202012Validator

from timessquare.exceptions import (
    PageParameterValueCastingError,
    ParameterDefaultInvalidError,
    ParameterDefaultMissingError,
    ParameterSchemaError,
)


@dataclass
class PageParameterSchema:
    """The domain model for a page parameter's JSON schema, which is a template
    variable in a page's notebook (`PageModel`).
    """

    validator: Draft202012Validator
    """Parameter value validator (based on `json_schema`)."""

    @classmethod
    def create(cls, json_schema: dict[str, Any]) -> PageParameterSchema:
        """Create a PageParameterSchema given a JSON Schema.

        Note that this method does not validate the schema. If the schema is
        being instantiated from an external source, run the
        `create_and_validate` constructor instead.
        """
        return cls(validator=Draft202012Validator(json_schema))

    @classmethod
    def create_and_validate(
        cls, name: str, json_schema: dict[str, Any]
    ) -> PageParameterSchema:
        try:
            Draft202012Validator.check_schema(json_schema)
        except jsonschema.exceptions.SchemaError as e:
            message = f"The schema for the {name} parameter is invalid.\n\n{e}"
            raise ParameterSchemaError.for_param(name, message) from e

        if "default" not in json_schema:
            raise ParameterDefaultMissingError.for_param(name)

        instance = cls.create(json_schema)
        if not instance.validate(json_schema["default"]):
            raise ParameterDefaultInvalidError.for_param(
                name, json_schema["default"]
            )

        return instance

    @property
    def schema(self) -> dict[str, Any]:
        """Get the JSON schema."""
        return self.validator.schema

    @property
    def default(self) -> Any:
        """Get the schema's default value."""
        return self.schema["default"]

    def __str__(self) -> str:
        return json.dumps(self.schema, sort_keys=True, indent=2)

    def validate(self, v: Any) -> bool:
        """Validate a parameter value."""
        return self.validator.is_valid(v)

    def cast_value(self, v: Any) -> Any:  # noqa: C901 PLR0912
        """Cast a value to the type indicated by the schema.

        Often the input value is a string value usually obtained from the URL
        query parameters into the correct type based on the JSON Schema's type.
        You can also safely pass the correct type idempotently.

        Only string, integer, number, and boolean schema types are supported.
        """
        schema_type = self.schema.get("type")
        if schema_type is None:
            return v

        try:
            if schema_type == "string":
                return v
            elif schema_type == "integer":
                return int(v)
            elif schema_type == "number":
                if isinstance(v, str):
                    if "." in v:
                        return float(v)
                    else:
                        return int(v)
                else:
                    return v
            elif schema_type == "boolean":
                if isinstance(v, str):
                    if v.lower() == "true":
                        return True
                    elif v.lower() == "false":
                        return False
                    else:
                        raise PageParameterValueCastingError.for_value(
                            v, schema_type
                        )
                else:
                    return v
            else:
                raise PageParameterValueCastingError.for_value(v, schema_type)
        except ValueError as e:
            raise PageParameterValueCastingError.for_value(
                v, schema_type
            ) from e
