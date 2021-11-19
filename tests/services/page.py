"""Tests for the Page service."""

from __future__ import annotations

from typing import Any, Dict

import pytest

from timessquare.exceptions import (
    ParameterDefaultInvalidError,
    ParameterDefaultMissingError,
    ParameterNameValidationError,
)
from timessquare.services.page import PageService


def test_parameter_name_validation() -> None:
    PageService.validate_parameter_name("myvar")
    PageService.validate_parameter_name("my_var")
    PageService.validate_parameter_name("myvar1")
    PageService.validate_parameter_name("Myvar1")
    PageService.validate_parameter_name("M")

    with pytest.raises(ParameterNameValidationError):
        PageService.validate_parameter_name(" M")
        PageService.validate_parameter_name("1p")


def test_parameter_default_exists() -> None:
    name = "myvar"
    schema: Dict[str, Any] = {"type": "number", "description": "Test schema"}

    with pytest.raises(ParameterDefaultMissingError):
        PageService.validate_parameter_schema(name, schema)

    # should work with default added
    schema["default"] = 0.0
    PageService.validate_parameter_schema(name, schema)


def test_parameter_default_invalid() -> None:
    name = "myvar"
    schema: Dict[str, Any] = {
        "type": "number",
        "default": -1,
        "minimum": 0,
        "description": "Test schema",
    }

    with pytest.raises(ParameterDefaultInvalidError):
        PageService.validate_parameter_schema(name, schema)

    # Change default to fulfil minimum
    schema["default"] = 1.0
    PageService.validate_parameter_schema(name, schema)
