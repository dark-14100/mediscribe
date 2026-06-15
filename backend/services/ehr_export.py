"""EHR write-back — file a signed note into a FHIR server as a DocumentReference.

Phase A targets an open FHIR R4 sandbox (no auth, e.g. hapi.fhir.org/baseR4),
chosen entirely via ``EHR_*`` settings. The same mapping + POST flow works against
a real EHR (Epic) once ``EHR_AUTH_MODE=smart_backend`` is implemented (Phase B).

The flow:
  1. resolve auth headers (none for the open sandbox)
  2. search-or-create a FHIR Patient keyed by our patient UUID identifier
  3. build a DocumentReference (LOINC type per note template, note text as a
     base64 text/plain attachment)
  4. POST it and return the created resource id

Unlike LLM calls, the EHR is the trusted system of record, so we send the REAL
(re-identified) note here — de-identification deliberately does not apply.
"""
from __future__ import annotations

import base64
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from core.config import settings
from core.note_templates import loinc, section_keys, section_labels
from services.groq_retry import call_with_retries

logger = logging.getLogger("medscribe.ehr")

PATIENT_IDENTIFIER_SYSTEM = "urn:mediscribe:patient-id"
LOINC_SYSTEM = "http://loinc.org"
US_CORE_CATEGORY_SYSTEM = (
    "http://hl7.org/fhir/us/core/CodeSystem/us-core-documentreference-category"
)
_FHIR_GENDERS = {"male", "female", "other", "unknown"}


class EhrExportError(RuntimeError):
    """Raised when an export cannot complete; carries a user-safe message."""


def _require_config() -> str:
    base = (settings.EHR_FHIR_BASE_URL or "").strip().rstrip("/")
    if not base:
        raise EhrExportError("EHR_FHIR_BASE_URL is not configured on the server.")
    return base


def _auth_headers() -> dict[str, str]:
    mode = (settings.EHR_AUTH_MODE or "none").strip().lower()
    if mode == "none":
        return {}
    if mode == "smart_backend":
        # SMART Backend Services (signed-JWT client-credentials) lands in Phase B.
        raise EhrExportError(
            "EHR_AUTH_MODE=smart_backend is not yet implemented (Phase B)."
        )
    raise EhrExportError(f"Unknown EHR_AUTH_MODE: {settings.EHR_AUTH_MODE!r}")


def _fhir_gender(gender: str | None) -> str:
    g = (gender or "").strip().lower()
    return g if g in _FHIR_GENDERS else "unknown"


def _human_name(full_name: str | None) -> dict[str, Any]:
    text = (full_name or "").strip() or "Unknown Patient"
    parts = text.split()
    if len(parts) >= 2:
        return {"use": "official", "family": parts[-1], "given": parts[:-1], "text": text}
    return {"use": "official", "text": text}


def assemble_note_text(
    note_type: str, sections: dict[str, Any], language: str | None = None
) -> str:
    """Render the note's sections (in template order) into labelled plain text.

    When ``language`` has localized section labels, the headers are translated to
    match the note body (English headers otherwise)."""
    labels = section_labels(note_type, language)
    blocks: list[str] = []
    for key in section_keys(note_type):
        field = sections.get(key) or {}
        text = str((field or {}).get("text", "") or "").strip()
        if not text:
            continue
        blocks.append(f"{labels.get(key, key)}:\n{text}")
    return "\n\n".join(blocks).strip()


def build_document_reference(
    *,
    note_type: str,
    sections: dict[str, Any],
    patient_reference: str,
    doctor_name: str | None,
    signed_at: datetime | None,
    title: str | None = None,
    language: str | None = None,
) -> dict[str, Any]:
    """Map a signed note to a FHIR R4 DocumentReference (US Core clinical-note)."""
    code, display = loinc(note_type)
    when = (signed_at or datetime.now(timezone.utc)).astimezone(timezone.utc)
    when_iso = when.isoformat()
    note_text = assemble_note_text(note_type, sections, language)
    encoded = base64.b64encode(note_text.encode("utf-8")).decode("ascii")
    doc_title = title or f"{display} — {when.date().isoformat()}"
    attachment: dict[str, Any] = {
        "contentType": "text/plain",
        "data": encoded,
        "title": doc_title,
        "creation": when_iso,
    }
    if language:
        attachment["language"] = language

    doc: dict[str, Any] = {
        "resourceType": "DocumentReference",
        "status": "current",
        "docStatus": "final",
        "type": {
            "coding": [{"system": LOINC_SYSTEM, "code": code, "display": display}],
            "text": display,
        },
        "category": [
            {
                "coding": [
                    {
                        "system": US_CORE_CATEGORY_SYSTEM,
                        "code": "clinical-note",
                        "display": "Clinical Note",
                    }
                ]
            }
        ],
        "subject": {"reference": patient_reference},
        "date": when_iso,
        "content": [{"attachment": attachment}],
    }
    if doctor_name:
        doc["author"] = [{"display": doctor_name}]
    return doc


