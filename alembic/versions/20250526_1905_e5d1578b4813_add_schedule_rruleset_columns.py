"""Add schedule rruleset columns.

Revision ID: e5d1578b4813
Revises: c617718eaf6b
Create Date: 2025-05-26 19:05:37.057539+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5d1578b4813"
down_revision: str | None = "c617718eaf6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pages",
        sa.Column("schedule_rruleset", sa.UnicodeText(), nullable=True),
    )
    op.add_column(
        "pages",
        sa.Column(
            "schedule_enabled", sa.Boolean(), nullable=False, default=False
        ),
    )


def downgrade() -> None:
    op.drop_column("pages", "schedule_enabled")
    op.drop_column("pages", "schedule_rruleset")
