"""Pipeline orchestration: transcribe, run, and SSE stream.

This module is the *backend* slice of the pipeline. It owns:
* HTTP wiring (request validation, auth, persistence).
* Asynchronous orchestration order (steps 2-7 as specified in the PRD).
* The SSE stream that pushes per-step events to the frontend.

It does NOT own:
* SOAP generation, transcription, embeddings, history retrieval, anomaly /
  differential / drift / compliance / bias services — those live in
  ``services/*.py`` files owned by the AI team.

The AI services are looked up dynamically at call time. If the service file
is empty (Phase-3-style scaffolding) the route returns HTTP 503 with a clear
message rather than 500-ing on a missing attribute.
"""
import asyncio
import importlib
import json
import logging
from typing import Annotated, Any, Callable
from uuid import UUID

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Path,
    Query,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_current_user_sse, require_doctor
from core.constants import (
    EVENT_ANOMALIES_READY,
    EVENT_BIAS_READY,
    EVENT_CODING_READY,
    EVENT_COMPLIANCE_READY,
    EVENT_DIFFERENTIALS_READY,
    EVENT_DRIFT_READY,
    EVENT_ERROR,
    EVENT_GROUNDING_READY,
    EVENT_PIPELINE_DONE,
    EVENT_SOAP_READY,
    EVENT_TRAJECTORY_READY,
)
from db.session import get_db
from models.patient import Patient
from models.user import User
from models.visit import Visit
from schemas.pipeline import (
    AudioUrlResponse,
    ClinicalNote,
    CodingResult,
    DeidReport,
    GroundingResult,
    PartialTranscriptResponse,
    PipelinePayload,
    PipelineRunRequest,
    SOAPNote,
    TrajectoryResult,
    TranscribeResponse,
)
from core.languages import canonical_language, normalize_language
from core.note_templates import normalize_note_type
from services.deid import count_residual, reidentify
from core.audit import log_phi_access
from core.config import settings
from core.ratelimit import limiter
from services.event_bus import EventBus, get_event_bus
from services.storage import StorageClient, get_storage

log = logging.getLogger("medscribe.pipeline")
router = APIRouter(prefix="/pipeline", tags=["pipeline"])

# Audio MIME types we accept for transcription. Browsers typically send
# audio/webm (MediaRecorder); the rest cover common manual uploads.
_ALLOWED_AUDIO_TYPES: frozenset[str] = frozenset(
    {
        "audio/webm",
        "audio/ogg",
        "audio/wav",
        "audio/x-wav",
        "audio/wave",
        "audio/mpeg",
        "audio/mp3",
        "audio/mp4",
        "audio/m4a",
        "audio/x-m4a",
        "audio/aac",
        "audio/flac",
        "application/octet-stream",
    }
)


def _is_allowed_audio_type(content_type: str) -> bool:
    return content_type in _ALLOWED_AUDIO_TYPES


# ---------------------------------------------------------------------------
# AI service resolution
# ---------------------------------------------------------------------------
# The AI team owns these modules. Until they ship, looking up the expected
# function returns None and the route gracefully 503s.


def _resolve(module_path: str, func_name: str) -> Callable[..., Any] | None:
    """Return the requested callable, or None if missing/unimplemented."""
    try:
        module = importlib.import_module(module_path)
    except ImportError as exc:
        log.debug("[pipeline] %s not importable: %s", module_path, exc)
        return None
    func = getattr(module, func_name, None)
    return func if callable(func) else None


def _require(func: Callable[..., Any] | None, label: str) -> Callable[..., Any]:
    if func is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"{label} is not yet implemented by the AI team.",
        )
    return func


