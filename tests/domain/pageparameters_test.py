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
    # Mock datetime.now to return a fixed date: Wednesday, January 1, 2025
    fixed_date = date(2025, 1, 1)

    class MockDatetime:
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            return datetime(2025, 1, 1, 12, 0, 0, tzinfo=tz)

    # Using monkeypatch as a context manager ensures it's reset after the block
    with monkeypatch.context() as m:
        m.setattr(
            "timessquare.domain.pageparameters._datedynamicdefault.datetime",
            MockDatetime,
        )

        # Test basic dynamic defaults
        schema_today = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "today",
            },
        )
        assert isinstance(schema_today, DateParameterSchema)
        assert schema_today.default == fixed_date

        schema_yesterday = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "yesterday",
            },
        )
        assert schema_yesterday.default == date(2024, 12, 31)

        schema_tomorrow = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "tomorrow",
            },
        )
        assert schema_tomorrow.default == date(2025, 1, 2)

        # Test day offset patterns
        schema_plus_5d = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "+5d",
            },
        )
        assert schema_plus_5d.default == date(2025, 1, 6)

        schema_minus_3d = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "-3d",
            },
        )
        assert schema_minus_3d.default == date(2024, 12, 29)

        # Test week patterns (January 1, 2025 is a Wednesday)
        schema_week_start = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "week_start",
            },
        )
        # Monday of the week containing Jan 1, 2025
        assert schema_week_start.default == date(2024, 12, 30)

        schema_week_end = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "week_end",
            },
        )
        # Sunday of the week containing Jan 1, 2025
        assert schema_week_end.default == date(2025, 1, 5)

        schema_plus_1_week_start = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "+1week_start",
            },
        )
        assert schema_plus_1_week_start.default == date(2025, 1, 6)

        schema_minus_2_week_end = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "-2week_end",
            },
        )
        assert schema_minus_2_week_end.default == date(2024, 12, 22)

        # Test month patterns
        schema_month_start = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "month_start",
            },
        )
        assert schema_month_start.default == date(2025, 1, 1)

        schema_month_end = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "month_end",
            },
        )
        assert schema_month_end.default == date(2025, 1, 31)

        schema_plus_2_month_start = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "+2month_start",
            },
        )
        assert schema_plus_2_month_start.default == date(2025, 3, 1)

        schema_minus_1_month_end = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "-1month_end",
            },
        )
        assert schema_minus_1_month_end.default == date(2024, 12, 31)

        # Test year patterns
        schema_year_start = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "year_start",
            },
        )
        assert schema_year_start.default == date(2025, 1, 1)

        schema_year_end = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "year_end",
            },
        )
        assert schema_year_end.default == date(2025, 12, 31)

        schema_plus_1_year_start = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "+1year_start",
            },
        )
        assert schema_plus_1_year_start.default == date(2026, 1, 1)

        schema_minus_1_year_end = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "-1year_end",
            },
        )
        assert schema_minus_1_year_end.default == date(2024, 12, 31)


def test_date_parameter_dynamic_default_validation() -> None:
    """Test validation of X-Dynamic-Default values."""
    # Valid patterns should work
    valid_patterns = [
        "today",
        "yesterday",
        "tomorrow",
        "+5d",
        "-10d",
        "week_start",
        "week_end",
        "+2week_start",
        "-1week_end",
        "month_start",
        "month_end",
        "+3month_start",
        "-2month_end",
        "year_start",
        "year_end",
        "+1year_start",
        "-5year_end",
    ]

    for pattern in valid_patterns:
        schema = create_and_validate_parameter_schema(
            "test_param",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": pattern,
            },
        )
        assert isinstance(schema, DateParameterSchema)

    # Invalid patterns should raise errors
    invalid_patterns = [
        "invalid",
        "d",  # missing sign and offset
        "+d",  # missing offset
        "5d",  # missing sign
        "week",  # incomplete
        "month",  # incomplete
        "year",  # incomplete
        "++5d",  # double sign
        "+week_start",  # missing number
        "0week_start",  # zero offset needs sign
    ]

    for pattern in invalid_patterns:
        with pytest.raises(
            ParameterDefaultInvalidError
        ):  # Could be ValueError or validation error
            create_and_validate_parameter_schema(
                "test_param",
                {
                    "type": "string",
                    "format": "date",
                    "X-Dynamic-Default": pattern,
                },
            )


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
