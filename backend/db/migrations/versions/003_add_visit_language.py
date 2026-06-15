"""add visits.language for multilingual notes

Revision ID: 003_add_visit_language
Revises: 002_add_visit_note_type
Create Date: 2026-06-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_add_visit_language"
down_revision: Union[str, None] = "002_add_visit_note_type"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "visits",
        sa.Column(
            "language",
            sa.String(length=16),
            nullable=False,
            server_default="en",
        ),
    )


def downgrade() -> None:
    op.drop_column("visits", "language")
