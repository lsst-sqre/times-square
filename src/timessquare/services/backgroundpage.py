"""A Page service specifically for use in Arq workers."""

from __future__ import annotations

import json
from base64 import b64decode
from collections.abc import Mapping
from typing import Any

from timessquare.domain.nbhtml import NbDisplaySettings, NbHtmlKey
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

    async def migrate_html_cache_keys(
        self, *, dry_run: bool = True, for_page_id: str | None = None
    ) -> int:
        """Migrate Redis keys to the new format.

        Parameters
        ----------
        dry_run
            If `True`, don't actually migrate the keys, but log what would be
            done.
        for_page_id
            If set, only migrate keys for the given page ID.

        Returns
        -------
        key_count
            The number of keys that were migrated (or would be migrated,
            if in dry-run).
        """
        key_count = 0
        if for_page_id:
            key_count += await self._migrate_html_cache_keys_for_page(
                dry_run=dry_run, page_id=for_page_id
            )
            return key_count

        for page_id in await self._page_store.list_page_names():
            key_count += await self._migrate_html_cache_keys_for_page(
                dry_run=dry_run, page_id=page_id
            )

        return key_count

    async def _migrate_html_cache_keys_for_page(
        self, *, dry_run: bool = True, page_id: str
    ) -> int:
        """Migrate the HTML cache keys for a specific page."""
        key_count = 0
        try:
            page = await self.get_page(page_id)
        except Exception as e:
            self._logger.warning(
                "Skipping page with error", page_id=page_id, error=str(e)
            )
            return key_count
        existing_keys = await self._html_store.list_keys_for_page(page.name)
        for existing_key in existing_keys:
            key_components = existing_key.split("/")
            if len(key_components) != 3:
                self._logger.warning(
                    "Skipping key with unexpected format",
                    key=existing_key,
                )
                continue
            if key_components[0] != page_id:
                self._logger.warning(
                    "Skipping key with unexpected page ID",
                    key=existing_key,
                    expected_page_id=page_id,
                )
                continue
            try:
                page_instance_values = json.loads(
                    b64decode(key_components[1]).decode("utf-8")
                )
            except Exception as e:
                self._logger.warning(
                    "Skipping key with invalid parameter values",
                    key=existing_key,
                    error=str(e),
                )
                continue
            try:
                display_settings_values = json.loads(
                    b64decode(key_components[2]).decode("utf-8")
                )
            except Exception as e:
                self._logger.warning(
                    "Skipping key with invalid display settings",
                    key=existing_key,
                    error=str(e),
                )
                continue

            try:
                page_instance = PageInstanceModel(
                    page=page, values=page_instance_values
                )
                page_instance_id = page_instance.id
            except Exception as e:
                self._logger.warning(
                    "Skipping key with invalid page instance values",
                    key=existing_key,
                    error=str(e),
                )
                continue
            try:
                display_settings = NbDisplaySettings(
                    hide_code=(display_settings_values.get("hide_code", True))
                )
                nb_html_key = NbHtmlKey(
                    display_settings=display_settings,
                    page_instance_id=page_instance_id,
                )
            except Exception as e:
                self._logger.warning(
                    "Skipping key with invalid display settings",
                    key=existing_key,
                    error=str(e),
                )
                continue
            new_cache_key = nb_html_key.cache_key
            if dry_run:
                self._logger.info(
                    "Would rename key",
                    old_key=existing_key,
                    new_key=new_cache_key,
                )
            else:
                await self._html_store.rename_key(existing_key, new_cache_key)
                self._logger.info(
                    "Renamed html cache key",
                    old_key=existing_key,
                    new_key=new_cache_key,
                )
            key_count += 1

        return key_count
