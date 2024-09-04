"""Exception classes."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Self

from fastapi import status
from safir.fastapi import ClientRequestError
from safir.models import ErrorLocation

if TYPE_CHECKING:
    from .domain.page import PageParameterSchema


class TimesSquareClientError(ClientRequestError):
    """Error related to a request from an API client."""


class PageNotFoundError(TimesSquareClientError):
    """Error related to a page not being found."""

    error = "page_not_found"
    status_code = status.HTTP_404_NOT_FOUND

    @classmethod
    def for_page_id(
        cls,
        page_id: str,
        location: ErrorLocation | None = None,
        field_path: list[str] | None = None,
    ) -> Self:
        """Create an exception with a message based on requested page ID."""
        message = f"Page {page_id} not found."
        return cls(message, location=location, field_path=field_path)


class PageNotebookFormatError(TimesSquareClientError):
    """Error related to parsing an ipynb file."""

    error = "ipynb_invalid"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY


class PageParameterError(TimesSquareClientError):
    """Error related to a page parameter's value."""

    error = "parameter_value_invalid"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY

    @classmethod
    def for_param(
        cls,
        name: str,
        value: Any,
        schema: PageParameterSchema,
        location: ErrorLocation | None = None,
        field_path: list[str] | None = None,
    ) -> Self:
        """Create an exception with a message based on the parameter name,
        value, and schema.
        """
        message = (
            f"Value {value!r} for the {name} parameter is invalid. The "
            f"schema is:\n\n{schema!s}"
        )
        return cls(message, location=location, field_path=field_path)


class PageParameterValueCastingError(TimesSquareClientError):
    """Error related to casting a parameter's value.

    Usually this error is converted into a `PageParameterError` since the
    name isn't known at the time the exception is raised.
    """

    error = "parameter_value_casting_error"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY

    @classmethod
    def for_value(
        cls,
        value: Any,
        schema_type: Any,
        location: ErrorLocation | None = None,
        field_path: list[str] | None = None,
    ) -> Self:
        """Create an exception with a message based on the value and schema
        type.
        """
        message = f"Value {value!r} cannot be cast to type {schema_type}"
        return cls(message, location=location, field_path=field_path)


class PageJinjaError(Exception):
    """An error occurred while rendering a template in a notebook cell.

    This error is raised duirng the notebook check run.
    """

    def __init__(self, message: str, cell_index: int) -> None:
        """Create an exception with a message and cell index."""
        super().__init__(message)
        self.cell_index = cell_index

    def __str__(self) -> str:
        return (
            "Error rendering template in "
            f"cell {self.cell_index + 1}: {self.args[0]}"
        )


class ParameterSchemaValidationError(TimesSquareClientError):
    """Error related to a parameter."""

    error = "parameter_validation_failed"
    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY

    parameter: str
    """The name of the parameter that caused the error."""

    def __init__(
        self,
        parameter: str,
        message: str,
        location: ErrorLocation | None = None,
        field_path: list[str] | None = None,
    ) -> None:
        """Create an exception with a message based on the parameter name."""
        super().__init__(message, location=location, field_path=field_path)
        self.parameter = parameter


class ParameterNameValidationError(ParameterSchemaValidationError):
    """Error for an invalid parameter name."""

    error = "invalid_parameter_name"

    @classmethod
    def for_param(
        cls,
        name: str,
        location: ErrorLocation | None = None,
        field_path: list[str] | None = None,
    ) -> Self:
        message = f"Parameter name {name} is not valid."
        return cls(name, message, location=location, field_path=field_path)


class ParameterSchemaError(ParameterSchemaValidationError):
    """The parameter's schema is not a valid JSON schema."""

    error = "invalid_parameter_schema"

    @classmethod
    def for_param(
        cls,
        name: str,
        message: str,
        location: ErrorLocation | None = None,
        field_path: list[str] | None = None,
    ) -> Self:
        return cls(name, message, location=location, field_path=field_path)


class ParameterDefaultMissingError(ParameterSchemaValidationError):
    """The default value of a parameter is missing."""

    error = "parameter_default_missing"

    @classmethod
    def for_param(
        cls,
        name: str,
        location: ErrorLocation | None = None,
        field_path: list[str] | None = None,
    ) -> Self:
        message = f"Parameter {name} is missing a default."
        return cls(name, message, location=location, field_path=field_path)


class ParameterDefaultInvalidError(ParameterSchemaValidationError):
    """The default value of a parameter is not valid with respect to the
    parameter's schema.
    """

    error = "parameter_default_invalid"

    @classmethod
    def for_param(
        cls,
        name: str,
        default: Any,
        location: ErrorLocation | None = None,
        field_path: list[str] | None = None,
    ) -> Self:
        message = f"Parameter {name}'s default is invalid: {default!s}."
        return cls(name, message, location=location, field_path=field_path)
