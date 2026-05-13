# Product Requirements Document
# MedScribe AI — Intelligent Medical Documentation & Longitudinal Intelligence Platform

**Version:** 1.0  
**Status:** Approved for Development  
**Last Updated:** May 2026  
**Target:** Hackathon MVP (working demo in ~5 days)

---

## 1. Problem Statement

India's healthcare system has a critical doctor-to-patient ratio problem. Doctors spend 35–40% of their time on documentation rather than care. Existing AI scribes (Nuance DAX, Abridge, Nabla) solve documentation but treat every visit in isolation — no longitudinal intelligence, no predictive signals, no compliance or bias awareness built into the pipeline.

**MedScribe AI** is different: it doesn't just document what happened, it predicts what's coming. By analyzing how patients change across visits — their language, symptoms, vitals, visit frequency — it surfaces early-warning signals before the doctor would otherwise catch them.

---

## 2. Goals

- Reduce per-visit documentation time by 70%+
- Give doctors a real-time, streaming SOAP note that builds as the conversation happens
- Provide longitudinal patient intelligence (trajectory scoring, linguistic drift)
- Simulate compliance and bias review before a note is finalized
- Ship a working end-to-end demo with seeded data that tells a compelling story

---

## 3. User Personas

| Persona | Role | Primary Need |
|---|---|---|
| Dr. User | Clinician, 20–40 patients/day | Fast, accurate notes. Anomaly alerts. No extra clicks. |
| Admin | Hospital admin | Audit trail, compliance status across all notes |
| Demo Viewer | Hackathon judge | A "wow" moment — catch something a doctor would miss |

**Out of scope (v1):** Patient portal, EHR integration (Epic/Cerner), mobile app, multi-language, billing/insurance, offline mode, graph DB drug interactions.

---

## 4. Full Tech Stack

### 4.1 Backend

| Layer | Technology | Why |
|---|---|---|
| Language | Python 3.11+ | Async support, ML ecosystem |
| Web Framework | FastAPI | Async-native, auto OpenAPI docs, fast |
| ORM | SQLAlchemy 2.0 (async) | Async sessions, type-safe queries |
| Schema Validation | Pydantic v2 | Request/response models, settings |
| Auth | python-jose + passlib[bcrypt] | JWT generation and verification |
| Migrations | Alembic | Version-controlled schema changes |
| Task Queue | Celery 5.x | Async post-processing (embeddings, compliance) |
| Message Broker | Redis (Upstash) | Celery broker + result backend + cache |
| HTTP Client | httpx (async) | Calling Groq, Claude APIs |
| Embeddings | sentence-transformers (`all-MiniLM-L6-v2`) | 384-dim, fast, runs on CPU |
| Test Framework | pytest + pytest-asyncio + httpx | Async API tests |
| Containerization | Docker + docker-compose | Local dev, reproducible environment |

### 4.2 AI / ML

| Task | Model | Provider | API |
|---|---|---|---|
| Speech transcription | `whisper-large-v3-turbo` | Groq | `POST /openai/v1/audio/transcriptions` |
| SOAP structuring | `llama-3.3-70b-versatile` | Groq | `POST /openai/v1/chat/completions` |
| Anomaly detection | `llama-3.3-70b-versatile` | Groq | same |
| Differential diagnosis | `llama-3.3-70b-versatile` | Groq | same |
| Compliance simulation | `llama-3.3-70b-versatile` | Groq | same |
| Bias review | `llama-3.3-70b-versatile` | Groq | same |
| Trajectory scoring | Custom scoring logic + `llama-3.1-8b-instant` | Groq | same |
| Linguistic drift | `all-MiniLM-L6-v2` + cosine similarity | Local (sentence-transformers) | — |
| Patient history retrieval | pgvector similarity search | PostgreSQL | SQL |

> All Groq models are on the free tier. Rate limit: 30 req/min, 6000 tokens/min. Design prompts to be concise.

### 4.3 Database

| Store | Technology | Hosted On | Purpose |
|---|---|---|---|
| Primary DB | PostgreSQL 15 + pgvector | Supabase | All structured data + embeddings |
| Cache | Redis | Upstash (free, DB 0 only) | Patient card cache, Celery broker |
| Object Storage | Backblaze B2 | Backblaze | Raw audio file storage |

