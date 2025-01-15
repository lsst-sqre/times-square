"""Adopt TEXT column types where useful.

In Postgres there is not functional or performance difference between VARCHAR
and TEXT columns. Therefore we're removing arbitrary constraints on many
string columns by migrating to TEXT column types.

Revision ID: 2a3bb5a5933b
Revises: 487195933fee
Create Date: 2025-01-14 16:20:45.553562+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2a3bb5a5933b"
down_revision: str | None = "487195933fee"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "pages",
        "uploader_username",
        existing_type=sa.VARCHAR(length=64),
        type_=sa.UnicodeText(),
        existing_nullable=True,
    )
    op.alter_column(
        "pages",
        "github_owner",
        existing_type=sa.VARCHAR(length=255),
        type_=sa.UnicodeText(),
        existing_nullable=True,
    )
    op.alter_column(
        "pages",
        "github_repo",
        existing_type=sa.VARCHAR(length=255),
        type_=sa.UnicodeText(),
        existing_nullable=True,
    )
    op.alter_column(
        "pages",
        "repository_path_prefix",
        existing_type=sa.VARCHAR(length=2048),
        type_=sa.UnicodeText(),
        existing_nullable=True,
    )
    op.alter_column(
        "pages",
        "repository_display_path_prefix",
        existing_type=sa.VARCHAR(length=2048),
        type_=sa.UnicodeText(),
        existing_nullable=True,
    )
    op.alter_column(
        "pages",
        "repository_path_stem",
        existing_type=sa.VARCHAR(length=255),
        type_=sa.UnicodeText(),
        existing_nullable=True,
    )
    op.alter_column(
        "pages",
        "repository_source_extension",
        existing_type=sa.VARCHAR(length=255),
        type_=sa.UnicodeText(),
        existing_nullable=True,
    )
    op.alter_column(
        "pages",
        "repository_sidecar_extension",
        existing_type=sa.VARCHAR(length=255),
        type_=sa.UnicodeText(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "pages",
        "repository_sidecar_extension",
        existing_type=sa.UnicodeText(),
        type_=sa.VARCHAR(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        "pages",
        "repository_source_extension",
        existing_type=sa.UnicodeText(),
        type_=sa.VARCHAR(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        "pages",
        "repository_path_stem",
        existing_type=sa.UnicodeText(),
        type_=sa.VARCHAR(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        "pages",
        "repository_display_path_prefix",
        existing_type=sa.UnicodeText(),
        type_=sa.VARCHAR(length=2048),
        existing_nullable=True,
    )
    op.alter_column(
        "pages",
        "repository_path_prefix",
        existing_type=sa.UnicodeText(),
        type_=sa.VARCHAR(length=2048),
        existing_nullable=True,
    )
    op.alter_column(
        "pages",
        "github_repo",
        existing_type=sa.UnicodeText(),
        type_=sa.VARCHAR(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        "pages",
        "github_owner",
        existing_type=sa.UnicodeText(),
        type_=sa.VARCHAR(length=255),
        existing_nullable=True,
    )
    op.alter_column(
        "pages",
        "uploader_username",
        existing_type=sa.UnicodeText(),
        type_=sa.VARCHAR(length=64),
        existing_nullable=True,
    )