async def _maybe_call(
    func: Callable[..., Any] | None,
    *args: Any,
    default: Any,
    label: str,
    degraded: list[str] | None = None,
    **kwargs: Any,
) -> Any:
    """Call an AI service and degrade gracefully on any failure.

    If the service module is missing OR the call raises at runtime (e.g. the
    Groq API is down after retries), we log it, record ``label`` in
    ``degraded`` so the caller can surface a partial-result warning, and return
    ``default`` instead of letting the exception tear down the whole pipeline.
    """
    if func is None:
        log.info("[pipeline] %s unavailable — returning default", label)
        if degraded is not None:
            degraded.append(label)
        return default
    try:
        result = func(*args, **kwargs)
        if asyncio.iscoroutine(result):
            result = await result
        return result
    except Exception:  # noqa: BLE001 — degrade rather than crash the pipeline
        log.exception("[pipeline] %s failed — degrading to default", label)
        if degraded is not None:
            degraded.append(label)
        return default


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _load_my_visit(visit_id: UUID, user: User, db: AsyncSession) -> Visit:
    visit = await db.scalar(
        select(Visit).where(Visit.id == visit_id, Visit.doctor_id == user.id)
    )
    if visit is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Visit not found")
    return visit


async def _is_first_visit(patient_id: UUID, db: AsyncSession) -> bool:
    """True when this patient has only one visit on record (drives new vs
    established E&M coding). Best-effort: any error treats them as established."""
    try:
        count = await db.scalar(
            select(func.count()).select_from(Visit).where(Visit.patient_id == patient_id)
        )
        return (count or 0) <= 1
    except Exception:  # noqa: BLE001 — coding is advisory; never break the run
        log.warning("[pipeline] first-visit check failed for patient %s", patient_id)
        return False


def _sse_format(event_name: str, data: dict[str, Any]) -> str:
    """Render a single SSE message frame."""
    return f"event: {event_name}\ndata: {json.dumps(data, default=str)}\n\n"


def _coerce_clinical_note(raw: Any, note_type: str) -> ClinicalNote:
    """Build a ClinicalNote from a generator's output (flat sections dict),
    a SOAPNote, or None. Tolerant: unparseable input yields an empty note."""
    if isinstance(raw, ClinicalNote):
        return raw
    if isinstance(raw, SOAPNote):
        note = ClinicalNote.from_soap(raw)
        note.note_type = note_type
        return note
    if isinstance(raw, dict):
        try:
            return ClinicalNote.from_sections(note_type, raw)
        except Exception:  # noqa: BLE001 — degrade to an empty note
            log.exception("[pipeline] note generator returned unparseable output")
    return ClinicalNote(note_type=note_type)


def _serialise(value: Any) -> Any:
    """Pydantic model / list-of-models → JSON-safe dict, otherwise pass-through."""
    if value is None:
        return None
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, list):
        return [_serialise(v) for v in value]
    return value


def _as_json_list(value: Any) -> list[Any]:
    """Persist only list-shaped JSONB; never write ``{}`` for list columns."""
    serialized = _serialise(value)
    if serialized is None:
        return []
    if isinstance(serialized, list):
        return serialized
    if isinstance(serialized, dict):
        return []
    return [serialized]


def _as_str_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, dict):
        return []
    return [str(value)]


# ---------------------------------------------------------------------------
# POST /pipeline/transcribe
# ---------------------------------------------------------------------------


