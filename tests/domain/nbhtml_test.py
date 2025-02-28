"""Tests for the NbHtml domain."""

from __future__ import annotations

from timessquare.domain.nbhtml import NbDisplaySettings, NbHtmlKey
from timessquare.domain.page import PageInstanceIdModel


def test_nbdisplay_settings_from_url_params() -> None:
    settings = NbDisplaySettings.from_url_params(
        {"ts_hide_code": "1", "other_parameter": "hello"}
    )
    assert settings.hide_code is True
    assert settings.url_query_string == "ts_hide_code=1"
    assert settings.cache_key == "ts_hide_code=1"

    # Test with hide_code disabled
    settings = NbDisplaySettings.from_url_params(
        {"ts_hide_code": "0", "other_parameter": "hello"}
    )
    assert settings.hide_code is False
    assert settings.url_query_string == "ts_hide_code=0"
    assert settings.cache_key == "ts_hide_code=0"

    # Test with defaults
    settings = NbDisplaySettings.from_url_params({})
    assert settings.hide_code is True
    assert settings.url_query_string == "ts_hide_code=1"
    assert settings.cache_key == "ts_hide_code=1"


def test_nbhtml_key() -> None:
    page_instance_id = PageInstanceIdModel(
        name="demo",
        parameter_values={"A": "2", "y0": "1.0", "lambd": "0.5"},
    )
    key = NbHtmlKey(
        display_settings=NbDisplaySettings(hide_code=True),
        page_instance_id=page_instance_id,
    )
    assert key.cache_key == "demo/A=2&lambd=0.5&y0=1.0/ts_hide_code=1"
    assert key.url_query_string == "A=2&lambd=0.5&y0=1.0&ts_hide_code=1"

    key = NbHtmlKey(
        display_settings=NbDisplaySettings(hide_code=False),
        page_instance_id=page_instance_id,
    )
    assert key.cache_key == "demo/A=2&lambd=0.5&y0=1.0/ts_hide_code=0"
    assert key.url_query_string == "A=2&lambd=0.5&y0=1.0&ts_hide_code=0"
