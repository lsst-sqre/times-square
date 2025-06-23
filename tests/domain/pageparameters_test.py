"""Tests for the the timessquare.domain.pageparameter module."""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any

import pytest

from timessquare.domain.pageparameters import (
    BooleanParameterSchema,
    DateParameterSchema,
    DatetimeParameterSchema,
    DayObsDateParameterSchema,
    DayObsParameterSchema,
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

        # Test short-form week patterns
        schema_plus_2w = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "+2w",
            },
        )
        assert schema_plus_2w.default == date(2025, 1, 15)  # 2 weeks = 14 days

        schema_minus_3w = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "-3w",
            },
        )
        assert schema_minus_3w.default == date(
            2024, 12, 11
        )  # 3 weeks = 21 days ago

        # Test short-form month patterns
        schema_plus_2m = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "+2m",
            },
        )
        assert schema_plus_2m.default == date(2025, 3, 1)  # 2 months later

        schema_minus_1m = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "-1m",
            },
        )
        assert schema_minus_1m.default == date(2024, 12, 1)  # 1 month ago

        # Test short-form year patterns
        schema_plus_1y = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "+1y",
            },
        )
        assert schema_plus_1y.default == date(2026, 1, 1)  # 1 year later

        schema_minus_2y = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "format": "date",
                "X-Dynamic-Default": "-2y",
            },
        )
        assert schema_minus_2y.default == date(2023, 1, 1)  # 2 years ago


