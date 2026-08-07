"""Add stable GitHub numeric ID columns to pages.

Revision ID: d30084ab26c8
Revises: 747a655bacf6
Create Date: 2026-08-07 15:24:42.775994+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d30084ab26c8"
down_revision: str | None = "747a655bacf6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pages",
        sa.Column("github_repository_id", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "pages", sa.Column("github_owner_id", sa.BigInteger(), nullable=True)
    )
    op.add_column(
        "pages",
        sa.Column("github_installation_id", sa.BigInteger(), nullable=True),
    )
    op.create_index(
        op.f("ix_pages_github_repository_id"),
        "pages",
        ["github_repository_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_pages_github_repository_id"), table_name="pages")
    op.drop_column("pages", "github_installation_id")
    op.drop_column("pages", "github_owner_id")
    op.drop_column("pages", "github_repository_id")