### 4.4 Frontend

| Layer | Technology | Why |
|---|---|---|
| Framework | Next.js 14.2.15 (App Router) | Pin to 14.2.15 — 14.2.35 breaks Edge runtime |
| Language | TypeScript (strict mode) | Type safety, no `any` |
| Styling | Tailwind CSS | Utility-first, fast to build |
| Animation | Framer Motion | SOAP field streaming animation |
| Audio Capture | Browser MediaRecorder API | No native app needed |
| Real-time Updates | SSE (Server-Sent Events) | Stream SOAP note updates to UI |
| HTTP | fetch with typed wrappers in `lib/api.ts` | No axios needed |

### 4.5 Infrastructure

| Layer | Technology |
|---|---|
| Backend hosting | Railway |
| Frontend hosting | Vercel |
| Local dev | Docker Compose |
| CI/CD | None for hackathon (manual deploy) |

---

## 5. Database Schema (Exact)

```sql
-- Enable pgvector
CREATE EXTENSION IF NOT EXISTS vector;

-- Users (doctors + admins)
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT UNIQUE NOT NULL,
    hashed_password TEXT NOT NULL,
    full_name TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('doctor', 'admin')),
    session_count_today INT DEFAULT 0,
    last_session_date DATE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Patients
CREATE TABLE patients (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name TEXT NOT NULL,
    dob DATE NOT NULL,
    gender TEXT NOT NULL CHECK (gender IN ('male', 'female', 'other')),
    assigned_doctor_id UUID REFERENCES users(id),
    known_allergies TEXT[],
    active_medications TEXT[],
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Visits
CREATE TABLE visits (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    patient_id UUID NOT NULL REFERENCES patients(id),
    doctor_id UUID NOT NULL REFERENCES users(id),
    visit_date TIMESTAMPTZ DEFAULT NOW(),
    raw_transcript TEXT,                  -- diarized full text
    audio_url TEXT,                       -- B2 object URL
    soap_note JSONB,                      -- { subjective, objective, assessment, plan }
    soap_audit_trail JSONB,               -- { field -> [source_line_indices] }
    anomalies JSONB,                      -- [{ id, severity, type, description, source_line }]
    differentials JSONB,                  -- [{ diagnosis, confidence, contributing_soap_fields }]
    drift_flag JSONB,                     -- { flagged: bool, direction: str, delta: float }
    compliance_status TEXT CHECK (compliance_status IN ('pass', 'warn', 'fail')),
    compliance_notes JSONB,               -- [{ field, issue, suggestion }]
    bias_flags JSONB,                     -- [{ phrase, type, suggested_rewrite }]
    trajectory_score FLOAT,
    trajectory_direction TEXT CHECK (trajectory_direction IN ('up', 'stable', 'down')),
    trajectory_watch_zones TEXT[],
    is_signed BOOLEAN DEFAULT FALSE,
    signed_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Embeddings (one per visit, for drift + history retrieval)
CREATE TABLE visit_embeddings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    visit_id UUID NOT NULL REFERENCES visits(id) ON DELETE CASCADE,
    patient_id UUID NOT NULL REFERENCES patients(id),
    patient_speech_embedding VECTOR(384),   -- embedded patient turns only
    full_note_embedding VECTOR(384),        -- embedded full SOAP note
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for fast similarity search
CREATE INDEX ON visit_embeddings
    USING ivfflat (patient_speech_embedding vector_cosine_ops)
    WITH (lists = 100);

CREATE INDEX ON visit_embeddings
    USING ivfflat (full_note_embedding vector_cosine_ops)
    WITH (lists = 100);
```

---

## 6. Full File & Folder Structure