def test_date_parameter_dynamic_default_validation() -> None:
    """Test validation of X-Dynamic-Default values."""
    # Valid patterns should work
    valid_patterns = [
        "today",
        "yesterday",
        "tomorrow",
        "+5d",
        "-10d",
        "+2w",
        "-3w",
        "+1m",
        "-6m",
        "+1y",
        "-2y",
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
        "w",  # missing sign and offset
        "+w",  # missing offset
        "5w",  # missing sign
        "m",  # missing sign and offset
        "+m",  # missing offset
        "3m",  # missing sign
        "y",  # missing sign and offset
        "+y",  # missing offset
        "2y",  # missing sign
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


def test_dayobs_parameter_schema() -> None:
    """Test basic DayObsParameterSchema functionality."""
    schema = create_and_validate_parameter_schema(
        "myvar",
        {
            "type": "string",
            "X-TS-Format": "dayobs",
            "default": "20250101",
        },
    )
    assert isinstance(schema, DayObsParameterSchema)
    assert schema.default == "20250101"

    # Test casting various input types
    assert schema.cast_value("20250215") == 20250215
    assert schema.cast_value(20250215) == 20250215
    assert schema.cast_value(date(2025, 2, 15)) == 20250215

    # Test datetime casting with timezone conversion
    utc_dt = datetime(2025, 2, 15, 14, 0, 0, tzinfo=UTC)
    # UTC 14:00 -> UTC-12 02:00 (same day)
    assert schema.cast_value(utc_dt) == 20250215

    # Test datetime that crosses date boundary due to timezone conversion
    # UTC 02:00 -> UTC-12 14:00 previous day
    utc_dt_early = datetime(2025, 2, 15, 2, 0, 0, tzinfo=UTC)
    assert schema.cast_value(utc_dt_early) == 20250214

    # Test another boundary case - late UTC time that stays same day in UTC-12
    utc_dt_afternoon = datetime(2025, 2, 15, 18, 0, 0, tzinfo=UTC)
    # UTC 18:00 -> UTC-12 06:00 (same day)
    assert schema.cast_value(utc_dt_afternoon) == 20250215

    # Test naive datetime (treated as UTC-12)
    naive_dt = datetime(2025, 2, 15, 12, 0, 0, tzinfo=None)  # noqa: DTZ001
    assert schema.cast_value(naive_dt) == 20250215

    # Test serialization methods
    assert (
        schema.create_python_assignment("myvar", "20250215")
        == "myvar = 20250215"
    )
    assert schema.create_json_value("20250215") == "20250215"
    assert schema.create_qs_value("20250215") == "20250215"

    # Test error cases
    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("hello")

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("2025021")  # Too short

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("202502155")  # Too long

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("2025ab15")  # Invalid characters

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value([])  # Invalid type


def test_dayobs_parameter_dynamic_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test DayObsParameterSchema with X-Dynamic-Default."""
    # Mock datetime.now to return a fixed datetime in UTC-12 timezone
    # January 1, 2025 at 14:00 UTC-12
    utc_minus_12 = timezone(-timedelta(hours=12))
    fixed_datetime = datetime(2025, 1, 1, 14, 0, 0, tzinfo=utc_minus_12)

    class MockDatetime:
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            if tz is not None:
                return fixed_datetime.astimezone(tz)
            return fixed_datetime

    with monkeypatch.context() as m:
        m.setattr(
            "timessquare.domain.pageparameters._dayobsparameter.datetime",
            MockDatetime,
        )

        # Test basic dynamic defaults
        schema_today = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "X-TS-Format": "dayobs",
                "X-Dynamic-Default": "today",
            },
        )
        assert isinstance(schema_today, DayObsParameterSchema)
        assert schema_today.default == "20250101"

        schema_yesterday = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "X-TS-Format": "dayobs",
                "X-Dynamic-Default": "yesterday",
            },
        )
        assert schema_yesterday.default == "20241231"

        schema_tomorrow = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "X-TS-Format": "dayobs",
                "X-Dynamic-Default": "tomorrow",
            },
        )
        assert schema_tomorrow.default == "20250102"

        # Test day offset patterns
        schema_plus_5d = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "X-TS-Format": "dayobs",
                "X-Dynamic-Default": "+5d",
            },
        )
        assert schema_plus_5d.default == "20250106"

        schema_minus_3d = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "X-TS-Format": "dayobs",
                "X-Dynamic-Default": "-3d",
            },
        )
        assert schema_minus_3d.default == "20241229"


def test_dayobs_parameter_dynamic_default_validation() -> None:
    """Test validation of X-Dynamic-Default values for ObsDateParameter."""
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
                "X-TS-Format": "dayobs",
                "X-Dynamic-Default": pattern,
            },
        )
        assert isinstance(schema, DayObsParameterSchema)

    # Invalid patterns should raise validation errors
    invalid_patterns = [
        "invalid_pattern",
        "today_invalid",
        "+5x",  # Invalid unit
        "-10z",  # Invalid unit
        "week_invalid",
        "",
    ]

    for pattern in invalid_patterns:
        with pytest.raises(ParameterDefaultInvalidError):
            create_and_validate_parameter_schema(
                "test_param",
                {
                    "type": "string",
                    "X-TS-Format": "dayobs",
                    "X-Dynamic-Default": pattern,
                },
            )


def test_dayobs_parameter_timezone_handling() -> None:
    """Test DayObsParameterSchema timezone conversions."""
    schema = create_and_validate_parameter_schema(
        "myvar",
        {
            "type": "string",
            "X-TS-Format": "dayobs",
            "default": "20250101",
        },
    )

    # Test various timezone scenarios
    utc_minus_12 = timezone(-timedelta(hours=12))
    utc_plus_9 = timezone(timedelta(hours=9))  # JST

    # Same moment in different timezones
    base_utc = datetime(2025, 2, 15, 12, 0, 0, tzinfo=UTC)

    # UTC 12:00 -> UTC-12 00:00 (same day)
    assert schema.cast_value(base_utc) == 20250215

    # UTC-12 12:00 (already in target timezone)
    utc_minus_12_dt = datetime(2025, 2, 15, 12, 0, 0, tzinfo=utc_minus_12)
    assert schema.cast_value(utc_minus_12_dt) == 20250215

    # JST 09:00 -> UTC 00:00 -> UTC-12 12:00 previous day
    jst_dt = datetime(2025, 2, 15, 9, 0, 0, tzinfo=utc_plus_9)
    assert schema.cast_value(jst_dt) == 20250214


def test_dayobs_parameter_edge_cases() -> None:
    """Test edge cases for DayObsParameterSchema."""
    schema = create_and_validate_parameter_schema(
        "myvar",
        {
            "type": "string",
            "X-TS-Format": "dayobs",
            "default": "20250101",
        },
    )

    # Test leap year dates
    assert schema.cast_value("20240229") == 20240229  # Valid leap year
    assert schema.cast_value(date(2024, 2, 29)) == 20240229

    # Test month/day boundaries
    assert schema.cast_value("20250131") == 20250131  # End of January
    assert schema.cast_value("20250201") == 20250201  # Start of February
    assert schema.cast_value("20251231") == 20251231  # End of year

    # Test year boundaries
    assert schema.cast_value("19990101") == 19990101  # Y2K-1
    assert schema.cast_value("20000101") == 20000101  # Y2K

    # Test invalid dates that would pass regex but fail date parsing
    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("20250229")  # Feb 29 in non-leap year

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("20251301")  # Month 13

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("20250132")  # Day 32


def test_dayobs_parameter_strict_schema() -> None:
    """Test that strict_schema removes custom format and adds regex pattern."""
    schema = create_and_validate_parameter_schema(
        "myvar",
        {
            "type": "string",
            "X-TS-Format": "dayobs",
            "default": "20250101",
            "description": "A dayobs parameter",
        },
    )

    # Get the strict schema (for notebook metadata)
    strict_schema = schema.strict_schema

    # Should have the basic type and description
    assert strict_schema["type"] == "string"
    assert strict_schema["description"] == "A dayobs parameter"
    assert strict_schema["default"] == "20250101"

    # Should NOT have the custom X-TS-Format
    assert "X-TS-Format" not in strict_schema
    assert "format" not in strict_schema

    # Should have a regex pattern to validate YYYYMMDD format
    assert "pattern" in strict_schema
    assert strict_schema["pattern"] == r"^\d{8}$"

    # The pattern should match valid dayobs strings
    pattern = re.compile(strict_schema["pattern"])
    assert pattern.match("20250101") is not None
    assert pattern.match("19991231") is not None
    assert pattern.match("20240229") is not None

    # The pattern should reject invalid formats
    assert pattern.match("2025010") is None  # Too short
    assert pattern.match("202501011") is None  # Too long
    assert pattern.match("2025-01-01") is None  # Has dashes
    assert pattern.match("abcd1234") is None  # Letters
    assert pattern.match("202501ab") is None  # Mixed


def test_dayobs_date_parameter_schema() -> None:
    """Test basic DayObsDateParameterSchema functionality."""
    schema = create_and_validate_parameter_schema(
        "myvar",
        {
            "type": "string",
            "X-TS-Format": "dayobs-date",
            "default": "2025-01-01",
        },
    )
    assert isinstance(schema, DayObsDateParameterSchema)
    assert schema.default == date(2025, 1, 1)

    # Test casting various input types
    assert schema.cast_value("2025-02-15") == date(2025, 2, 15)
    assert schema.cast_value(date(2025, 2, 15)) == date(2025, 2, 15)

    # Test datetime casting with timezone conversion
    utc_dt = datetime(2025, 2, 15, 14, 0, 0, tzinfo=UTC)
    # UTC 14:00 -> UTC-12 02:00 (same day)
    assert schema.cast_value(utc_dt) == date(2025, 2, 15)

    # Test datetime that crosses date boundary due to timezone conversion
    # UTC 02:00 -> UTC-12 14:00 previous day
    utc_dt_early = datetime(2025, 2, 15, 2, 0, 0, tzinfo=UTC)
    assert schema.cast_value(utc_dt_early) == date(2025, 2, 14)

    # Test another boundary case - late UTC time that stays same day in UTC-12
    utc_dt_afternoon = datetime(2025, 2, 15, 18, 0, 0, tzinfo=UTC)
    # UTC 18:00 -> UTC-12 06:00 (same day)
    assert schema.cast_value(utc_dt_afternoon) == date(2025, 2, 15)

    # Test naive datetime (treated as UTC-12)
    naive_dt = datetime(2025, 2, 15, 12, 0, 0, tzinfo=None)  # noqa: DTZ001
    assert schema.cast_value(naive_dt) == date(2025, 2, 15)

    # Test serialization methods
    assert (
        schema.create_python_assignment("myvar", "2025-02-15")
        == 'myvar = datetime.date.fromisoformat("2025-02-15")'
    )
    assert schema.create_python_imports() == ["import datetime"]
    assert schema.create_json_value("2025-02-15") == "2025-02-15"
    assert schema.create_json_value(date(2025, 2, 15)) == "2025-02-15"
    assert schema.create_qs_value("2025-02-15") == "2025-02-15"
    assert schema.create_qs_value(date(2025, 2, 15)) == "2025-02-15"

    # Test error cases
    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("hello")

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("2025-021")  # Too short

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("202502155")  # No dashes, wrong format

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("2025ab15")  # Invalid characters

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("20250215")  # No dashes (YYYYMMDD format)

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value(20250215)  # Integer not supported

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value([])  # Invalid type


def test_dayobs_date_parameter_dynamic_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test DayObsDateParameterSchema with X-Dynamic-Default."""
    # Mock datetime.now to return a fixed datetime in UTC-12 timezone
    # January 1, 2025 at 14:00 UTC-12
    utc_minus_12 = timezone(-timedelta(hours=12))
    fixed_datetime = datetime(2025, 1, 1, 14, 0, 0, tzinfo=utc_minus_12)

    class MockDatetime:
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            if tz is not None:
                return fixed_datetime.astimezone(tz)
            return fixed_datetime

    with monkeypatch.context() as m:
        m.setattr(
            "timessquare.domain.pageparameters._dayobsdateparameter.datetime",
            MockDatetime,
        )

        # Test basic dynamic defaults
        schema_today = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "X-TS-Format": "dayobs-date",
                "X-Dynamic-Default": "today",
            },
        )
        assert isinstance(schema_today, DayObsDateParameterSchema)
        assert schema_today.default == date(2025, 1, 1)

        schema_yesterday = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "X-TS-Format": "dayobs-date",
                "X-Dynamic-Default": "yesterday",
            },
        )
        assert schema_yesterday.default == date(2024, 12, 31)

        schema_tomorrow = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "X-TS-Format": "dayobs-date",
                "X-Dynamic-Default": "tomorrow",
            },
        )
        assert schema_tomorrow.default == date(2025, 1, 2)

        # Test day offset patterns
        schema_plus_5d = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "X-TS-Format": "dayobs-date",
                "X-Dynamic-Default": "+5d",
            },
        )
        assert schema_plus_5d.default == date(2025, 1, 6)

        schema_minus_3d = create_and_validate_parameter_schema(
            "myvar",
            {
                "type": "string",
                "X-TS-Format": "dayobs-date",
                "X-Dynamic-Default": "-3d",
            },
        )
        assert schema_minus_3d.default == date(2024, 12, 29)


