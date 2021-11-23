"""The parmeterized notebook page service."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any, Dict

import jsonschema.exceptions
import nbformat
from jsonschema import Draft202012Validator

from timessquare.domain.page import PageModel
from timessquare.exceptions import (
    PageNotFoundError,
    ParameterDefaultInvalidError,
    ParameterDefaultMissingError,
    ParameterNameValidationError,
    ParameterSchemaError,
)

if TYPE_CHECKING:
    from structlog.stdlib import BoundLogger

    from timessquare.storage.page import PageStore


NB_VERSION = 4
"""The notebook format version used for reading and writing notebooks.

Generally this version should be upgraded as needed to support more modern
notebook formats, while also being compatible with this app.
"""

parameter_name_pattern = re.compile(
    r"^"
    r"[a-zA-Z]"  # initial characters are letters only
    r"[_a-zA-Z0-9]*$"  # following characters are letters and numbers
    r"$"
)


class PageService:
    """A service manager for parameterized notebook pages.

    Parameters
    ----------
    page_store : `timessquare.storage.page.PageStore
        The PageStore, which adapts the database backend.
    logger : `structlog.stdlib.BoundLogger`
        The logger instance, bound with context about the request.
    """

    def __init__(
        self,
        page_store: PageStore,
        logger: BoundLogger,
    ) -> None:
        self._page_store = page_store
        self._logger = logger

    def create_page_with_notebook(self, name: str, ipynb: str) -> None:
        """Create a page resource given the parameterized Jupyter Notebook
        content.
        """
        notebook = self._read_ipynb(ipynb)
        parameters = self._extract_parameters(notebook)

        page = PageModel(name=name, ipynb=ipynb, parameters=parameters)
        self._page_store.add(page)

    async def get_page(self, name: str) -> PageModel:
        """Get the page from the data store, given its name."""
        page = await self._page_store.get(name)
        if page is None:
            raise PageNotFoundError(name)
        return page

    def _read_ipynb(self, ipynb: str) -> nbformat.NotebookNode:
        """Parse the Jupyter Notebook."""
        return nbformat.reads(ipynb, as_version=NB_VERSION)

    def _extract_parameters(
        self, notebook: nbformat.NotebookNode
    ) -> Dict[str, Dict[str, Any]]:
        """Get the page parmeters from the notebook.

        Parameters are located in the Jupyter Notebook's metadata under
        the ``times-square.parameters`` path. Each key is a parameter name,
        and each value is a JSON Schema description of that paramter.
        """
        try:
            parameters_metadata = notebook.metadata["times-square"].parameters
        except AttributeError:
            return {}

        for name, schema in parameters_metadata.items():
            self.validate_parameter_schema(name, schema)

        return parameters_metadata

    @staticmethod
    def validate_parameter_schema(name: str, schema: Dict[str, Any]) -> None:
        """Validate a parameter's name and schema.

        Raises
        ------
        ParameterValidationError
            Raised if the parameter is invalid (a specific subclass is raised
            for each type of validation check).
        """
        PageService.validate_parameter_name(name)

        try:
            Draft202012Validator.check_schema(schema)
        except jsonschema.exceptions.SchemaError as e:
            raise ParameterSchemaError(name, str(e))

        validator = Draft202012Validator(schema)

        if "default" not in schema:
            raise ParameterDefaultMissingError(name)
        else:
            if not validator.is_valid(schema["default"]):
                raise ParameterDefaultInvalidError(name, schema["default"])

    @staticmethod
    def validate_parameter_name(name: str) -> None:
        if parameter_name_pattern.match(name) is None:
            raise ParameterNameValidationError(name)
