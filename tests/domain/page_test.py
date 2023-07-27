"""Tests for the Page service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

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


def test_render_parameters() -> None:
    """Test PageModel.render_parameters()."""
    ipynb_path = Path(__file__).parent.parent / "data" / "demo.ipynb"
    ipynb = ipynb_path.read_text()
    nb = PageModel.read_ipynb(ipynb)
    page = PageModel.create_from_api_upload(
        ipynb=ipynb,
        title="Demo",
        uploader_username="testuser",
    )
    rendered = page.render_parameters(values={"A": 2, "y0": 1.0, "lambd": 0.5})
    rendered_nb = PageModel.read_ipynb(rendered)

    # Check that the markdown got rendered
    assert rendered_nb["cells"][0]["source"] == (
        "# Times Square demo\n"
        "\n"
        "Plot parameters:\n"
        "\n"
        "- Amplitude: A = 2\n"
        "- Y offset: y0 = 1.0\n"
        "- Wavelength: lambd = 0.5"
    )

    # Check that the first code cell got replaced
    assert rendered_nb["cells"][1]["source"] == (
        "# Parameters\nA = 2\nlambd = 0.5\ny0 = 1.0"
    )

    # Check that the second code cell was unchanged
    assert rendered_nb["cells"][2]["source"] == nb["cells"][2]["source"]
