"""Tests for the timessquare.storage.github.settingsfiles module."""

from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError
from safir.github.models import GitHubBlobModel

from timessquare.domain.pageparameters import (
    DateParameterSchema,
    DatetimeParameterSchema,
    ObsDateParameterSchema,
)
from timessquare.storage.github.settingsfiles import (
    NotebookSidecarFile,
    ParameterSchemaModel,
    RepositorySettingsFile,
)


def test_settings_file_load() -> None:
    json_path = Path(__file__).parent.joinpath(
        "../../data/times-square-demo/settings-blob.json"
    )
    blob = GitHubBlobModel.model_validate_json(json_path.read_text())
    settings = RepositorySettingsFile.parse_yaml(blob.decode())
    assert settings.enabled is True


def test_load_sidecar() -> None:
    sidecar_path = Path(__file__).parent.joinpath(
        "../../data/times-square-demo/demo.yaml"
    )
    sidecar = NotebookSidecarFile.parse_yaml(sidecar_path.read_text())
    parameters = sidecar.export_parameters()
    assert parameters is not None


def test_date_format_parameter() -> None:
    json_schema = {
        "type": "string",
        "format": "date",
        "description": "A date",
        "default": "2021-01-01",
    }
    parameter = ParameterSchemaModel.model_validate(json_schema)
    parameter_schema = parameter.to_parameter_schema("mydate")
    assert isinstance(parameter_schema, DateParameterSchema)


def test_datetime_format_parameter() -> None:
    json_schema = {
        "type": "string",
        "format": "date-time",
        "description": "A date and time",
        "default": "2021-01-01T00:00:00Z",
    }
    parameter = ParameterSchemaModel.model_validate(json_schema)
    parameter_schema = parameter.to_parameter_schema("mydatetime")
    assert isinstance(parameter_schema, DatetimeParameterSchema)


def test_datetime_format_parameter_no_tz() -> None:
    json_schema = {
        "type": "string",
        "format": "date-time",
        "description": "A date and time",
        "default": "2021-01-01T00:00:00",
    }
    parameter = ParameterSchemaModel.model_validate(json_schema)
    parameter_schema = parameter.to_parameter_schema("mydatetime")
    # This seems to be supported currently
    assert isinstance(parameter_schema, DatetimeParameterSchema)


def test_dynamic_date_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test the dynamic default functionality with a date parameter."""

    class MockDatetime:
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            return datetime(2025, 5, 16, 12, 0, 0, tzinfo=tz)

    # Apply the monkeypatch for the entire test
    monkeypatch.setattr(
        "timessquare.domain.pageparameters._datedynamicdefault.datetime",
        MockDatetime,
    )

    json_schema = {
        "type": "string",
        "format": "date",
        "description": "A dynamic date",
        "dynamic_default": "+7d",
    }
    parameter = ParameterSchemaModel.model_validate(json_schema)
    parameter_schema = parameter.to_parameter_schema("mydynamicdate")
    assert isinstance(parameter_schema, DateParameterSchema)
    assert parameter_schema.default == date(2025, 5, 23)


def test_dynamic_date_default_invalid() -> None:
    """Test that an invalid dynamic date default raises a validation error."""
    json_schema = {
        "type": "string",
        "format": "date",
        "description": "An invalid dynamic date",
        "dynamic_default": "invalid_format",
    }
    with pytest.raises(
        ValidationError, match="Invalid dynamic_default format"
    ):
        ParameterSchemaModel.model_validate(json_schema)


def test_dynamic_default_with_non_date_parameter() -> None:
    """Test that a dynamic default on a non-date parameter raises an error."""
    json_schema = {
        "type": "string",
        "format": "date-time",  # this isn't supported for dynamic defaults
        "description": "A string with dynamic default",
        "dynamic_default": "+7d",
    }
    with pytest.raises(
        ValidationError, match="dynamic_default can only be set when"
    ):
        ParameterSchemaModel.model_validate(json_schema)


def test_default_with_dynamic_default() -> None:
    """Test that a default value and dynamic default cannot be set together."""
    json_schema = {
        "type": "string",
        "format": "date",
        "description": "A date with dynamic default",
        "dynamic_default": "+7d",
        "default": "2021-01-01",  # This should raise an error
    }
    with pytest.raises(
        ValidationError,
        match="Either default or dynamic_default must be set, but not both",
    ):
        ParameterSchemaModel.model_validate(json_schema)

    # Test when neither default nor dynamic_default is set
    json_schema = {
        "type": "string",
        "format": "date",
        "description": "A date without default",
    }
    with pytest.raises(
        ValidationError, match="Either default or dynamic_default must be set"
    ):
        ParameterSchemaModel.model_validate(json_schema)


def test_dayobs_format_parameter() -> None:
    """Test that dayobs format creates ObsDateParameterSchema."""
    json_schema = {
        "type": "string",
        "format": "dayobs",
        "description": "A dayobs date",
        "default": "20250101",
    }
    parameter = ParameterSchemaModel.model_validate(json_schema)
    parameter_schema = parameter.to_parameter_schema("mydayobs")
    assert isinstance(parameter_schema, ObsDateParameterSchema)


def test_dayobs_format_parameter_with_dynamic_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test dayobs format with dynamic default values."""

    class MockDatetime:
        @classmethod
        def now(cls, tz: timezone | None = None) -> datetime:
            return datetime(2025, 1, 15, 12, 0, 0, tzinfo=tz)

    # Apply the monkeypatch for the entire test
    monkeypatch.setattr(
        "timessquare.domain.pageparameters._obsdateparameter.datetime",
        MockDatetime,
    )

    json_schema = {
        "type": "string",
        "format": "dayobs",
        "description": "A dynamic dayobs date",
        "dynamic_default": "today",
    }
    parameter = ParameterSchemaModel.model_validate(json_schema)
    parameter_schema = parameter.to_parameter_schema("mydynamicdayobs")
    assert isinstance(parameter_schema, ObsDateParameterSchema)
    assert parameter_schema.default == "20250115"


def test_dayobs_format_parameter_validation() -> None:
    """Test validation for dayobs format parameters."""
    # Valid dynamic default patterns for dayobs
    valid_patterns = ["today", "yesterday", "+7d", "month_start"]

    for pattern in valid_patterns:
        json_schema = {
            "type": "string",
            "format": "dayobs",
            "description": "A dayobs date with dynamic default",
            "dynamic_default": pattern,
        }
        parameter = ParameterSchemaModel.model_validate(json_schema)
        assert parameter.format == "dayobs"
        assert parameter.dynamic_default == pattern

    # Invalid dynamic default pattern should raise validation error
    json_schema = {
        "type": "string",
        "format": "dayobs",
        "description": "A dayobs date with invalid dynamic default",
        "dynamic_default": "invalid_pattern",
    }
    with pytest.raises(
        ValidationError, match="Invalid dynamic_default format"
    ):
        ParameterSchemaModel.model_validate(json_schema)


def test_dayobs_format_parameter_json_schema_conversion() -> None:
    """Test that dayobs format is converted to X-TS-Format in JSON schema."""
    json_schema = {
        "type": "string",
        "format": "dayobs",
        "description": "A dayobs date",
        "default": "20250101",
    }
    parameter = ParameterSchemaModel.model_validate(json_schema)
    parameter_schema = parameter.to_parameter_schema("mydayobs")

    # Check that the underlying JSON schema uses X-TS-Format instead of format
    schema_format = parameter_schema.schema.get("format")
    assert schema_format != "dayobs" or "format" not in parameter_schema.schema
    assert parameter_schema.schema.get("X-TS-Format") == "dayobs"
