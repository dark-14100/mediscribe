"""Dialect-aware column type factories.

Postgres-specific column types (JSONB, ARRAY) degrade to plain JSON when the
engine dialect is SQLite. This lets the same ORM models run against
Supabase Postgres in production and against an in-memory SQLite in tests
without any runtime if-Postgres branching.

ALWAYS call these as functions (not class attributes) so each column gets a
fresh TypeEngine instance — SQLAlchemy caches some state on the instance.
"""
from sqlalchemy import JSON, String
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.types import TypeEngine


def jsonb_type() -> TypeEngine:
    """JSONB on Postgres, JSON on SQLite."""
    return JSONB().with_variant(JSON(), "sqlite")


def array_str_type() -> TypeEngine:
    """ARRAY(String) on Postgres, JSON on SQLite."""
    return ARRAY(String).with_variant(JSON(), "sqlite")