@router.post("/transcribe", response_model=TranscribeResponse)
@limiter.limit(settings.RATE_LIMIT_PIPELINE)
async def transcribe(
    request: Request,
    user: Annotated[User, Depends(require_doctor)],
    db: Annotated[AsyncSession, Depends(get_db)],
    storage: Annotated[StorageClient, Depends(get_storage)],
    audio: UploadFile = File(...),
    visit_id: Annotated[UUID | None, Query()] = None,
) -> TranscribeResponse:
    """Step 1 of the pipeline.

    Reads the uploaded audio blob, calls the AI team's ``transcription.transcribe``
    service to get a diarised transcript, and (asynchronously) queues a B2
    upload that will populate ``visits.audio_url`` once complete.
    """
    content_type = (audio.content_type or "").split(";")[0].strip().lower()
    if content_type and not _is_allowed_audio_type(content_type):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported audio format",
        )

    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty audio upload")
    if len(audio_bytes) > settings.MAX_AUDIO_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=(
                "Audio upload exceeds the maximum allowed size "
                f"({settings.MAX_AUDIO_UPLOAD_BYTES // (1024 * 1024)} MB)."
            ),
        )

    # Confirm caller owns the visit (if a visit_id was supplied).
    visit: Visit | None = None
    if visit_id is not None:
        visit = await _load_my_visit(visit_id, user, db)

    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GROQ_API_KEY is not configured on the server.",
        )

    # Prefer transcribe_detect (returns Whisper's detected spoken language too)
    # and fall back to the legacy transcribe (lines only) for back-compat/tests.
    detect_fn = _resolve("services.transcription", "transcribe_detect")
    transcribe_fn = detect_fn or _require(
        _resolve("services.transcription", "transcribe"),
        "Transcription service",
    )
    # Optional ASR language hint: when we know the visit's note language and the
    # hint is enabled, nudge Whisper rather than relying on pure auto-detect.
    lang_hint: str | None = None
    if visit is not None and settings.WHISPER_LANGUAGE_HINT:
        lang_hint = normalize_language(getattr(visit, "language", None))
    detected_language: str | None = None
    try:
        result = await transcribe_fn(audio_bytes, language=lang_hint)
        if detect_fn is not None:
            transcript, detected_language = result
        else:
            transcript = result
    except Exception as exc:
        # Log the upstream detail server-side; return a generic message so we
        # don't leak provider/internal error text to the client.
        log.exception("[pipeline] transcription failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail="Transcription failed. Please try again.",
        ) from exc

    if not transcript:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No speech detected in the recording. Try speaking longer or check your microphone.",
        )

    # Archive audio to object storage in-process. We deliberately do NOT route
    # raw audio (PHI) through the Celery/Redis broker, where it would sit
    # base64-encoded in an unencrypted queue. Archiving failures must not fail
    # the transcription, so we degrade to audio_upload_queued=False instead.
    # Persist the detected spoken language so /run can decide cross-lingual
    # grounding (note language != spoken language). Best-effort; never fatal.
    if visit is not None and detected_language:
        try:
            visit.transcript_language = canonical_language(detected_language)
            await db.commit()
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            log.warning(
                "[pipeline] persisting transcript_language failed visit_id=%s: %s",
                visit.id,
                exc,
            )

    audio_upload_queued = False
    if visit is not None:
        try:
            url = await storage.upload_audio(
                audio_bytes, str(visit.id), audio.content_type or "audio/webm"
            )
            visit.audio_url = url
            await db.commit()
            audio_upload_queued = True
        except Exception as exc:  # noqa: BLE001
            await db.rollback()
            log.warning(
                "[pipeline] audio archival failed visit_id=%s: %s", visit.id, exc
            )

    return TranscribeResponse(
        visit_id=visit_id,
        transcript=_serialise(transcript) or [],
        audio_upload_queued=audio_upload_queued,
    )


@router.post("/transcribe-chunk", response_model=PartialTranscriptResponse)
@limiter.limit(settings.RATE_LIMIT_PIPELINE)
async def transcribe_chunk(
    request: Request,
    user: Annotated[User, Depends(require_doctor)],
    audio: UploadFile = File(...),
) -> PartialTranscriptResponse:
    """Near-live preview transcription.

    Accepts the cumulative audio captured so far while the doctor is still
    recording and returns its plain text (no diarization, no storage). This is a
    best-effort convenience so the transcript appears to form in real time; the
    authoritative diarized transcript is still produced by ``/transcribe`` on the
    final blob. Any failure degrades to an empty preview rather than an error so
    it never disrupts an in-progress recording.
    """
    content_type = (audio.content_type or "").split(";")[0].strip().lower()
    if content_type and not _is_allowed_audio_type(content_type):
        raise HTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Unsupported audio format",
        )

    audio_bytes = await audio.read()
    if not audio_bytes:
        return PartialTranscriptResponse(text="")
    if len(audio_bytes) > settings.MAX_AUDIO_UPLOAD_BYTES:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="Audio upload exceeds the maximum allowed size.",
        )

    if not settings.GROQ_API_KEY:
        return PartialTranscriptResponse(text="")

    partial_fn = _resolve("services.transcription", "transcribe_partial")
    if partial_fn is None:
        return PartialTranscriptResponse(text="")
    try:
        text = await partial_fn(audio_bytes)
    except Exception:  # noqa: BLE001
        log.warning("[pipeline] partial transcription failed", exc_info=True)
        return PartialTranscriptResponse(text="")

    return PartialTranscriptResponse(text=text or "")


