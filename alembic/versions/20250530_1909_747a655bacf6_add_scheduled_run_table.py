"""Add scheduled_run table.

Revision ID: 747a655bacf6
Revises: e5d1578b4813
Create Date: 2025-05-30 19:09:24.669170+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "747a655bacf6"
down_revision: str | None = "e5d1578b4813"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduled_run",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("page_name", sa.Unicode(length=32), nullable=False),
        sa.Column(
            "scheduled_time", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("job_id", sa.UnicodeText(), nullable=False),
        sa.ForeignKeyConstraint(
            ["page_name"],
            ["pages.name"],
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "page_name", "scheduled_time", name="unique_page_schedule"
        ),
    )


def downgrade() -> None:
    op.drop_table("scheduled_run")
