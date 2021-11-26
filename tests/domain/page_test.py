"""Tests for the Page service."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from timessquare.domain.page import PageModel, PageParameterSchema
from timessquare.exceptions import (
    ParameterDefaultInvalidError,
    ParameterDefaultMissingError,
    ParameterNameValidationError,
)


def test_parameter_name_validation() -> None:
    PageModel.validate_parameter_name("myvar")
    PageModel.validate_parameter_name("my_var")
    PageModel.validate_parameter_name("myvar1")
    PageModel.validate_parameter_name("Myvar1")
    PageModel.validate_parameter_name("M")

    with pytest.raises(ParameterNameValidationError):
        PageModel.validate_parameter_name(" M")
        PageModel.validate_parameter_name("1p")


def test_parameter_default_exists() -> None:
    name = "myvar"
    schema: Dict[str, Any] = {"type": "number", "description": "Test schema"}

    with pytest.raises(ParameterDefaultMissingError):
        PageParameterSchema.create_and_validate(name=name, json_schema=schema)

    # should work with default added
    schema["default"] = 0.0
    PageParameterSchema.create_and_validate(name=name, json_schema=schema)


def test_parameter_default_invalid() -> None:
    name = "myvar"
    schema: Dict[str, Any] = {
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
    assert "hello" == schema.cast_value("hello")

    schema = PageParameterSchema.create({"default": 1, "type": "integer"})
    assert 1 == schema.cast_value("1")
    assert 1 == schema.cast_value(1)

    schema = PageParameterSchema.create({"default": 1.5, "type": "number"})
    assert 2.4 == schema.cast_value("2.4")
    assert 2.4 == schema.cast_value(2.4)

    schema = PageParameterSchema.create({"default": 1.5, "type": "number"})
    assert 2 == schema.cast_value("2")
    assert 2 == schema.cast_value(2)

    schema = PageParameterSchema.create({"default": True, "type": "boolean"})
    assert True is schema.cast_value("true")
    assert False is schema.cast_value("false")
    assert True is schema.cast_value(True)
    assert False is schema.cast_value(False)
