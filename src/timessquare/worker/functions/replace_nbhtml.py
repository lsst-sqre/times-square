"""A worker task that replaces a page isntance's HTML in the cache
if a Noteburst job is complete.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from safir.dependencies.db_session import db_session_dependency
from safir.slack.blockkit import SlackCodeBlock, SlackMessage, SlackTextField

from timessquare.storage.noteburst import (
    NoteburstApi,
    NoteburstJobModel,
    NoteburstJobStatus,
)
from timessquare.worker.servicefactory import (
    create_arq_queue,
    create_page_service,
)


async def replace_nbhtml(
    ctx: dict[Any, Any],
    *,
    page_name: str,
    parameter_values: Mapping[str, Any],
    noteburst_job: NoteburstJobModel,
) -> str:
    """Recompute a page instance with noteburst and update the HTML cache.

    This function is triggered with a page instance (HTML rendering) is soft
    deleted so that it's recomputed in the background while current users
    see the stale version.
    """
    logger = ctx["logger"].bind(
        task="replace_nbhtml",
        page=page_name,
        parameter_values=parameter_values,
    )
    logger.info("Running replace_nbhtml")

    try:
        noteburst_client = NoteburstApi(
            http_client=ctx["http_client"],
        )
        updated_job_result = await noteburst_client.get_job(
            str(noteburst_job.job_url)
        )
        if not updated_job_result.data:
            raise RuntimeError(
                f"Failed to get noteburst job at {noteburst_job.job_url}"
            )

        async for db_session in db_session_dependency():
            page_service = await create_page_service(
                http_client=ctx["http_client"],
                logger=logger,
                db_session=db_session,
            )

            if updated_job_result.data.status == NoteburstJobStatus.complete:
                # Job finished, so render the HTML and update the cache
                await page_service.update_nbhtml(
                    page_name=page_name,
                    parameter_values=parameter_values,
                    noteburst_response=updated_job_result.data,
                )
            elif (
                updated_job_result.data.status == NoteburstJobStatus.not_found
            ):
                # Job was lost, so re-send the request
                await page_service.soft_delete_html(
                    name=page_name, query_params=parameter_values
                )
            else:
                # Job is still queued or running, so scheduled another task
                # TODO(jonathansick): add a start time and a timeout to the
                # job's parameters so we can abort if it takes too long.
                arq_queue = await create_arq_queue()
                await arq_queue.enqueue(
                    "replace_nbhtml",
                    page_name=page_name,
                    parameter_values=parameter_values,
                    noteburst_job=updated_job_result.data.to_job_model(),
                    _defer_by=1,  # look again in 1 second
                )

    except Exception as e:
        if "slack" in ctx:
            await ctx["slack"].post(
                SlackMessage(
                    message="Times Square worker exception.",
                    fields=[
                        SlackTextField(
                            heading="Task", text="recompute_page_instance"
                        ),
                        SlackTextField(heading="Page", text=page_name),
                    ],
                    blocks=[
                        SlackCodeBlock(
                            heading="Parameters",
                            code=json.dumps(
                                parameter_values, indent=2, sort_keys=True
                            ),
                        ),
                        SlackCodeBlock(
                            heading="Exception",
                            code=str(e),
                        ),
                    ],
                )
            )
        raise

    return "Done"