```
medscribe-ai/
│
├── backend/
│   ├── main.py                          # FastAPI app factory, middleware, router registration
│   ├── core/
│   │   ├── config.py                    # pydantic-settings: all env vars loaded here
│   │   ├── security.py                  # JWT create/verify, password hashing
│   │   └── constants.py                 # ICD-10 codebook snippet, drift threshold, etc.
│   │
│   ├── db/
│   │   ├── session.py                   # Async SQLAlchemy engine + session factory
│   │   ├── base.py                      # Base declarative class
│   │   └── migrations/
│   │       ├── env.py
│   │       └── versions/
│   │           └── 001_initial_schema.py
│   │
│   ├── models/                          # SQLAlchemy ORM models (mirror schema above)
│   │   ├── user.py
│   │   ├── patient.py
│   │   ├── visit.py
│   │   └── embedding.py
│   │
│   ├── schemas/                         # Pydantic v2 request/response schemas
│   │   ├── user.py
│   │   ├── patient.py
│   │   ├── visit.py
│   │   └── pipeline.py                  # SOAPNote, AnomalyFlag, Differential, etc.
│   │
│   ├── api/
│   │   ├── deps.py                      # get_db, get_current_user, require_doctor
│   │   └── routes/
│   │       ├── auth.py                  # POST /auth/login, POST /auth/register
│   │       ├── patients.py              # CRUD + GET /patients/{id}/summary
│   │       ├── visits.py                # POST /visits, GET /visits/{id}, GET /visits/patient/{id}
│   │       ├── pipeline.py              # POST /pipeline/transcribe, POST /pipeline/run
│   │       ├── notes.py                 # POST /notes/save, POST /notes/sign
│   │       └── analytics.py            # GET /analytics/trajectory/{patient_id}
│   │
│   ├── services/                        # One file per concern, all async
│   │   ├── transcription.py             # Groq Whisper call → diarized dialogue JSON
│   │   ├── soap_generator.py            # Claude prompt → SOAP JSON with audit trail
│   │   ├── history_retrieval.py         # pgvector similarity search → top-k visits
│   │   ├── anomaly_agent.py             # Claude prompt → anomaly flags list
│   │   ├── differential_agent.py        # Claude prompt → differentials list
│   │   ├── drift_agent.py               # sentence-transformers → cosine delta → drift flag
│   │   ├── compliance.py                # Claude prompt → compliance_status + compliance_notes
│   │   ├── bias_review.py               # Claude prompt → bias_flags list
│   │   ├── trajectory.py                # Aggregate visit history → score + direction + watch_zones
│   │   ├── embedding.py                 # sentence-transformers encode → store in visit_embeddings
│   │   ├── storage.py                   # Backblaze B2 upload/download
│   │   └── cache.py                     # Redis get/set/invalidate helpers
│   │
│   ├── workers/
│   │   ├── celery_app.py                # Celery app init
│   │   └── tasks.py                     # async tasks: embed_visit, invalidate_cache
│   │
│   ├── tests/
│   │   ├── conftest.py                  # Async test client, test DB setup
│   │   ├── test_auth.py
│   │   ├── test_patients.py
│   │   ├── test_soap_generator.py
│   │   ├── test_anomaly_agent.py
│   │   ├── test_compliance.py
│   │   ├── test_drift_agent.py
│   │   ├── test_trajectory.py
│   │   └── test_pipeline_e2e.py         # Full pipeline with mock transcript
│   │
│   ├── .env.example
│   ├── requirements.txt
│   ├── Dockerfile
│   └── alembic.ini
│
├── frontend/
│   ├── app/
│   │   ├── layout.tsx
│   │   ├── page.tsx                     # Login
│   │   └── dashboard/
│   │       ├── page.tsx                 # Doctor dashboard — patient list
│   │       └── session/
│   │           └── [patientId]/
│   │               ├── page.tsx         # Active session view
│   │               └── history/
│   │                   └── page.tsx     # Past visits + trajectory
│   │
│   ├── components/
│   │   ├── AudioRecorder.tsx            # MediaRecorder, start/stop, sends audio blob
│   │   ├── SOAPNote.tsx                 # Streaming SOAP fields, click-to-source
│   │   ├── PatientCard.tsx              # At-a-glance summary card
│   │   ├── TrajectoryCard.tsx           # ↑/→/↓ + watch zones
│   │   ├── AnomalyFlag.tsx              # Inline flag with severity badge
│   │   ├── DifferentialPanel.tsx        # Collapsible ranked differentials
│   │   ├── ComplianceBadge.tsx          # Green/yellow/red + notes
│   │   ├── BiasReviewPanel.tsx          # Phrase + suggestion + accept/reject
│   │   └── CognitiveLoadNudge.tsx       # Dismissable nudge banner
│   │
│   ├── lib/
│   │   ├── api.ts                       # Typed fetch wrappers for all endpoints
│   │   ├── auth.ts                      # JWT store/retrieve from localStorage
│   │   ├── sse.ts                       # SSE connection helper for streaming SOAP
│   │   └── types.ts                     # All shared TypeScript interfaces
│   │
│   ├── .env.example
│   └── next.config.js                   # Pin Next.js 14.2.15, no edge runtime issues
│
├── docker-compose.yml                   # postgres + redis + backend + celery worker
├── seed/
│   └── seed_demo_data.py                # Seeds 6-visit patient history for trajectory demo
└── README.md
```