def test_dayobs_date_parameter_dynamic_default_validation() -> None:
    """Test validation of X-Dynamic-Default values for DayObsDateParameter."""
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
                "X-TS-Format": "dayobs-date",
                "X-Dynamic-Default": pattern,
            },
        )
        assert isinstance(schema, DayObsDateParameterSchema)

    # Invalid patterns should raise validation errors
    invalid_patterns = [
        "invalid_pattern",
        "today_invalid",
        "+5x",  # Invalid unit
        "-10z",  # Invalid unit
        "week_invalid",
        "",
    ]

    for pattern in invalid_patterns:
        with pytest.raises(ParameterDefaultInvalidError):
            create_and_validate_parameter_schema(
                "test_param",
                {
                    "type": "string",
                    "X-TS-Format": "dayobs-date",
                    "X-Dynamic-Default": pattern,
                },
            )


def test_dayobs_date_parameter_timezone_handling() -> None:
    """Test DayObsDateParameterSchema timezone conversions."""
    schema = create_and_validate_parameter_schema(
        "myvar",
        {
            "type": "string",
            "X-TS-Format": "dayobs-date",
            "default": "2025-01-01",
        },
    )

    # Test various timezone scenarios
    utc_minus_12 = timezone(-timedelta(hours=12))
    utc_plus_9 = timezone(timedelta(hours=9))  # JST

    # Same moment in different timezones
    base_utc = datetime(2025, 2, 15, 12, 0, 0, tzinfo=UTC)

    # UTC 12:00 -> UTC-12 00:00 (same day)
    assert schema.cast_value(base_utc) == date(2025, 2, 15)

    # UTC-12 12:00 (already in target timezone)
    utc_minus_12_dt = datetime(2025, 2, 15, 12, 0, 0, tzinfo=utc_minus_12)
    assert schema.cast_value(utc_minus_12_dt) == date(2025, 2, 15)

    # JST 09:00 -> UTC 00:00 -> UTC-12 12:00 previous day
    jst_dt = datetime(2025, 2, 15, 9, 0, 0, tzinfo=utc_plus_9)
    assert schema.cast_value(jst_dt) == date(2025, 2, 14)


