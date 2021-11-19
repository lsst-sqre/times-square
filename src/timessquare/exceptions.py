"""Exception classes."""

from __future__ import annotations

from typing import Any, ClassVar, Dict, List, Union

from fastapi import status


class TimesSquareError(Exception):
    """Root error for Times Square services."""

    error: ClassVar[str] = "times_square_error"
    """Used as the ``type`` field of the error message.

    Should be overridden by any subclass.
    """

    status_code: ClassVar[int] = status.HTTP_500_INTERNAL_SERVER_ERROR
    """HTTP status code for this type of validation error."""

    def to_dict(self) -> Dict[str, Union[List[str], str]]:
        """Convert the exception to a dictionary suitable for the exception.

        The return value is intended to be passed as the ``detail`` parameter
        to a `fastapi.HTTPException`.
        """
        return {
            "msg": str(self),
            "type": self.error,
        }


class ParameterSchemaValidationError(TimesSquareError):
    """Error related to a parameter.

    There is a global handler for this exception and all exceptions derived
    from it that returns an HTTP 422 status code with a body that's consistent
    with the error messages generated internally by FastAPI.  It should be
    used for input and parameter validation errors that cannot be caught by
    FastAPI for whatever reason.

    Parameters
    ----------
    message : `str`
        The error message (used as the ``msg`` key).
    parameter_name : `str`
        The name of the invalid parameter.
    """

    error = "parameter_validation_failed"

    status_code = status.HTTP_422_UNPROCESSABLE_ENTITY

    def __init__(self, message: str, parameter_name: str) -> None:
        super().__init__(message)
        self.parameter_name = parameter_name

    def to_dict(self) -> Dict[str, Union[List[str], str]]:
        """Convert the exception to a dictionary suitable for the exception.

        The return value is intended to be passed as the ``detail`` parameter
        to a `fastapi.HTTPException`.
        """
        details = super().to_dict()
        details["name"] = self.parameter_name
        return details


class ParameterNameValidationError(ParameterSchemaValidationError):
    """Error for an invalid parameter name."""

    error = "invalid_parameter_name"

    def __init__(self, name: str) -> None:
        message = f"Parameter name {name} is not valid."
        super().__init__(message, name)


class ParameterSchemaError(ParameterSchemaValidationError):
    """The parameter's schema is not a valid JSON schema."""

    error = "invalid_parameter_schema"

    def __init__(self, name: str, message: str) -> None:
        super().__init__(message, name)


class ParameterDefaultMissingError(ParameterSchemaValidationError):
    """The default value of a parameter is missing."""

    error = "parameter_default_missing"

    def __init__(self, name: str) -> None:
        message = f"Parameter {name} is missing a default."
        super().__init__(message, name)


class ParameterDefaultInvalidError(ParameterSchemaValidationError):
    """The default value of a parameter is not valid with respect to the
    parameter's schema.
    """

    error = "parameter_default_invalid"

    def __init__(self, name: str, default: Any) -> None:
        message = f"Parameter {name}'s default is invalid: {default!s}."
        super().__init__(message, name)