---

## 7. API Endpoints (Full List)

```
Auth
  POST   /auth/register               Create doctor account
  POST   /auth/login                  Returns JWT

Patients
  POST   /patients                    Create patient
  GET    /patients                    List (doctor sees own, admin sees all)
  GET    /patients/{id}               Patient detail
  GET    /patients/{id}/summary       At-a-glance card (Redis-cached)

Visits
  POST   /visits                      Create empty visit record (session start)
  GET    /visits/{id}                 Full visit detail
  GET    /visits/patient/{id}         All visits for a patient (paginated)

Pipeline
  POST   /pipeline/transcribe         Upload audio → returns diarized transcript
  POST   /pipeline/run                Transcript → full pipeline → complete note payload
  GET    /pipeline/stream/{visit_id}  SSE stream of SOAP fields as they build

Notes
  POST   /notes/save                  Save completed note to visit record
  POST   /notes/sign                  Mark note as signed (immutable after this)

Analytics
  GET    /analytics/trajectory/{patient_id}   Trajectory score + watch zones
  GET    /analytics/load              Doctor cognitive load stats for today

Admin
  GET    /admin/visits                All visits across all doctors (admin only)
  GET    /admin/compliance-summary    Compliance status breakdown
```

---

## 8. Pipeline: Step-by-Step with Exact Inputs/Outputs

### Step 1 — Transcription
**Service:** `services/transcription.py`  
**Triggered by:** `POST /pipeline/transcribe`  
**Input:** Audio blob (webm/wav from MediaRecorder)  
**API call:** `POST https://api.groq.com/openai/v1/audio/transcriptions` with `whisper-large-v3-turbo`  
**Output:**
```json
{
  "transcript": [
    { "speaker": "doctor", "text": "How long have you had this pain?", "line": 1 },
    { "speaker": "patient", "text": "About three days now, it gets worse at night.", "line": 2 }
  ]
}
```
**Timing:** Begins streaming mid-conversation. Frontend calls this endpoint when recording stops.

---

### Step 2 — SOAP Generation
**Service:** `services/soap_generator.py`  
**Input:** Diarized transcript JSON  
**API call:** Groq `llama-3.3-70b-versatile`, system prompt instructs structured JSON output only  
**Prompt strategy:** Pass full transcript, ask model to fill SOAP fields and cite source line numbers  
**Output:**
```json
{
  "subjective": { "text": "Patient reports 3-day pain worsening at night.", "source_lines": [2] },
  "objective": { "text": "No vitals mentioned. Patient appears fatigued.", "source_lines": [] },
  "assessment": { "text": "Possible musculoskeletal or neuropathic pain.", "source_lines": [2, 6] },
  "plan": { "text": "Prescribe ibuprofen 400mg TDS. Follow up in 1 week.", "source_lines": [14, 15] }
}
```

---

### Step 3 — History Retrieval
**Service:** `services/history_retrieval.py`  
**Input:** `patient_id`, current SOAP note text  
**DB call:** Embed current note with `all-MiniLM-L6-v2`, run pgvector cosine similarity against `visit_embeddings.full_note_embedding` for this patient  
**SQL:**
```sql
SELECT v.*, ve.full_note_embedding
FROM visit_embeddings ve
JOIN visits v ON ve.visit_id = v.id
WHERE ve.patient_id = :patient_id
ORDER BY ve.full_note_embedding <=> :query_embedding
LIMIT 5;
```
**Output:** Top-5 most semantically relevant past visit records

