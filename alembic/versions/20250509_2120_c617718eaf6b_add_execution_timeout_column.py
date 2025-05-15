"""Add execution_timeout column.

Revision ID: c617718eaf6b
Revises: 2a3bb5a5933b
Create Date: 2025-05-09 21:20:45.660792+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c617718eaf6b"
down_revision: str | None = "2a3bb5a5933b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pages", sa.Column("execution_timeout", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("pages", "execution_timeout")
