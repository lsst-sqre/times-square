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
    page_instance = PageInstanceModel(page=page, values=values)
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
        "title = 'Demo'\n"
        "y0 = 1.0"
    )

    # Check that the second code cell was unchanged
    assert rendered_nb["cells"][2]["source"] == nb["cells"][2]["source"]

    # Check that the kernelspec was removed
    assert "kernelspec" not in rendered_nb["metadata"]
    # But keep the times-square metadata
    assert "times-square" in rendered_nb["metadata"]


def test_page_instance_id_model() -> None:
    page_instance_id = PageInstanceIdModel(
        name="demo",
        parameter_values={"A": "2", "y0": "1.0", "lambd": "0.5"},
    )
    assert page_instance_id.cache_key == "demo/A=2&lambd=0.5&y0=1.0"
    assert page_instance_id.url_query_string == "A=2&lambd=0.5&y0=1.0"


def test_mark_parameters_cell() -> None:
    """Test PageModel.mark_parameters_cell()."""
    ipynb_path = Path(__file__).parent.parent / "data" / "demo.ipynb"
    ipynb = ipynb_path.read_text()

    page = PageModel.create_from_api_upload(
        ipynb=ipynb,
        title="Test marking",
        uploader_username="testuser",
    )

    # Initially no metadata on cells
    nb = PageModel.read_ipynb(page.ipynb)
    first_code_cell = next(c for c in nb.cells if c.cell_type == "code")
    assert (
        first_code_cell.metadata.get("times_square", {}).get("cell_type")
        != "parameters"
    )

    # Mark the parameters cell
    page.mark_parameters_cell()

    # Verify first code cell is marked
    nb = PageModel.read_ipynb(page.ipynb)
    first_code_cell = next(c for c in nb.cells if c.cell_type == "code")
    assert (
        first_code_cell.metadata.get("times_square", {}).get("cell_type")
        == "parameters"
    )

    # Verify only first code cell is marked
    code_cells = [c for c in nb.cells if c.cell_type == "code"]
    assert len(code_cells) > 1, (
        "Test requires notebook with multiple code cells"
    )
    for cell in code_cells[1:]:
        assert (
            cell.metadata.get("times_square", {}).get("cell_type")
            != "parameters"
        )


def test_mark_parameters_cell_idempotent() -> None:
    """Test that mark_parameters_cell() is idempotent."""
    ipynb_path = Path(__file__).parent.parent / "data" / "demo.ipynb"
    ipynb = ipynb_path.read_text()

    page = PageModel.create_from_api_upload(
        ipynb=ipynb,
        title="Test idempotence",
        uploader_username="testuser",
    )

    # Mark twice
    page.mark_parameters_cell()
    ipynb_after_first = page.ipynb
    page.mark_parameters_cell()
    ipynb_after_second = page.ipynb

    # Should be identical
    assert ipynb_after_first == ipynb_after_second


def test_mark_parameters_cell_respects_existing() -> None:
    """Test that mark_parameters_cell() respects author-specified cells."""
    ipynb_path = Path(__file__).parent.parent / "data" / "demo.ipynb"
    ipynb = ipynb_path.read_text()

    page = PageModel.create_from_api_upload(
        ipynb=ipynb,
        title="Test author-specified",
        uploader_username="testuser",
    )

    # Manually mark the second code cell as parameters
    nb = PageModel.read_ipynb(page.ipynb)
    code_cells = [c for c in nb.cells if c.cell_type == "code"]
    assert len(code_cells) >= 2, "Test requires at least 2 code cells"

    # Mark the second code cell
    code_cells[1].metadata["times_square"] = {"cell_type": "parameters"}
    page.ipynb = PageModel.write_ipynb(nb)

    # Now call mark_parameters_cell() - should not change anything
    page.mark_parameters_cell()

    # Verify the second code cell is still the marked one
    nb_after = PageModel.read_ipynb(page.ipynb)
    code_cells_after = [c for c in nb_after.cells if c.cell_type == "code"]

    # First code cell should NOT be marked
    assert (
        code_cells_after[0].metadata.get("times_square", {}).get("cell_type")
        != "parameters"
    )

    # Second code cell should still be marked
    assert (
        code_cells_after[1].metadata.get("times_square", {}).get("cell_type")
        == "parameters"
    )


def test_render_with_marked_parameters_cell() -> None:
    """Test that render_ipynb() uses metadata to find parameters cell."""
    ipynb_path = Path(__file__).parent.parent / "data" / "demo.ipynb"
    ipynb = ipynb_path.read_text()

    page = PageModel.create_from_api_upload(
        ipynb=ipynb,
        title="Test marked params",
        uploader_username="testuser",
    )

    # Mark the parameters cell
    page.mark_parameters_cell()

    # Render with parameters
    values = {
        "A": 5,
        "y0": 2.0,
        "lambd": 0.3,
        "title": "Marked Test",
        "mydate": "2021-06-15",
        "mydatetime": "2021-06-15T10:30:00+00:00",
    }
    page_instance = PageInstanceModel(page=page, values=values)
    rendered = page_instance.render_ipynb()
    rendered_nb = PageModel.read_ipynb(rendered)

    # Find the parameters cell by metadata
    params_cell = next(
        c
        for c in rendered_nb.cells
        if c.cell_type == "code"
        and c.metadata.get("times_square", {}).get("cell_type") == "parameters"
    )

    # Verify it was replaced with parameter assignments
    assert "A = 5" in params_cell.source
    assert "y0 = 2.0" in params_cell.source