---

### Steps 4a, 4b, 4c — Parallel Agents (run concurrently via asyncio.gather)
**Service:** `services/anomaly_agent.py`, `services/differential_agent.py`, `services/drift_agent.py`

**4a — Anomaly Agent**  
Input: current SOAP + top-5 historical visits  
API: Groq `llama-3.3-70b-versatile`  
Output: `[{ "severity": "high", "type": "drug_interaction", "description": "...", "source_line": 14 }]`

**4b — Differential Agent**  
Input: current SOAP note only  
API: Groq `llama-3.3-70b-versatile`  
Output: `[{ "diagnosis": "Tension headache", "confidence": 0.72, "contributing_fields": ["subjective", "assessment"] }]`

**4c — Drift Agent**  
Input: patient speech turns from current visit + `patient_speech_embedding` from last 3 visits  
Process: Embed current patient speech → compute cosine similarity vs prior embeddings → compare delta  
Output: `{ "flagged": true, "direction": "increased_pain_descriptors", "delta": 0.31, "threshold": 0.25 }`

**Concurrency pattern:**
```python
anomalies, differentials, drift = await asyncio.gather(
    anomaly_agent.run(soap, history),
    differential_agent.run(soap),
    drift_agent.run(patient_id, current_patient_speech)
)
```

---

### Step 5 — Compliance Pass
**Service:** `services/compliance.py`  
**Input:** SOAP note JSON (post-Stage 2)  
**API:** Groq `llama-3.3-70b-versatile` with ICD-10 codebook context injected  
**Checks:** HIPAA field completeness, ICD-10 code availability, missing plan details  
**Output:**
```json
{
  "status": "warn",
  "notes": [
    { "field": "objective", "issue": "No vitals documented", "suggestion": "Add BP, HR, temperature if available" },
    { "field": "plan", "issue": "No ICD-10 code mapped", "suggestion": "M54.5 — Low back pain" }
  ]
}
```

---

### Step 6 — Bias Review Pass
**Service:** `services/bias_review.py`  
**Input:** Compliance-corrected SOAP note  
**API:** Groq `llama-3.3-70b-versatile`  
**Checks:** Gender bias, pain underreporting by demographic, age-related minimization  
**Output:**
```json
{
  "flags": [
    {
      "phrase": "patient seems overly anxious about pain",
      "type": "gender_bias",
      "suggested_rewrite": "patient reports significant pain concern"
    }
  ]
}
```

---

### Step 7 — Trajectory Scoring
**Service:** `services/trajectory.py`  
**Input:** All visits for patient (from DB), current anomalies, current drift flag  
**Process:** Rule-based scoring across: anomaly frequency trend, visit frequency trend, drift flag history, vital trends mentioned in SOAP  
**Minimum visits required:** 2 (return `null` if fewer)  
**Output:**
```json
{
  "direction": "down",
  "confidence": 82,
  "watch_zones": ["BP mentioned as elevated 3 visits in a row", "Linguistic drift flagged 2/3 recent visits"],
  "computed_from_visits": 6
}
```

---

### Final — Dashboard Payload
All outputs assembled into one response object and returned from `POST /pipeline/run`. SSE stream delivers SOAP fields as they arrive (Steps 1–2), rest delivered on pipeline completion.

---

## 9. Implementation Phases & Dependency Graph

### Dependency Rules
- Phase 2 depends on Phase 1 (need DB + auth to store anything)
- Phase 3 depends on Phase 2 (need transcription + SOAP before retrieval makes sense)
- Phase 4a/4b/4c can be built in parallel with each other, but depend on Phase 3
- Phase 5 depends on Phase 4 (compliance runs on the output of SOAP + agents)
- Phase 6 depends on Phase 5 (bias sees compliance-corrected note)
- Phase 7 (trajectory) depends on Phase 3 (needs history) and Phase 4c (needs drift)
- Frontend phases can be built in parallel with backend phases after Phase 1 is done

---

### Phase 1 — Foundation *(~Day 1)*
**No dependencies. Start here.**

