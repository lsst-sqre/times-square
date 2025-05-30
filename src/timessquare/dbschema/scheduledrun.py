"""The ScheduledRun database model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Unicode,
    UnicodeText,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base
from .page import SqlPage

__all__ = ["SqlScheduledRun"]


class SqlScheduledRun(Base):
    """A scheduled execution of a page."""

    __tablename__ = "scheduled_run"

    __table_args__ = (
        UniqueConstraint(
            "page_name", "scheduled_time", name="unique_page_schedule"
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    page_name: Mapped[str] = mapped_column(
        Unicode(32), ForeignKey("pages.name"), nullable=False
    )

    scheduled_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    job_id: Mapped[str] = mapped_column(UnicodeText, nullable=False)

    # Relationships
    page: Mapped[SqlPage] = relationship("SqlPage")
