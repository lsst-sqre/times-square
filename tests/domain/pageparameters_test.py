"""Tests for the the timessquare.domain.pageparameter module."""

from __future__ import annotations

from typing import Any

import pytest

from timessquare.domain.pageparameters import (
    BooleanParameterSchema,
    IntegerParameterSchema,
    NumberParameterSchema,
    PageParameters,
    PageParameterSchema,
    StringParameterSchema,
)
from timessquare.exceptions import (
    PageParameterValueCastingError,
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


def test_string_parameter_schema() -> None:
    schema = PageParameterSchema.create_and_validate(
        "myvar", {"default": "default", "type": "string"}
    )
    assert isinstance(schema, StringParameterSchema)
    assert schema.default == "default"
    assert schema.cast_value("hello") == "hello"
    assert (
        schema.create_python_assignment("myvar", "hello") == 'myvar = "hello"'
    )
    assert schema.create_json_value("hello") == "hello"
    assert schema.create_qs_value("hello") == "hello"


def test_integer_parameter_schema() -> None:
    schema = PageParameterSchema.create_and_validate(
        "myvar", {"default": 1, "type": "integer"}
    )
    assert isinstance(schema, IntegerParameterSchema)
    assert schema.default == 1
    assert schema.cast_value("2") == 2
    assert schema.cast_value(1) == 1
    assert schema.create_python_assignment("myvar", 1) == "myvar = 1"
    assert schema.create_json_value(1) == 1
    assert schema.create_qs_value(1) == "1"
    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("hello")


def test_number_parameter_schema() -> None:
    schema = PageParameterSchema.create_and_validate(
        "myvar", {"default": 1.5, "type": "number"}
    )
    assert isinstance(schema, NumberParameterSchema)
    assert schema.default == 1.5
    assert schema.cast_value("2.4") == 2.4
    assert schema.cast_value(2.4) == 2.4
    assert schema.cast_value("2") == 2
    assert schema.cast_value(2) == 2
    assert schema.create_python_assignment("myvar", 1.5) == "myvar = 1.5"
    assert schema.create_python_assignment("myvar", 1) == "myvar = 1"
    assert schema.create_json_value(1.5) == 1.5
    assert schema.create_json_value(1) == 1
    assert schema.create_qs_value(1.5) == "1.5"
    assert schema.create_qs_value(1) == "1"
    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("hello")


def test_boolean_parameter_schema() -> None:
    schema = PageParameterSchema.create_and_validate(
        "myvar", {"default": True, "type": "boolean"}
    )
    assert isinstance(schema, BooleanParameterSchema)
    assert schema.default is True
    assert schema.cast_value("true") is True
    assert schema.cast_value("false") is False
    assert schema.cast_value(True) is True
    assert schema.cast_value(False) is False
    assert schema.create_python_assignment("myvar", True) == "myvar = True"
    assert schema.create_python_assignment("myvar", False) == "myvar = False"
    assert schema.create_json_value(True) is True
    assert schema.create_json_value(False) is False
    assert schema.create_qs_value(True) == "true"
    assert schema.create_qs_value(False) == "false"

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("hello")

    # Currently don't allow casting of 1 or 0 to boolean
    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value(1)
    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value(0)
