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
from __future__ import annotations

import asyncio
import base64
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
    UploadFile,
    status,
)
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_current_user, get_current_user_sse, require_doctor
from core.constants import (
    EVENT_ANOMALIES_READY,
    EVENT_BIAS_READY,
    EVENT_COMPLIANCE_READY,
    EVENT_DIFFERENTIALS_READY,
    EVENT_DRIFT_READY,
    EVENT_ERROR,
    EVENT_PIPELINE_DONE,
    EVENT_SOAP_READY,
    EVENT_TRAJECTORY_READY,
)
from db.session import get_db
from models.patient import Patient
from models.user import User
from models.visit import Visit
from schemas.pipeline import (
    PipelinePayload,
    PipelineRunRequest,
    SOAPNote,
    TrajectoryResult,
    TranscribeResponse,
)
from core.config import settings
from services.event_bus import EventBus, get_event_bus

log = logging.getLogger("medscribe.pipeline")
router = APIRouter(prefix="/pipeline", tags=["pipeline"])


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
    **kwargs: Any,
) -> Any:
    """Call an optional AI service; if unavailable, log and return ``default``."""
    if func is None:
        log.info("[pipeline] %s unavailable — returning default", label)
        return default
    result = func(*args, **kwargs)
    if asyncio.iscoroutine(result):
        result = await result
    return result


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


