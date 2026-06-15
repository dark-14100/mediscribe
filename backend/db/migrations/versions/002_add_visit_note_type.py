"""add visits.note_type for multiple clinical note types

Revision ID: 002_add_visit_note_type
Revises: 001_initial_schema
Create Date: 2026-06-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "002_add_visit_note_type"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "visits",
        sa.Column(
            "note_type",
            sa.String(length=16),
            nullable=False,
            server_default="soap",
        ),
    )


def downgrade() -> None:
    op.drop_column("visits", "note_type")
