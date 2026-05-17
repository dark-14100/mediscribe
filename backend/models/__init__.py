"""ORM model registry.

Importing this package guarantees every ORM model is registered with
``Base.metadata`` — required for Alembic autogeneration and for tests
that create the schema directly from metadata.
"""
from models.embedding import VisitEmbedding
from models.patient import Patient
from models.user import User
from models.visit import Visit

__all__ = ["User", "Patient", "Visit", "VisitEmbedding"]