def _sse_format(event_name: str, data: dict[str, Any]) -> str:
    """Render a single SSE message frame."""
    return f"event: {event_name}\ndata: {json.dumps(data, default=str)}\n\n"


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
async def transcribe(
    user: Annotated[User, Depends(require_doctor)],
    db: Annotated[AsyncSession, Depends(get_db)],
    audio: UploadFile = File(...),
    visit_id: Annotated[UUID | None, Query()] = None,
) -> TranscribeResponse:
    """Step 1 of the pipeline.

    Reads the uploaded audio blob, calls the AI team's ``transcription.transcribe``
    service to get a diarised transcript, and (asynchronously) queues a B2
    upload that will populate ``visits.audio_url`` once complete.
    """
    audio_bytes = await audio.read()
    if not audio_bytes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Empty audio upload")

    # Confirm caller owns the visit (if a visit_id was supplied).
    if visit_id is not None:
        await _load_my_visit(visit_id, user, db)

    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="GROQ_API_KEY is not configured on the server.",
        )

    transcribe_fn = _require(
        _resolve("services.transcription", "transcribe"),
        "Transcription service",
    )
    try:
        transcript = await transcribe_fn(audio_bytes)
    except Exception as exc:
        log.exception("[pipeline] transcription failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            detail=f"Transcription failed: {exc}",
        ) from exc

    if not transcript:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No speech detected in the recording. Try speaking longer or check your microphone.",
        )

    # Fire-and-forget audio upload via Celery.
    audio_upload_queued = False
    if visit_id is not None:
        try:
            from workers.celery_app import celery_app

            celery_app.send_task(
                "workers.tasks.upload_audio_to_b2",
                args=[
                    str(visit_id),
                    base64.b64encode(audio_bytes).decode("ascii"),
                    audio.content_type or "audio/webm",
                ],
            )
            audio_upload_queued = True
        except Exception as exc:  # noqa: BLE001
            log.warning("[pipeline] failed to queue audio upload: %s", exc)

    return TranscribeResponse(
        visit_id=visit_id,
        transcript=_serialise(transcript) or [],
        audio_upload_queued=audio_upload_queued,
    )


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

    # --- Step 2: SOAP generation -----------------------------------------
    # NB: the AI team's services/soap_generator.py exposes `generate_soap`,
    # not `generate`. We fall back to either symbol so the route works with
    # whichever name they decide to standardise on.
    soap_fn = _require(
        _resolve("services.soap_generator", "generate_soap")
        or _resolve("services.soap_generator", "generate"),
        "SOAP generator",
    )
    soap_note: SOAPNote = await _maybe_call(
        soap_fn, payload.transcript, default=SOAPNote(), label="soap_generator"
    )
    if not isinstance(soap_note, SOAPNote):  # tolerate dict returns
        soap_note = SOAPNote.model_validate(soap_note)
    await bus.publish(visit_id_str, EVENT_SOAP_READY, soap_note.model_dump(mode="json"))

    # --- Step 3: History retrieval (RAG) ---------------------------------
    history_fn = _resolve("services.history_retrieval", "get_summaries")
    history_summaries: list[str] = await _maybe_call(
        history_fn,
        soap_note,
        patient.id,
        db,
        default=[],
        label="history_retrieval",
    )

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
        ),
        _maybe_call(
            differential_fn, soap_note, default=[], label="differential_agent"
        ),
        _maybe_call(
            drift_fn,
            patient.id,
            payload.transcript,
            default=None,
            label="drift_agent",
        ),
    )
    await bus.publish(visit_id_str, EVENT_ANOMALIES_READY, {"anomalies": _serialise(anomalies)})
    await bus.publish(
        visit_id_str,
        EVENT_DIFFERENTIALS_READY,
        {"differentials": _serialise(differentials)},
    )
    await bus.publish(
        visit_id_str, EVENT_DRIFT_READY, {"drift_flag": _serialise(drift_flag)}
    )

    # --- Step 5: Compliance (sequential, after Step 4) -------------------
    compliance_fn = _resolve("services.compliance", "check")
    compliance_result = await _maybe_call(
        compliance_fn, soap_note, default=None, label="compliance"
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
        {"compliance_status": compliance_status, "compliance_notes": compliance_notes},
    )

    # --- Steps 6 + 7: Bias review + Trajectory (concurrent) --------------
    bias_fn = _resolve("services.bias_review", "review")
    trajectory_fn = _resolve("services.trajectory", "compute")

    bias_flags, trajectory_result = await asyncio.gather(
        _maybe_call(bias_fn, soap_note, default=[], label="bias_review"),
        _maybe_call(
            trajectory_fn,
            patient.id,
            drift_flag,
            db,
            default=None,
            label="trajectory",
        ),
    )
    await bus.publish(
        visit_id_str, EVENT_BIAS_READY, {"bias_flags": _serialise(bias_flags)}
    )
    await bus.publish(
        visit_id_str,
        EVENT_TRAJECTORY_READY,
        {"trajectory": _serialise(trajectory_result)},
    )

    # --- Final: persist everything to the visit row ----------------------
    visit.soap_note = soap_note.model_dump(mode="json")
    visit.anomalies = _as_json_list(anomalies)
    visit.differentials = _as_json_list(differentials)
    visit.drift_flag = _serialise(drift_flag)
    visit.compliance_status = compliance_status
    visit.compliance_notes = _as_json_list(compliance_notes)
    visit.bias_flags = _as_json_list(bias_flags)
    if trajectory_result is not None:
        visit.trajectory_score = getattr(trajectory_result, "score", None)
        visit.trajectory_direction = getattr(trajectory_result, "direction", None)
        visit.trajectory_watch_zones = _as_str_list(
            getattr(trajectory_result, "watch_zones", []) or []
        )
    visit.raw_transcript = "\n".join(
        f"[{t.speaker}] {t.text}" for t in payload.transcript
    )
    await db.commit()
    await db.refresh(visit)

    return PipelinePayload(
        visit_id=visit.id,
        soap_note=soap_note,
        anomalies=_serialise(anomalies) or [],
        differentials=_serialise(differentials) or [],
        drift_flag=_serialise(drift_flag),
        compliance_status=compliance_status,
        compliance_notes=compliance_notes or [],
        bias_flags=_serialise(bias_flags) or [],
        trajectory=_serialise(trajectory_result),
    )


@router.post("/run", response_model=PipelinePayload)
async def run(
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
        await bus.publish(visit_id_str, EVENT_PIPELINE_DONE, {"visit_id": visit_id_str})
        return result
    except HTTPException as exc:
        await bus.publish(visit_id_str, EVENT_ERROR, {"detail": exc.detail})
        raise
    except Exception as exc:
        log.exception("[pipeline] run failed visit_id=%s", visit.id)
        await bus.publish(visit_id_str, EVENT_ERROR, {"detail": str(exc)})
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Pipeline execution failed"
        ) from exc
    finally:
        await bus.close(visit_id_str)


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
    return PipelinePayload(
        visit_id=visit.id,
        soap_note=SOAPNote.model_validate(visit.soap_note or {}),
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
    )