# ---------------------------------------------------------------------------
# GET /pipeline/stream/{visit_id}
# ---------------------------------------------------------------------------


@router.get("/stream/{visit_id}")
async def stream(
    visit_id: UUID,
    user: Annotated[User, Depends(get_current_user_sse)],
    db: Annotated[AsyncSession, Depends(get_db)],
    bus: Annotated[EventBus, Depends(get_event_bus)],
) -> StreamingResponse:
    """SSE endpoint. Client connects here BEFORE calling /pipeline/run."""
    # Auth + ownership check.
    await _load_my_visit(visit_id, user, db)

    async def event_stream():
        # Initial comment frame so the client knows the stream is open.
        yield ": stream open\n\n"
        async for event in bus.subscribe(str(visit_id)):
            yield _sse_format(event.name, event.data)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable nginx buffering if behind a proxy
        },
    )


# ---------------------------------------------------------------------------
# POST /pipeline/run — the orchestrator
# ---------------------------------------------------------------------------


async def _run_pipeline(
    payload: PipelineRunRequest,
    visit: Visit,
    patient: Patient,
    db: AsyncSession,
    bus: EventBus,
) -> PipelinePayload:
    """Steps 2-7 of the pipeline.

    Each step publishes its SSE event the moment its data is ready. The final
    DB write happens after every step has completed.
    """
    visit_id_str = str(visit.id)
    # Steps that failed at runtime and fell back to a default. Surfaced to the
    # client so the doctor knows the note is partial rather than complete.
    degraded_steps: list[str] = []

    # Resolve the note type: a request override wins, else the visit's stored
    # type, else the default. Persist it so save/sign/reload agree.
    note_type = normalize_note_type(
        payload.note_type or getattr(visit, "note_type", None)
    )
    visit.note_type = note_type

    # Resolve the note language the same way: request override, else the visit's
    # stored language, else the default. The note is generated in this language.
    language = normalize_language(
        payload.language
        or getattr(visit, "language", None)
        or settings.DEFAULT_NOTE_LANGUAGE
    )
    visit.language = language

    # The spoken language (Whisper-detected at /transcribe). When it differs from
    # the note language the grounding gate goes cross-lingual (LLM-authoritative).
    transcript_language = (
        canonical_language(getattr(visit, "transcript_language", None)) or language
    )

    # --- Step 1.5: De-identify before any LLM sees the text --------------
    # Replace PHI with reversible placeholders; the whole LLM portion runs on
    # the clean copy, and every output is re-identified at the boundaries.
    deid_mode = settings.DEID_MODE.strip().lower()
    deid: Any = None
    if deid_mode != "off":
        deid_fn = _resolve("services.deid", "deidentify_transcript")
        deid = await _maybe_call(
            deid_fn,
            payload.transcript,
            patient,
            transcript_language,
            default=None,
            label="deid",
            degraded=degraded_steps,
        )
    deid_map: dict[str, str] = deid.mapping if deid is not None else {}
    # enforce = fail-closed: if de-id failed, never hand raw PHI to ANY LLM step
    # (SOAP or the agents). We run the rest on empty text rather than crash.
    soap_blocked = deid_mode == "enforce" and deid is None
    if deid is not None:
        clean_transcript = deid.transcript
    elif soap_blocked:
        clean_transcript = []
    else:
        clean_transcript = payload.transcript

    def _reid(value: Any) -> Any:
        """Serialize a result then restore real identifiers for display/persist."""
        return reidentify(_serialise(value), deid_map)

    # --- Step 2: Note generation (template-aware) ------------------------
    # The note type (soap | hp | progress | discharge) drives the section
    # template. `clinical_note` holds the real sections; `soap_note` is its SOAP
    # projection so the analyst/coding/compliance agents keep working unchanged.
    if soap_blocked:
        log.warning(
            "[pipeline] DEID enforce: de-id failed — skipping note generation to "
            "avoid sending raw PHI to the LLM"
        )
        clinical_note = ClinicalNote(note_type=note_type)
        if "soap_generator" not in degraded_steps:
            degraded_steps.append("soap_generator")
    else:
        # Prefer the template-aware generate_note; fall back to the legacy
        # generate_soap/generate symbols (SOAP-only) for back-compat.
        note_fn = _resolve("services.soap_generator", "generate_note")
        if note_fn is not None:
            note_raw: Any = await _maybe_call(
                note_fn,
                clean_transcript,
                note_type,
                language,
                default=None,
                label="soap_generator",
                degraded=degraded_steps,
            )
        else:
            soap_fn = _require(
                _resolve("services.soap_generator", "generate_soap")
                or _resolve("services.soap_generator", "generate"),
                "SOAP generator",
            )
            note_raw = await _maybe_call(
                soap_fn,
                clean_transcript,
                default=None,
                label="soap_generator",
                degraded=degraded_steps,
            )
        clinical_note = _coerce_clinical_note(note_raw, note_type)
        if note_raw is None and "soap_generator" not in degraded_steps:
            degraded_steps.append("soap_generator")

    soap_note = clinical_note.to_soap()
    section_dump = {k: v.model_dump() for k, v in clinical_note.sections.items()}
    await bus.publish(visit_id_str, EVENT_SOAP_READY, _reid(section_dump))

    # --- Step 2.5: Grounding gate ----------------------------------------
    # Verify each SOAP claim is supported by its cited transcript lines. This is
    # faithfulness (not correctness) and is config-gated; "off" skips it.
    grounding_result: GroundingResult | None = None
    if settings.GROUNDING_MODE.strip().lower() != "off":
        grounding_fn = _resolve("services.grounding", "verify")
        grounding_result = await _maybe_call(
            grounding_fn,
            clinical_note,
            clean_transcript,
            default=None,
            label="grounding",
            degraded=degraded_steps,
            note_language=language,
            transcript_language=transcript_language,
        )
        await bus.publish(
            visit_id_str,
            EVENT_GROUNDING_READY,
            {"grounding": _reid(grounding_result)},
        )

    # --- Step 3: History retrieval (RAG) ---------------------------------
    history_fn = _resolve("services.history_retrieval", "get_summaries")
    if soap_blocked:
        # enforce fail-closed: don't pull real history into the LLM agents.
        history_summaries: list[str] = []
    else:
        history_summaries = await _maybe_call(
            history_fn,
            soap_note,
            patient.id,
            db,
            default=[],
            label="history_retrieval",
            degraded=degraded_steps,
        )
        # Past-visit summaries are PHI too — scrub them (extending the same map)
        # before they're fed to the analyst agents.
        if deid is not None and history_summaries:
            history_summaries = [deid.scrub_text(s) for s in history_summaries]

    # --- Step 4: Parallel intelligence agents ----------------------------
    anomaly_fn = _resolve("services.anomaly_agent", "detect")
    differential_fn = _resolve("services.differential_agent", "diagnose")
    drift_fn = _resolve("services.drift_agent", "detect")

    anomalies, differentials, drift_flag = await asyncio.gather(
        _maybe_call(
            anomaly_fn,
            soap_note,
            history_summaries,
            list(patient.active_medications or []),
            default=[],
            label="anomaly_agent",
            degraded=degraded_steps,
        ),
        _maybe_call(
            differential_fn,
            soap_note,
            default=[],
            label="differential_agent",
            degraded=degraded_steps,
        ),
        _maybe_call(
            drift_fn,
            patient.id,
            clean_transcript,
            default=None,
            label="drift_agent",
            degraded=degraded_steps,
        ),
    )
    await bus.publish(visit_id_str, EVENT_ANOMALIES_READY, {"anomalies": _reid(anomalies)})
    await bus.publish(
        visit_id_str,
        EVENT_DIFFERENTIALS_READY,
        {"differentials": _reid(differentials)},
    )
    await bus.publish(
        visit_id_str, EVENT_DRIFT_READY, {"drift_flag": _reid(drift_flag)}
    )

    # --- Step 5: Compliance (sequential, after Step 4) -------------------
    compliance_fn = _resolve("services.compliance", "check")
    compliance_result = await _maybe_call(
        compliance_fn,
        clinical_note,
        default=None,
        label="compliance",
        degraded=degraded_steps,
    )
    compliance_status = (
        getattr(compliance_result, "status", None)
        if compliance_result is not None
        else None
    )
    compliance_notes = (
        _serialise(getattr(compliance_result, "notes", []))
        if compliance_result is not None
        else []
    )
    await bus.publish(
        visit_id_str,
        EVENT_COMPLIANCE_READY,
        {
            "compliance_status": compliance_status,
            "compliance_notes": _reid(compliance_notes),
        },
    )

    # --- Step 5.5: Coding agent (advisory ICD-10 / CPT / E&M) ------------
    # Turns the (de-identified) note into billing suggestions. Advisory only —
    # never blocks; config-gated; degrades like every other step.
    coding_result: CodingResult | None = None
    if settings.CODING_MODE.strip().lower() != "off" and not soap_blocked:
        coding_fn = _resolve("services.coding", "generate_codes")
        patient_class = (
            "new" if await _is_first_visit(patient.id, db) else "established"
        )
        coding_result = await _maybe_call(
            coding_fn,
            clinical_note,
            patient_class=patient_class,
            default=None,
            label="coding_agent",
            degraded=degraded_steps,
        )
        await bus.publish(
            visit_id_str, EVENT_CODING_READY, {"coding": _reid(coding_result)}
        )

    # --- Steps 6 + 7: Bias review + Trajectory (concurrent) --------------
    bias_fn = _resolve("services.bias_review", "review")
    trajectory_fn = _resolve("services.trajectory", "compute")

    bias_flags, trajectory_result = await asyncio.gather(
        _maybe_call(
            bias_fn,
            soap_note,
            default=[],
            label="bias_review",
            degraded=degraded_steps,
        ),
        _maybe_call(
            trajectory_fn,
            patient.id,
            drift_flag,
            db,
            default=None,
            label="trajectory",
            degraded=degraded_steps,
        ),
    )
    await bus.publish(
        visit_id_str, EVENT_BIAS_READY, {"bias_flags": _reid(bias_flags)}
    )
    await bus.publish(
        visit_id_str,
        EVENT_TRAJECTORY_READY,
        {"trajectory": _reid(trajectory_result)},
    )

    # --- Re-identify outputs for the doctor's view + persistence ---------
    # Everything above ran on de-identified text; restore real identifiers now.
    # `section_pub` is the real (template-shaped) note body; `soap_note_pub` is its
    # SOAP projection, kept for the typed payload field + residual counting.
    section_pub = _reid(section_dump)
    soap_note_pub = _reid(soap_note)
    grounding_pub = _reid(grounding_result) if grounding_result is not None else None

    deid_report: DeidReport | None = None
    if deid is not None:
        deid_report = deid.report()
        if settings.DEID_FLAG_RESIDUAL:
            residual = count_residual(soap_note_pub, deid_map)
            deid_report.residual_placeholders = residual
            if residual and deid_mode == "enforce" and "deid" not in degraded_steps:
                degraded_steps.append("deid")
    elif deid_mode != "off":
        # de-id was attempted but failed (fail-open) — record it didn't apply.
        deid_report = DeidReport(applied=False)

    # --- Final: persist everything to the visit row ----------------------
    # Store the real section body (flat); note_type is already set on the visit.
    visit.soap_note = section_pub if isinstance(section_pub, dict) else soap_note_pub
    coding_pub = _reid(coding_result) if coding_result is not None else None
    audit_trail: dict[str, Any] = {}
    if grounding_pub is not None:
        audit_trail["grounding"] = grounding_pub
    if deid_report is not None:
        audit_trail["deid"] = deid_report.model_dump(mode="json")
    if coding_pub is not None:
        audit_trail["coding"] = coding_pub
    visit.soap_audit_trail = audit_trail
    visit.anomalies = _as_json_list(_reid(anomalies))
    visit.differentials = _as_json_list(_reid(differentials))
    serialized_drift = _reid(drift_flag)
    visit.drift_flag = (
        serialized_drift if isinstance(serialized_drift, dict) else None
    )
    visit.compliance_status = compliance_status
    visit.compliance_notes = _as_json_list(_reid(compliance_notes))
    visit.bias_flags = _as_json_list(_reid(bias_flags))
    if trajectory_result is not None:
        visit.trajectory_score = getattr(trajectory_result, "score", None)
        visit.trajectory_direction = getattr(trajectory_result, "direction", None)
        visit.trajectory_watch_zones = _as_str_list(
            _reid(getattr(trajectory_result, "watch_zones", []) or [])
        )
    # The stored transcript is always the REAL one — it never goes to an LLM in
    # persisted form; only the de-identified copy did.
    visit.raw_transcript = "\n".join(
        f"[{t.speaker}] {t.text}" for t in payload.transcript
    )
    await db.commit()
    await db.refresh(visit)

    if degraded_steps:
        log.warning(
            "[pipeline] visit_id=%s completed with degraded steps: %s",
            visit_id_str,
            ", ".join(degraded_steps),
        )

    note_pub = ClinicalNote.from_sections(
        note_type, section_pub if isinstance(section_pub, dict) else {}
    )
    return PipelinePayload(
        visit_id=visit.id,
        note_type=note_type,
        language=language,
        note=note_pub,
        soap_note=SOAPNote.model_validate(soap_note_pub),
        anomalies=_reid(anomalies) or [],
        differentials=_reid(differentials) or [],
        drift_flag=_reid(drift_flag),
        compliance_status=compliance_status,
        compliance_notes=_reid(compliance_notes) or [],
        bias_flags=_reid(bias_flags) or [],
        trajectory=_reid(trajectory_result),
        grounding=(
            GroundingResult.model_validate(grounding_pub)
            if grounding_pub is not None
            else None
        ),
        deid=deid_report,
        coding=(
            CodingResult.model_validate(coding_pub) if coding_pub is not None else None
        ),
        degraded_steps=degraded_steps,
    )


