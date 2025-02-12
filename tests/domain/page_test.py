"""Tests for the Page service."""

from __future__ import annotations

from pathlib import Path

import pytest

from timessquare.domain.page import PageModel
from timessquare.exceptions import ParameterNameValidationError


def test_parameter_name_validation() -> None:
    PageModel.validate_parameter_name("myvar")
    PageModel.validate_parameter_name("my_var")
    PageModel.validate_parameter_name("myvar1")
    PageModel.validate_parameter_name("Myvar1")
    PageModel.validate_parameter_name("M")

    with pytest.raises(ParameterNameValidationError):
        PageModel.validate_parameter_name(" M")
    with pytest.raises(ParameterNameValidationError):
        PageModel.validate_parameter_name("1p")
    with pytest.raises(ParameterNameValidationError):
        PageModel.validate_parameter_name("lambda")


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
    rendered = page.render_parameters(
        values={"A": 2, "y0": 1.0, "lambd": 0.5, "title": "Demo"}
    )
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
        "# Parameters\nA = 2\nlambd = 0.5\ntitle = 'Demo'\ny0 = 1.0"
    )

    # Check that the second code cell was unchanged
    assert rendered_nb["cells"][2]["source"] == nb["cells"][2]["source"]
