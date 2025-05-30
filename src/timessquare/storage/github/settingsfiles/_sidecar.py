"""Models for Times Square settings files in a GitHub repository."""

from __future__ import annotations

from typing import Annotated

import dateutil
import yaml
from pydantic import BaseModel, Field
from safir.pydantic import HumanTimedelta

from timessquare.domain.page import PersonModel
from timessquare.domain.pageparameters import PageParameters
from timessquare.domain.schedule import ExecutionSchedule

from ._parameterschema import ParameterSchemaModel
from ._person import SidecarPersonModel
from ._schedule import ScheduleRule

__all__ = [
    "NotebookSidecarFile",
]


class NotebookSidecarFile(BaseModel):
    """A Pydantic model for a ``{notebook}.yaml`` notebook settings sidecar
    file.
    """

    authors: Annotated[
        list[SidecarPersonModel],
        Field(title="Authors of the notebook", default_factory=list),
    ]

    title: Annotated[
        str | None,
        Field(
            title="Title of a notebook (default is to use the filename)",
        ),
    ] = None

    description: Annotated[
        str | None,
        Field(
            title="Description of a notebook",
            description="Can be markdown-formatted.",
        ),
    ] = None

    enabled: Annotated[
        bool,
        Field(
            title=(
                "Toggle for activating a notebook's inclusion in Times Square"
            )
        ),
    ] = True

    cache_ttl: Annotated[
        int | None, Field(title="Lifetime (seconds) of notebook page renders")
    ] = None

    tags: Annotated[
        list[str],
        Field(
            title="Tag keywords associated with the notebook",
            default_factory=list,
        ),
    ]

    timeout: Annotated[
        HumanTimedelta | None,
        Field(
            title="Timeout for notebook execution",
            description="If not set, the default execution timeout is used.",
        ),
    ] = None

    parameters: Annotated[
        dict[str, ParameterSchemaModel],
        Field(title="Parameters and their schemas", default_factory=dict),
    ]

    schedule: Annotated[
        list[ScheduleRule],
        Field(
            title="Schedule rules for the notebook",
            description=(
                "A list of schedule rules that determine when the notebook "
                "should be executed. If empty, the the notebook is only "
                "executed on-demand. Use a schedule to have a notebook "
                "executed automatically when data for a report is ready."
            ),
            default_factory=list,
        ),
    ]

    schedule_enabled: Annotated[
        bool,
        Field(
            title="Toggle for enabling the schedule",
            description=(
                "If set to `False`, the notebook is not executed "
                "automatically, even if it has a schedule. This is useful "
                "if you want to temporarily disable the schedule without "
                "removing the schedule rules."
            ),
        ),
    ] = True

    @classmethod
    def parse_yaml(cls, content: str) -> NotebookSidecarFile:
        """Create a NotebookSidecarFile from the YAML content."""
        return cls.model_validate(yaml.safe_load(content))

    def export_parameters(self) -> PageParameters:
        """Export the `parameters` attribute to `PageParameterSchema` used
        by the PageModel.
        """
        return PageParameters(
            {k: v.to_parameter_schema(k) for k, v in self.parameters.items()}
        )

    def export_authors(self) -> list[PersonModel]:
        return [a.to_person_model() for a in self.authors]

    @property
    def execution_schedule(self) -> ExecutionSchedule | None:
        """Return the execution schedule for this notebook."""
        if len(self.schedule) == 0:
            return None

        rset = dateutil.rrule.rruleset(cache=True)
        for rule in self.schedule:
            if rule.date is not None:
                if rule.exclude:
                    rset.exdate(rule.to_datetime())
                else:
                    rset.rdate(rule.to_datetime())
            elif rule.exclude:
                rset.exrule(rule.to_rrule())
            else:
                rset.rrule(rule.to_rrule())

        return ExecutionSchedule(
            rset,
            enabled=self.schedule_enabled,
        )