@router.post("/run", response_model=PipelinePayload)
@limiter.limit(settings.RATE_LIMIT_PIPELINE)
async def run(
    request: Request,
    payload: PipelineRunRequest,
    user: Annotated[User, Depends(require_doctor)],
    db: Annotated[AsyncSession, Depends(get_db)],
    bus: Annotated[EventBus, Depends(get_event_bus)],
) -> PipelinePayload:
    """Synchronously run pipeline Steps 2-7, streaming events along the way."""
    visit = await _load_my_visit(payload.visit_id, user, db)
    patient = await db.get(Patient, visit.patient_id)
    if patient is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="Patient for this visit not found"
        )

    if visit.is_signed:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="Pipeline cannot be re-run on a signed note",
        )

    visit_id_str = str(visit.id)
    try:
        result = await _run_pipeline(payload, visit, patient, db, bus)
        await bus.publish(
            visit_id_str,
            EVENT_PIPELINE_DONE,
            {"visit_id": visit_id_str, "degraded_steps": result.degraded_steps},
        )
        return result
    except HTTPException as exc:
        await bus.publish(visit_id_str, EVENT_ERROR, {"detail": exc.detail})
        raise
    except Exception as exc:
        # Log the real error server-side; surface only a generic message over
        # SSE and HTTP so internal details aren't exposed to the client.
        log.exception("[pipeline] run failed visit_id=%s", visit.id)
        await bus.publish(
            visit_id_str, EVENT_ERROR, {"detail": "Pipeline execution failed"}
        )
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Pipeline execution failed"
        ) from exc
    finally:
        await bus.close(visit_id_str)


