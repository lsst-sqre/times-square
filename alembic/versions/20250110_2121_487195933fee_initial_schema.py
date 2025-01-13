"""Initial schema.

Revision ID: 487195933fee
Revises:
Create Date: 2025-01-10 21:21:26.706763+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "487195933fee"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pages",
        sa.Column("name", sa.Unicode(length=32), nullable=False),
        sa.Column("ipynb", sa.UnicodeText(), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("title", sa.UnicodeText(), nullable=False),
        sa.Column("date_added", sa.DateTime(), nullable=False),
        sa.Column("authors", sa.JSON(), nullable=False),
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("uploader_username", sa.Unicode(length=64), nullable=True),
        sa.Column("date_deleted", sa.DateTime(), nullable=True),
        sa.Column("description", sa.UnicodeText(), nullable=True),
        sa.Column("cache_ttl", sa.Integer(), nullable=True),
        sa.Column("github_owner", sa.Unicode(length=255), nullable=True),
        sa.Column("github_repo", sa.Unicode(length=255), nullable=True),
        sa.Column("github_commit", sa.Unicode(length=40), nullable=True),
        sa.Column(
            "repository_path_prefix", sa.Unicode(length=2048), nullable=True
        ),
        sa.Column(
            "repository_display_path_prefix",
            sa.Unicode(length=2048),
            nullable=True,
        ),
        sa.Column(
            "repository_path_stem", sa.Unicode(length=255), nullable=True
        ),
        sa.Column(
            "repository_source_extension",
            sa.Unicode(length=255),
            nullable=True,
        ),
        sa.Column(
            "repository_sidecar_extension",
            sa.Unicode(length=255),
            nullable=True,
        ),
        sa.Column(
            "repository_source_sha", sa.Unicode(length=40), nullable=True
        ),
        sa.Column(
            "repository_sidecar_sha", sa.Unicode(length=40), nullable=True
        ),
        sa.PrimaryKeyConstraint("name"),
    )


def downgrade() -> None:
    op.drop_table("pages")
