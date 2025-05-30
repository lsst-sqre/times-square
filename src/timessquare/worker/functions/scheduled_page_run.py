"""A worker task that runs a page given a scheduled event."""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from safir.dependencies.db_session import db_session_dependency
from safir.slack.blockkit import SlackCodeBlock, SlackMessage, SlackTextField

from timessquare.storage.noteburst import NoteburstApi, NoteburstJobStatus
from timessquare.worker.servicefactory import create_page_service


async def scheduled_page_run(
    ctx: dict[Any, Any],
    *,
    page_name: str,
    scheduled_time: datetime,
) -> str:
    """Run a page from a scheduled event.

    These jobs are enqueued by the RunSchedulerService according to the page's
    schedule. This function is different from replace_nbhtml in that it waits
    for the Noteburst job to complete in order to get the result and render
    the HTML (there is no interactive user waiting for the result).

    Parameters
    ----------
    ctx
        The context dictionary containing dependencies like the logger and
        HTTP client.
    page_name
        The name of the page to run.
    scheduled_time
        The time when the page is scheduled to be run, in ISO 8601 format.
    """
    logger = ctx["logger"].bind(
        task="scheduled_page_run",
        page=page_name,
        scheduled_time=scheduled_time.isoformat(),
    )
    logger.info("Running scheduled_page_run")

    try:
        noteburst_client = NoteburstApi(
            http_client=ctx["http_client"],
        )

        async for db_session in db_session_dependency():
            page_service = await create_page_service(
                http_client=ctx["http_client"],
                logger=logger,
                db_session=db_session,
            )
            page = await page_service.get_page(page_name)
            page_execution_info = (
                await page_service.execute_page_with_defaults(page=page)
            )

            # Wait for the job to complete
            # This should be timedout by arq if the job never resolves
            while True:
                noteburst_job = page_execution_info.noteburst_job
                if not noteburst_job:
                    raise RuntimeError(
                        f"No Noteburst job found for page {page_name}"
                    )
                updated_job_result = await noteburst_client.get_job(
                    job_url=str(noteburst_job.job_url),
                )
                job_response = updated_job_result.data
                if not job_response:
                    raise RuntimeError(
                        "Failed to get Noteburst job at "
                        f"{noteburst_job.job_url}"
                    )
                if job_response.status in [
                    NoteburstJobStatus.complete,
                    NoteburstJobStatus.not_found,
                ]:
                    break

                await asyncio.sleep(15)

            if job_response.status is NoteburstJobStatus.not_found:
                raise RuntimeError(
                    "Noteburst job not found",
                )

            if job_response.status == NoteburstJobStatus.complete:
                # Job finished, so render the HTML and update the cache
                await page_service.update_nbhtml(
                    page_name=page_name,
                    parameter_values=page_execution_info.values,
                    noteburst_response=job_response,
                )

    except Exception as e:
        if "slack" in ctx:
            await ctx["slack"].post(
                SlackMessage(
                    message="Times Square worker exception.",
                    fields=[
                        SlackTextField(
                            heading="Task", text="scheduled_page_run"
                        ),
                        SlackTextField(heading="Page", text=page_name),
                        SlackTextField(
                            heading="Scheduled Time",
                            text=scheduled_time.isoformat(),
                        ),
                    ],
                    blocks=[
                        SlackCodeBlock(
                            heading="Exception",
                            code=str(e),
                        ),
                    ],
                )
            )
        raise

    return "Done"
