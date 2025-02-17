"""Tests for the Page service."""

from __future__ import annotations

from pathlib import Path

from timessquare.domain.page import PageModel


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
    print(list(page.parameters.keys()))
    values = page.parameters.resolve_values(
        {
            "A": 2,
            "y0": 1.0,
            "lambd": 0.5,
            "title": "Demo",
        }
    )
    rendered = page.render_parameters(values=values)
    rendered_nb = PageModel.read_ipynb(rendered)

    # Check that the markdown got rendered
    assert rendered_nb["cells"][0]["source"] == (
        "# Times Square demo\n"
        "\n"
        "Plot parameters:\n"
        "\n"
        "- Amplitude: A = 2\n"
        "- Y offset: y0 = 1.0\n"
        "- Wavelength: lambd = 0.5\n"
        "- Title: 'Demo'\n"
        "- Flag: True"
    )

    # Check that the first code cell got replaced
    assert rendered_nb["cells"][1]["source"] == (
        "# Parameters\n"
        "A = 2\n"
        "boolflag = True\n"
        "lambd = 0.5\n"
        'title = "Demo"\n'
        "y0 = 1.0"
    )

    # Check that the second code cell was unchanged
    assert rendered_nb["cells"][2]["source"] == nb["cells"][2]["source"]
