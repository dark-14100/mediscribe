"""initial schema: users, patients, visits, visit_embeddings + pgvector

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-05-17

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ---- pgvector extension (Supabase Postgres requires this) ----
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ---- users ----
    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False, unique=True),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column(
            "role", sa.String(length=32), nullable=False, server_default="doctor"
        ),
        sa.Column(
            "session_count_today",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
        sa.Column("last_session_date", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    # ---- patients ----
    op.create_table(
        "patients",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("dob", sa.Date(), nullable=False),
        sa.Column("gender", sa.String(length=32), nullable=False),
        sa.Column(
            "doctor_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "allergies",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "active_medications",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_patients_doctor_id", "patients", ["doctor_id"])

    # ---- visits ----
    op.create_table(
        "visits",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "patient_id",
            sa.Uuid(),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "doctor_id",
            sa.Uuid(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "visit_date",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("raw_transcript", sa.Text(), nullable=True),
        sa.Column("audio_url", sa.String(length=1024), nullable=True),
        sa.Column(
            "soap_note", postgresql.JSONB(), nullable=False, server_default="{}"
        ),
        sa.Column(
            "soap_audit_trail",
            postgresql.JSONB(),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "anomalies", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column(
            "differentials",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column("drift_flag", postgresql.JSONB(), nullable=True),
        sa.Column("compliance_status", sa.String(length=16), nullable=True),
        sa.Column(
            "compliance_notes",
            postgresql.JSONB(),
            nullable=False,
            server_default="[]",
        ),
        sa.Column(
            "bias_flags", postgresql.JSONB(), nullable=False, server_default="[]"
        ),
        sa.Column("trajectory_score", sa.Float(), nullable=True),
        sa.Column("trajectory_direction", sa.String(length=16), nullable=True),
        sa.Column(
            "trajectory_watch_zones",
            postgresql.ARRAY(sa.String()),
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "is_signed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("signed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_visits_patient_id", "visits", ["patient_id"])
    op.create_index("ix_visits_doctor_id", "visits", ["doctor_id"])

    # ---- visit_embeddings ----
    op.create_table(
        "visit_embeddings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "visit_id",
            sa.Uuid(),
            sa.ForeignKey("visits.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "patient_id",
            sa.Uuid(),
            sa.ForeignKey("patients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("full_note_embedding", Vector(384), nullable=False),
        sa.Column("patient_speech_embedding", Vector(384), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_visit_embeddings_patient_id", "visit_embeddings", ["patient_id"]
    )

    # ivfflat indexes for cosine similarity (lists=100 is fine for hackathon scale)
    op.execute(
        "CREATE INDEX ix_visit_embeddings_full_note "
        "ON visit_embeddings USING ivfflat (full_note_embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )
    op.execute(
        "CREATE INDEX ix_visit_embeddings_patient_speech "
        "ON visit_embeddings USING ivfflat (patient_speech_embedding vector_cosine_ops) "
        "WITH (lists = 100)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_visit_embeddings_patient_speech")
    op.execute("DROP INDEX IF EXISTS ix_visit_embeddings_full_note")
    op.drop_index("ix_visit_embeddings_patient_id", table_name="visit_embeddings")
    op.drop_table("visit_embeddings")
    op.drop_index("ix_visits_doctor_id", table_name="visits")
    op.drop_index("ix_visits_patient_id", table_name="visits")
    op.drop_table("visits")
    op.drop_index("ix_patients_doctor_id", table_name="patients")
    op.drop_table("patients")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
    op.execute("DROP EXTENSION IF EXISTS vector")
