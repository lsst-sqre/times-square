"""Tests for the the timessquare.domain.pageparameter module."""

from __future__ import annotations

from datetime import UTC, date, datetime, timezone
from typing import Any

import pytest

from timessquare.domain.pageparameters import (
    BooleanParameterSchema,
    DateParameterSchema,
    DatetimeParameterSchema,
    IntegerParameterSchema,
    NumberParameterSchema,
    PageParameters,
    StringParameterSchema,
    create_and_validate_parameter_schema,
)
from timessquare.exceptions import (
    PageParameterValueCastingError,
    ParameterDefaultInvalidError,
    ParameterDefaultMissingError,
    ParameterNameValidationError,
)


def test_resolve_values() -> None:
    parameters = PageParameters(
        {
            "myvar": create_and_validate_parameter_schema(
                "myvar", {"type": "number", "default": 1.0}
            ),
            "myvar2": create_and_validate_parameter_schema(
                "myvar2", {"type": "string", "default": "hello"}
            ),
        }
    )
    assert parameters.resolve_values({"myvar": 2.0, "myvar2": "world"}) == {
        "myvar": 2.0,
        "myvar2": "world",
    }
    # Should be able to cast from all-string values (e.g. from query string)
    assert parameters.resolve_values({"myvar": "2.0", "myvar2": "world"}) == {
        "myvar": 2.0,
        "myvar2": "world",
    }
    # Should use provided values combined with default values
    assert parameters.resolve_values({"myvar": 2.0}) == {
        "myvar": 2.0,
        "myvar2": "hello",
    }
    # Should use default values
    assert parameters.resolve_values({}) == {"myvar": 1.0, "myvar2": "hello"}
    # Should ignore extra parameters
    assert parameters.resolve_values({"myvar": 2.0, "myvar3": "world"}) == {
        "myvar": 2.0,
        "myvar2": "hello",
    }


def test_parameter_schema_access() -> None:
    parameters = PageParameters(
        {
            "myvar": create_and_validate_parameter_schema(
                "myvar", {"type": "number", "default": 1.0}
            ),
            "myvar2": create_and_validate_parameter_schema(
                "myvar2", {"type": "string", "default": "hello"}
            ),
        }
    )
    assert parameters["myvar"].schema["type"] == "number"
    assert parameters["myvar2"].schema["type"] == "string"

    with pytest.raises(KeyError):
        parameters["myvar3"]

    assert len(parameters) == 2
    assert set(list(parameters.keys())) == {"myvar", "myvar2"}


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
        create_and_validate_parameter_schema(name, schema)

    # should work with default added
    schema["default"] = 0.0
    create_and_validate_parameter_schema(name, schema)


def test_parameter_default_invalid() -> None:
    name = "myvar"
    schema: dict[str, Any] = {
        "type": "number",
        "default": -1,
        "minimum": 0,
        "description": "Test schema",
    }

    with pytest.raises(ParameterDefaultInvalidError):
        create_and_validate_parameter_schema(name, schema)

    # Change default to fulfil minimum
    schema["default"] = 1.0
    create_and_validate_parameter_schema(name, schema)


def test_string_parameter_schema() -> None:
    schema = create_and_validate_parameter_schema(
        "myvar", {"default": "default", "type": "string"}
    )
    assert isinstance(schema, StringParameterSchema)
    assert schema.default == "default"
    assert schema.cast_value("hello") == "hello"
    assert (
        schema.create_python_assignment("myvar", "hello") == "myvar = 'hello'"
    )
    assert schema.create_json_value("hello") == "hello"
    assert schema.create_qs_value("hello") == "hello"


def test_integer_parameter_schema() -> None:
    schema = create_and_validate_parameter_schema(
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
    schema = create_and_validate_parameter_schema(
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
    schema = create_and_validate_parameter_schema(
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


def test_date_parameter_schema() -> None:
    schema = create_and_validate_parameter_schema(
        "myvar", {"default": "2025-02-01", "type": "string", "format": "date"}
    )
    assert isinstance(schema, DateParameterSchema)
    assert schema.default == date.fromisoformat("2025-02-01")
    assert schema.cast_value("2025-02-21") == date(year=2025, month=2, day=21)
    assert schema.create_python_assignment("myvar", date(2025, 2, 21)) == (
        'myvar = datetime.date.fromisoformat("2025-02-21")'
    )
    assert schema.create_python_imports() == ["import datetime"]
    assert schema.create_json_value(date(2025, 2, 21)) == "2025-02-21"
    assert schema.create_json_value("2025-02-21") == "2025-02-21"
    assert schema.create_qs_value(date(2025, 2, 21)) == "2025-02-21"
    assert schema.create_qs_value("2025-02-21") == "2025-02-21"

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("hello")


def test_date_parameter_dynamic_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mock datetime.now to return a fixed date
    fixed_date = date(2025, 1, 1)

    class MockDatetime:
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            return datetime(2025, 1, 1, 12, 0, 0, tzinfo=tz)

    # Using monkeypatch as a context manager ensures it's reset after the block
    with monkeypatch.context() as m:
        m.setattr(
            "timessquare.domain.pageparameters._dateparameter.datetime",
            MockDatetime,
        )

        schema = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "today",
            },
        )
        assert isinstance(schema, DateParameterSchema)
        assert schema.default == fixed_date


def test_datetime_parameter_schema() -> None:
    schema = create_and_validate_parameter_schema(
        "myvar",
        {
            "default": "2025-02-01T12:00:00+00:00",
            "type": "string",
            "format": "date-time",
        },
    )
    assert isinstance(schema, DatetimeParameterSchema)
    assert schema.default == datetime(2025, 2, 1, 12, 0, 0, tzinfo=UTC)
    assert schema.cast_value("2025-02-21T12:00:00+00:00") == datetime(
        2025, 2, 21, 12, 0, 0, tzinfo=UTC
    )
    assert schema.cast_value("2025-02-21T12:00:00") == datetime(
        2025, 2, 21, 12, 0, 0, tzinfo=UTC
    )
    assert schema.cast_value(
        datetime(2025, 2, 21, 12, 0, 0, tzinfo=None)  # noqa: DTZ001
    ) == datetime(2025, 2, 21, 12, tzinfo=UTC)
    assert schema.create_python_assignment(
        "myvar", datetime(2025, 2, 21, 12, 0, 0, tzinfo=UTC)
    ) == (
        'myvar = datetime.datetime.fromisoformat("2025-02-21T12:00:00+00:00")'
    )
    assert schema.create_python_imports() == ["import datetime"]
    assert schema.create_json_value(
        datetime(2025, 2, 21, 12, 0, 0, tzinfo=UTC)
    ) == ("2025-02-21T12:00:00+00:00")
    assert schema.create_qs_value(
        datetime(2025, 2, 21, 12, 0, 0, tzinfo=UTC)
    ) == ("2025-02-21T12:00:00+00:00")
