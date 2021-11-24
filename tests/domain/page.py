"""Tests for the Page service."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from timessquare.domain.page import PageModel
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
        PageModel.validate_parameter_schema(name, schema)

    # should work with default added
    schema["default"] = 0.0
    PageModel.validate_parameter_schema(name, schema)


def test_parameter_default_invalid() -> None:
    name = "myvar"
    schema: Dict[str, Any] = {
        "type": "number",
        "default": -1,
        "minimum": 0,
        "description": "Test schema",
    }

    with pytest.raises(ParameterDefaultInvalidError):
        PageModel.validate_parameter_schema(name, schema)

    # Change default to fulfil minimum
    schema["default"] = 1.0
    PageModel.validate_parameter_schema(name, schema)
