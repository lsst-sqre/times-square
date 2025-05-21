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
        page_instance = PageInstanceModel(
            page=page, values=dict(parameter_values)
        )
        # Create HTML for each display setting and store it in the cache
        await self.render_nbhtml_matrix_from_noteburst_response(
            page_instance=page_instance, noteburst_response=noteburst_response
        )

    async def migrate_ipynb_with_nbstripout(
        self, *, dry_run: bool = True, for_page_id: str | None = None
    ) -> int:
        """Migrate the ipynb files with nbstripout to remove outputs
        and metadata.

        This service method is intended to be run once via the
        ``times-square nbstripout`` CLI command.

        Returns
        -------
        int
            The number of pages that were migrated (or would be migrated,
            if in dry-run).
        """
        if for_page_id:
            return await self._run_nbstripout_on_page(
                dry_run=dry_run, page_id=for_page_id
            )

        page_count = 0
        for page_id in await self._page_store.list_page_names():
            page_count += await self._run_nbstripout_on_page(
                dry_run=dry_run, page_id=page_id
            )

        return page_count

    async def _run_nbstripout_on_page(
        self, *, dry_run: bool = True, page_id: str
    ) -> int:
        """Run nbstripout on a page."""
        try:
            page = await self.get_page(page_id)
        except Exception as e:
            self._logger.warning(
                "Skipping page with error", page_id=page_id, error=str(e)
            )
            return 0

        if not page.ipynb:
            self._logger.warning(
                "Skipping page with no ipynb", page_id=page_id
            )
            return 0

        # Run nbstripout on the ipynb file
        ipynb = page.read_ipynb(page.ipynb)
        if has_kernelspec := "kernelspec" in ipynb.metadata:
            self._logger.debug(
                "ipynb has kernelspec metadata", page_id=page_id
            )
        if not dry_run:
            page.strip_ipynb()
            await self.update_page_in_store(page, drop_html_cache=False)
        return 1 if has_kernelspec else 0