@router.get(
    "/audio/{visit_id}",
    response_model=AudioUrlResponse,
    summary="Mint a short-lived signed URL for a visit's stored audio",
)
async def get_audio_url(
    visit_id: Annotated[UUID, Path()],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
    storage: Annotated[StorageClient, Depends(get_storage)],
) -> AudioUrlResponse:
    """Return a time-limited signed URL for the visit's audio.

    The bucket is private and only the object key is persisted, so a fresh
    signed URL is minted per request and expires after AUDIO_URL_TTL_SECONDS.
    """
    visit = await db.scalar(select(Visit).where(Visit.id == visit_id))
    if visit is None or (user.role != "admin" and visit.doctor_id != user.id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Visit not found")
    if not visit.audio_url:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail="No audio stored for this visit"
        )
    url = await storage.signed_download_url(
        visit.audio_url, settings.AUDIO_URL_TTL_SECONDS
    )
    log_phi_access(
        user_id=str(user.id),
        action="download",
        resource_type="audio",
        resource_id=str(visit.id),
    )
    return AudioUrlResponse(url=url, expires_in=settings.AUDIO_URL_TTL_SECONDS)


@router.get(
    "/run-status/{visit_id}",
    response_model=PipelinePayload,
    summary="Read the persisted pipeline output for a visit",
)
async def run_status(
    visit_id: Annotated[UUID, Path()],
    user: Annotated[User, Depends(get_current_user)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PipelinePayload:
    """Read back the persisted pipeline result for a visit (post-run)."""
    visit = await db.scalar(select(Visit).where(Visit.id == visit_id))
    if visit is None or (
        user.role != "admin" and visit.doctor_id != user.id
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Visit not found")
    log_phi_access(
        user_id=str(user.id),
        action="read",
        resource_type="visit",
        resource_id=str(visit.id),
    )
    stored_note_type = normalize_note_type(getattr(visit, "note_type", None))
    stored_note = ClinicalNote.from_sections(stored_note_type, visit.soap_note or {})
    stored_language = normalize_language(getattr(visit, "language", None))
    return PipelinePayload(
        visit_id=visit.id,
        note_type=stored_note_type,
        language=stored_language,
        note=stored_note,
        soap_note=stored_note.to_soap(),
        anomalies=visit.anomalies or [],
        differentials=visit.differentials or [],
        drift_flag=visit.drift_flag,
        compliance_status=visit.compliance_status,
        compliance_notes=visit.compliance_notes or [],
        bias_flags=visit.bias_flags or [],
        trajectory=(
            TrajectoryResult(
                direction=visit.trajectory_direction,
                score=visit.trajectory_score or 0.0,
                confidence=0,
                watch_zones=visit.trajectory_watch_zones or [],
                computed_from_visits=0,
            )
            if visit.trajectory_direction
            else None
        ),
        grounding=(
            GroundingResult.model_validate(visit.soap_audit_trail["grounding"])
            if isinstance(visit.soap_audit_trail, dict)
            and visit.soap_audit_trail.get("grounding")
            else None
        ),
        deid=(
            DeidReport.model_validate(visit.soap_audit_trail["deid"])
            if isinstance(visit.soap_audit_trail, dict)
            and visit.soap_audit_trail.get("deid")
            else None
        ),
        coding=(
            CodingResult.model_validate(visit.soap_audit_trail["coding"])
            if isinstance(visit.soap_audit_trail, dict)
            and visit.soap_audit_trail.get("coding")
            else None
        ),
    )
