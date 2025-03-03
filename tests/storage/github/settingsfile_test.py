"""Tests for the timessquare.storage.github.settingsfiles module."""

from __future__ import annotations

from pathlib import Path

from safir.github.models import GitHubBlobModel

from timessquare.domain.pageparameters import (
    DateParameterSchema,
    DatetimeParameterSchema,
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
