"""Tests for the timessquare.storage.github.settingsfiles module."""

from __future__ import annotations

from pathlib import Path

from safir.github.models import GitHubBlobModel

from timessquare.storage.github.settingsfiles import (
    NotebookSidecarFile,
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
