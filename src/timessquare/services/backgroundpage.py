"""A Page service specifically for use in Arq workers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from timessquare.domain.page import PageInstanceModel
from timessquare.storage.noteburst import NoteburstJobResponseModel

from .page import PageService


class BackgroundPageService(PageService):
    """A Page service specifically for use in Arq workers.

    This is a subclass of PageService that is specifically designed to be
    used in Arq workers. This service includes additional methods that are
    only suitable for use in the background.
    """

    async def update_nbhtml(
        self,
        page_name: str,
        parameter_values: Mapping[str, Any],
        noteburst_response: NoteburstJobResponseModel,
    ) -> None:
        """Recompute a page instance with noteburst and update the HTML cache.

        This method is used with the ``recompute_page_instance`` task, which is
        triggered by a soft delete of a page instance. In a soft-delete, the
        page is instance is recomputed in the background while current users
        see the stale version.

        Parameters
        ----------
        page_name
            The name of the page to recompute.
        parameter_values
            The parameter values to use when recomputing the page instance.
        """
        page = await self.get_page(page_name)
        resolved_values = page.resolve_and_validate_values(parameter_values)
        page_instance = PageInstanceModel(
            name=page.name, values=resolved_values, page=page
        )
        # Create HTML for each display setting and store it in the cache
        await self.render_nbhtml_matrix_from_noteburst_response(
            page_instance=page_instance, noteburst_response=noteburst_response
        )
