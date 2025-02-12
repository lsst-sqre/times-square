"""Tests for the the timessquare.domain.pageparameter module."""

from __future__ import annotations

from typing import Any

import pytest

from timessquare.domain.pageparameters import (
    PageParameters,
    PageParameterSchema,
)
from timessquare.exceptions import (
    ParameterDefaultInvalidError,
    ParameterDefaultMissingError,
    ParameterNameValidationError,
)


def test_parameter_name_validation() -> None:
    PageParameters.validate_parameter_name("myvar")
    PageParameters.validate_parameter_name("my_var")
    PageParameters.validate_parameter_name("myvar1")
    PageParameters.validate_parameter_name("Myvar1")
    PageParameters.validate_parameter_name("M")

    with pytest.raises(ParameterNameValidationError):
        PageParameters.validate_parameter_name(" M")
    with pytest.raises(ParameterNameValidationError):
        PageParameters.validate_parameter_name("1p")
    with pytest.raises(ParameterNameValidationError):
        PageParameters.validate_parameter_name("lambda")


def test_parameter_default_exists() -> None:
    name = "myvar"
    schema: dict[str, Any] = {"type": "number", "description": "Test schema"}

    with pytest.raises(ParameterDefaultMissingError):
        PageParameterSchema.create_and_validate(name=name, json_schema=schema)

    # should work with default added
    schema["default"] = 0.0
    PageParameterSchema.create_and_validate(name=name, json_schema=schema)


def test_parameter_default_invalid() -> None:
    name = "myvar"
    schema: dict[str, Any] = {
        "type": "number",
        "default": -1,
        "minimum": 0,
        "description": "Test schema",
    }

    with pytest.raises(ParameterDefaultInvalidError):
        PageParameterSchema.create_and_validate(name=name, json_schema=schema)

    # Change default to fulfil minimum
    schema["default"] = 1.0
    PageParameterSchema.create_and_validate(name=name, json_schema=schema)


def test_parameter_casting() -> None:
    schema = PageParameterSchema.create(
        {"default": "default", "type": "string"}
    )
    assert schema.cast_value("hello") == "hello"

    schema = PageParameterSchema.create({"default": 1, "type": "integer"})
    assert schema.cast_value("1") == 1
    assert schema.cast_value(1) == 1

    schema = PageParameterSchema.create({"default": 1.5, "type": "number"})
    assert schema.cast_value("2.4") == 2.4
    assert schema.cast_value(2.4) == 2.4

    schema = PageParameterSchema.create({"default": 1.5, "type": "number"})
    assert schema.cast_value("2") == 2
    assert schema.cast_value(2) == 2

    schema = PageParameterSchema.create({"default": True, "type": "boolean"})
    assert True is schema.cast_value("true")
    assert False is schema.cast_value("false")
    assert True is schema.cast_value(True)
    assert False is schema.cast_value(False)