async def _fhir_get(base: str, path: str, headers: dict[str, str]) -> httpx.Response:
    async def _request() -> httpx.Response:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{base}/{path.lstrip('/')}",
                headers={"Accept": "application/fhir+json", **headers},
                timeout=settings.EHR_REQUEST_TIMEOUT_SECONDS,
            )
        if response.status_code >= 400:
            response.raise_for_status()
        return response

    return await call_with_retries(_request, label="ehr-get")


async def _fhir_post(
    base: str, path: str, body: dict[str, Any], headers: dict[str, str]
) -> httpx.Response:
    async def _request() -> httpx.Response:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{base}/{path.lstrip('/')}",
                headers={
                    "Accept": "application/fhir+json",
                    "Content-Type": "application/fhir+json",
                    **headers,
                },
                json=body,
                timeout=settings.EHR_REQUEST_TIMEOUT_SECONDS,
            )
        if response.status_code >= 400:
            response.raise_for_status()
        return response

    return await call_with_retries(_request, label="ehr-post")


async def _search_or_create_patient(
    base: str, headers: dict[str, str], patient: Any
) -> str:
    """Return a ``Patient/{id}`` reference, creating the FHIR Patient if absent."""
    identifier_value = str(getattr(patient, "id", "") or "")
    query = f"Patient?identifier={PATIENT_IDENTIFIER_SYSTEM}|{identifier_value}"
    try:
        resp = await _fhir_get(base, query, headers)
        bundle = resp.json()
        for entry in bundle.get("entry") or []:
            resource = entry.get("resource") or {}
            rid = resource.get("id")
            if rid:
                return f"Patient/{rid}"
    except Exception:  # noqa: BLE001 — fall through to create
        logger.warning("[ehr] patient search failed; will create", exc_info=True)

    dob = getattr(patient, "dob", None)
    body: dict[str, Any] = {
        "resourceType": "Patient",
        "identifier": [
            {"system": PATIENT_IDENTIFIER_SYSTEM, "value": identifier_value}
        ],
        "name": [_human_name(getattr(patient, "full_name", None))],
        "gender": _fhir_gender(getattr(patient, "gender", None)),
    }
    if dob is not None:
        body["birthDate"] = dob.isoformat() if hasattr(dob, "isoformat") else str(dob)

    resp = await _fhir_post(base, "Patient", body, headers)
    created = resp.json()
    rid = created.get("id")
    if not rid:
        raise EhrExportError("FHIR server did not return a Patient id.")
    return f"Patient/{rid}"


def _resource_id_from_response(resp: httpx.Response, resource_type: str) -> str:
    """Resolve ``{ResourceType}/{id}`` from the response body or Location header."""
    try:
        body = resp.json()
        rid = body.get("id")
        if rid:
            return f"{resource_type}/{rid}"
    except Exception:  # noqa: BLE001 — fall back to Location
        pass
    location = resp.headers.get("Location") or resp.headers.get("Content-Location") or ""
    if resource_type in location:
        tail = location.split(resource_type, 1)[1].strip("/").split("/")
        if tail and tail[0]:
            return f"{resource_type}/{tail[0]}"
    raise EhrExportError("FHIR server did not return a DocumentReference id.")


async def export_note(
    *,
    note_type: str,
    sections: dict[str, Any],
    patient: Any,
    doctor_name: str | None,
    signed_at: datetime | None,
    language: str | None = None,
) -> dict[str, Any]:
    """File a signed note into the configured FHIR server.

    Returns ``{document_reference_id, patient_fhir_id, fhir_base_url}`` on success
    and raises ``EhrExportError`` (user-safe message) on failure.
    """
    if not assemble_note_text(note_type, sections, language):
        raise EhrExportError("The note is empty; nothing to file.")

    base = _require_config()
    headers = _auth_headers()

    patient_reference = await _search_or_create_patient(base, headers, patient)
    doc = build_document_reference(
        note_type=note_type,
        sections=sections,
        patient_reference=patient_reference,
        doctor_name=doctor_name,
        signed_at=signed_at,
        language=language,
    )
    resp = await _fhir_post(base, "DocumentReference", doc, headers)
    doc_id = _resource_id_from_response(resp, "DocumentReference")

    logger.info(
        "[ehr] filed note note_type=%s doc=%s subject=%s base=%s",
        note_type,
        doc_id,
        patient_reference,
        base,
    )
    return {
        "document_reference_id": doc_id,
        "patient_fhir_id": patient_reference,
        "fhir_base_url": base,
    }