def test_dayobs_date_parameter_edge_cases() -> None:
    """Test edge cases for DayObsDateParameterSchema."""
    schema = create_and_validate_parameter_schema(
        "myvar",
        {
            "type": "string",
            "X-TS-Format": "dayobs-date",
            "default": "2025-01-01",
        },
    )

    # Test leap year dates
    assert schema.cast_value("2024-02-29") == date(
        2024, 2, 29
    )  # Valid leap year
    assert schema.cast_value(date(2024, 2, 29)) == date(2024, 2, 29)

    # Test month/day boundaries
    assert schema.cast_value("2025-01-31") == date(
        2025, 1, 31
    )  # End of January
    assert schema.cast_value("2025-02-01") == date(
        2025, 2, 1
    )  # Start of February
    assert schema.cast_value("2025-12-31") == date(2025, 12, 31)  # End of year

    # Test year boundaries
    assert schema.cast_value("1999-01-01") == date(1999, 1, 1)  # Y2K-1
    assert schema.cast_value("2000-01-01") == date(2000, 1, 1)  # Y2K

    # Test invalid dates that would pass regex but fail date parsing
    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("2025-02-29")  # Feb 29 in non-leap year

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("2025-13-01")  # Month 13

    with pytest.raises(PageParameterValueCastingError):
        schema.cast_value("2025-01-32")  # Day 32


