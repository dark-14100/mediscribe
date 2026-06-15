"""add visits.transcript_language (spoken language, for cross-lingual notes)

Revision ID: 004_add_visit_transcript_language
Revises: 003_add_visit_language
Create Date: 2026-06-15

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "004_add_visit_transcript_language"
down_revision: Union[str, None] = "003_add_visit_language"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable: unknown until Whisper detects the spoken language. When it differs
    # from `language` (the note output language) the grounding gate goes
    # cross-lingual (LLM-authoritative) instead of lexical word-overlap.
    op.add_column(
        "visits",
        sa.Column("transcript_language", sa.String(length=16), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("visits", "transcript_language")
