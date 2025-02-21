"""Tests for the Page domain."""

from __future__ import annotations

from pathlib import Path

from timessquare.domain.page import (
    PageInstanceIdModel,
    PageInstanceModel,
    PageModel,
)


def test_render_parameters() -> None:
    """Test PageInstanceModel.render_parameters()."""
    ipynb_path = Path(__file__).parent.parent / "data" / "demo.ipynb"
    ipynb = ipynb_path.read_text()
    nb = PageModel.read_ipynb(ipynb)
    page = PageModel.create_from_api_upload(
        ipynb=ipynb,
        title="Demo",
        uploader_username="testuser",
    )
    print(list(page.parameters.keys()))
    values = {
        "A": 2,
        "y0": 1.0,
        "lambd": 0.5,
        "title": "Demo",
        "mydate": "2021-01-01",
        "mydatetime": "2021-01-01T12:00:00+00:00",
    }
    page_instance = PageInstanceModel.create(page=page, values=values)
    rendered = page_instance.render_ipynb()
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
        "- Title: Demo\n"
        "- Flag: True"
    )

    # Check that the first code cell got replaced
    assert rendered_nb["cells"][1]["source"] == (
        "# Parameters\n"
        "import datetime\n"
        "A = 2\n"
        "boolflag = True\n"
        "lambd = 0.5\n"
        'mydate = datetime.date.fromisoformat("2021-01-01")\n'
        "mydatetime = datetime.datetime.fromisoformat"
        '("2021-01-01T12:00:00+00:00")\n'
        'title = "Demo"\n'
        "y0 = 1.0"
    )

    # Check that the second code cell was unchanged
    assert rendered_nb["cells"][2]["source"] == nb["cells"][2]["source"]


def test_page_instance_id_model() -> None:
    page_instance_id = PageInstanceIdModel(
        name="demo",
        parameter_values={"A": "2", "y0": "1.0", "lambd": "0.5"},
    )
    assert page_instance_id.cache_key == "demo/A=2&lambd=0.5&y0=1.0"
    assert page_instance_id.url_query_string == "A=2&lambd=0.5&y0=1.0"