| Task | File(s) | Parallel? |
|---|---|---|
| FastAPI app factory + CORS + error handlers | `main.py` | — |
| Config loading (all env vars) | `core/config.py` | ✓ parallel with next |
| JWT security helpers | `core/security.py` | ✓ |
| Async SQLAlchemy engine + session | `db/session.py` | — |
| ORM models (User, Patient, Visit, Embedding) | `models/*.py` | ✓ parallel with each other |
| Alembic migration 001 (full schema) | `db/migrations/versions/001` | after models |
| Auth routes (register, login) | `api/routes/auth.py` | after security.py |
| Pydantic schemas | `schemas/*.py` | ✓ parallel with models |
| Docker Compose (postgres + redis) | `docker-compose.yml` | ✓ |
| `.env.example` | root | ✓ |

**Exit criteria:** `POST /auth/register` and `POST /auth/login` work. DB tables created via migration.

---

### Phase 2 — Patient & Visit CRUD *(~Day 1–2)*
**Depends on:** Phase 1

| Task | File(s) | Parallel? |
|---|---|---|
| Patient routes (CRUD) | `api/routes/patients.py` | — |
| Visit routes (create, get, list) | `api/routes/visits.py` | ✓ parallel with patients |
| Auth dependency (get_current_user) | `api/deps.py` | before routes |
| Redis cache helpers | `services/cache.py` | ✓ |
| Celery app init | `workers/celery_app.py` | ✓ |

**Exit criteria:** Can create a patient, create a visit, retrieve both. JWT auth gates all routes.

---

### Phase 3 — Core Pipeline: Transcription + SOAP *(~Day 2)*
**Depends on:** Phase 2

| Task | File(s) | Parallel? |
|---|---|---|
| Groq Whisper transcription service | `services/transcription.py` | — |
| Claude SOAP generation service | `services/soap_generator.py` | ✓ parallel with transcription |
| Pipeline route (`/pipeline/transcribe`, `/pipeline/run`) | `api/routes/pipeline.py` | after both services |
| SSE streaming route (`/pipeline/stream/{visit_id}`) | `api/routes/pipeline.py` | after above |
| B2 audio upload | `services/storage.py` | ✓ parallel |
| Embedding service (sentence-transformers) | `services/embedding.py` | ✓ parallel |
| History retrieval (pgvector) | `services/history_retrieval.py` | after embedding.py |
| Celery task: embed_visit | `workers/tasks.py` | after embedding.py |

**Exit criteria:** Send a text transcript → get back a valid SOAP JSON. pgvector search returns past visits.

---

### Phase 4 — Intelligence Agents *(~Day 3)*
**Depends on:** Phase 3  
**4a, 4b, 4c can be built in parallel by different team members**

| Task | File(s) | Parallel? |
|---|---|---|
| **4a** Anomaly detection agent | `services/anomaly_agent.py` | ✓ |
| **4b** Differential diagnosis agent | `services/differential_agent.py` | ✓ |
| **4c** Linguistic drift agent | `services/drift_agent.py` | ✓ |
| asyncio.gather orchestration in pipeline route | `api/routes/pipeline.py` | after 4a/b/c |

**Exit criteria:** Pipeline returns anomalies, differentials, and drift flag alongside SOAP note.

---

### Phase 5 — Compliance + Bias Review *(~Day 3–4)*
**Depends on:** Phase 4  
**5a and 5b are sequential (not parallel)**

| Task | File(s) | Parallel? |
|---|---|---|
| **5a** Compliance simulation service | `services/compliance.py` | — |
| **5b** Bias review service | `services/bias_review.py` | after 5a (sees corrected note) |
| Wire both into pipeline route | `api/routes/pipeline.py` | after both |

**Exit criteria:** Pipeline output includes `compliance_status`, `compliance_notes`, and `bias_flags`.

---

### Phase 6 — Trajectory + Cognitive Load *(~Day 4)*
**Depends on:** Phase 4c (drift), Phase 3 (history)

| Task | File(s) | Parallel? |
|---|---|---|
| Trajectory scoring service | `services/trajectory.py` | — |
| Cognitive load tracker (increment + check) | `services/cache.py` (Redis counter) | ✓ |
| Analytics routes | `api/routes/analytics.py` | after trajectory.py |
| Patient summary endpoint (Redis-cached) | `api/routes/patients.py` | after trajectory |

