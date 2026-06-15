"""Schemas for EHR write-back (FHIR DocumentReference export)."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class EhrExportRequest(BaseModel):
    """Body of POST /notes/ehr-export/{visit_id}."""

    # Re-file even if this visit was already exported (creates a new
    # DocumentReference). Default keeps exports idempotent.
    force: bool = False


class EhrExportResult(BaseModel):
    """Outcome of an export, also persisted into ``visit.soap_audit_trail.ehr_export``."""

    status: str = "none"  # none | filed | failed
    document_reference_id: str | None = None
    patient_fhir_id: str | None = None
    fhir_base_url: str | None = None
    exported_at: datetime | None = None
    exported_by: str | None = None
    error: str | None = None