def test_dayobs_date_parameter_strict_schema() -> None:
    """Test that strict_schema removes custom format and adds regex pattern."""
    schema = create_and_validate_parameter_schema(
        "myvar",
        {
            "type": "string",
            "X-TS-Format": "dayobs-date",
            "default": "2025-01-01",
            "description": "A dayobs-date parameter",
        },
    )

    # Get the strict schema (for notebook metadata)
    strict_schema = schema.strict_schema

    # Should have the basic type and description
    assert strict_schema["type"] == "string"
    assert strict_schema["description"] == "A dayobs-date parameter"
    assert strict_schema["default"] == "2025-01-01"

    # Should NOT have the custom X-TS-Format
    assert "X-TS-Format" not in strict_schema
    assert "format" not in strict_schema

    # Should have a regex pattern to validate YYYY-MM-DD format
    assert "pattern" in strict_schema
    assert strict_schema["pattern"] == r"^\d{4}-\d{2}-\d{2}$"

    # The pattern should match valid dayobs-date strings
    pattern = re.compile(strict_schema["pattern"])
    assert pattern.match("2025-01-01") is not None
    assert pattern.match("1999-12-31") is not None
    assert pattern.match("2024-02-29") is not None

    # The pattern should reject invalid formats
    assert pattern.match("2025-1-01") is None  # Single digit month
    assert pattern.match("2025-01-1") is None  # Single digit day
    assert pattern.match("25-01-01") is None  # Two digit year
    assert pattern.match("20250101") is None  # No dashes
    assert pattern.match("2025/01/01") is None  # Wrong separators
    assert pattern.match("abcd-12-34") is None  # Letters
    assert pattern.match("2025-ab-01") is None  # Mixed