**Exit criteria:** `GET /analytics/trajectory/{patient_id}` returns direction, confidence, watch zones.

---

### Phase 7 — Notes + Sign-off *(~Day 4)*
**Depends on:** Phase 5, Phase 6  
**Parallel with Phase 6**

| Task | File(s) | Parallel? |
|---|---|---|
| Note save endpoint | `api/routes/notes.py` | — |
| Note sign endpoint (sets `is_signed`, blocks edits) | `api/routes/notes.py` | after save |
| Audit trail linkage (verify source lines stored) | `api/routes/notes.py` | with save |

**Exit criteria:** Doctor can save a note, sign it. Signed notes cannot be overwritten.

---

### Phase 8 — Frontend *(~Day 2–5, parallel with backend Phases 3–7)*
**Depends on:** Phase 1 (auth endpoints must exist)

| Task | Component | Parallel? |
|---|---|---|
| Auth (login page, JWT store) | `app/page.tsx`, `lib/auth.ts` | — |
| Dashboard patient list | `app/dashboard/page.tsx` | after auth |
| AudioRecorder component | `components/AudioRecorder.tsx` | ✓ |
| SOAPNote streaming component (SSE) | `components/SOAPNote.tsx`, `lib/sse.ts` | ✓ |
| PatientCard component | `components/PatientCard.tsx` | ✓ |
| TrajectoryCard component | `components/TrajectoryCard.tsx` | ✓ |
| AnomalyFlag component | `components/AnomalyFlag.tsx` | ✓ |
| DifferentialPanel component | `components/DifferentialPanel.tsx` | ✓ |
| ComplianceBadge component | `components/ComplianceBadge.tsx` | ✓ |
| BiasReviewPanel component | `components/BiasReviewPanel.tsx` | ✓ |
| CognitiveLoadNudge component | `components/CognitiveLoadNudge.tsx` | ✓ |
| Session view wiring (all components together) | `app/dashboard/session/[patientId]/page.tsx` | after components |

---

### Phase 9 — Demo Data + Polish *(~Day 5)*
**Depends on:** All phases

| Task | File(s) |
|---|---|
| Seed script: 6-visit patient showing ↓ trajectory | `seed/seed_demo_data.py` |
| Inject 3 HIPAA violations into test note (compliance demo) | seed script |
| Inject 2 biased phrases into test note (bias demo) | seed script |
| End-to-end test covering full pipeline | `tests/test_pipeline_e2e.py` |
| README with setup instructions | `README.md` |

---

## 10. Environment Variables

**Backend `.env.example`:**
```
DATABASE_URL=postgresql+asyncpg://user:pass@host:5432/medscribe
REDIS_URL=rediss://:password@host:port/0
GROQ_API_KEY=
JWT_SECRET_KEY=
SECRET_KEY=
BACKBLAZE_KEY_ID=
BACKBLAZE_APPLICATION_KEY=
BACKBLAZE_BUCKET_NAME=medscribe-audio
EMBEDDING_MODEL=all-MiniLM-L6-v2
DRIFT_THRESHOLD=0.25
COGNITIVE_LOAD_THRESHOLD=6
```

**Frontend `.env.example`:**
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

---

## 11. Out of Scope (v1)

- EHR integration (Epic, Cerner)
- Patient-facing portal
- Mobile app
- Multi-language transcription
- Graph database / drug interaction graph
- Billing / insurance
- Offline mode
- Real-time collaboration (multiple doctors on same note)

---

## 12. Success Metrics (Demo Day)

| Metric | Target |
|---|---|
| Full pipeline latency | ≤ 15s from recording stop to complete dashboard |
| SOAP field accuracy on test transcript | ≥ 85% correct field placement |
| Trajectory demo | Seeded 6-visit patient shows clear ↓ with watch zones |
| Compliance catch rate | ≥ 3 injected violations caught |
| Bias catch rate | ≥ 2 injected biased phrases caught |
| Drift detection | Flagged on visit 4 of seeded data |
