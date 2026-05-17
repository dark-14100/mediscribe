# Product Requirements Document
# MedScribe AI — Intelligent Medical Documentation & Longitudinal Intelligence Platform

**Version:** 3.0
**Status:** Approved for Development
**Last Updated:** May 2026
**Target:** Hackathon MVP — working end-to-end demo in ~5 days

---

## 1. Problem Statement

India has 1 doctor per 834 patients against a WHO recommendation of 1 per 1,000. Documentation consumes 35–40% of every clinical shift. Existing AI scribes (Nuance DAX at ₹70,000/month per doctor, Abridge, Nabla) solve single-visit documentation but treat each session in isolation — no memory across visits, no early-warning signals, no compliance or bias checks in the pipeline.

**MedScribe AI** generates real-time SOAP notes from voice and wraps a longitudinal intelligence layer around them: trajectory scoring, linguistic drift detection, anomaly flagging, compliance simulation, and bias-aware output review — all completing in under 15 seconds per session.

---

## 2. Goals

- Real-time SOAP note generation streamed to the doctor mid-conversation
- Longitudinal patient intelligence derived from visit history (trajectory, drift)
- Inline anomaly and differential diagnosis suggestions
- Compliance simulation before any note is finalized
- Bias-aware review pass on generated clinical language
- Full audit trail — every AI-generated field traceable to its source transcript line
- Working demo with seeded 6-visit patient data that shows a clear downward trajectory caught before a crisis

---

## 3. User Personas

| Persona | Role | Primary Need |
|---|---|---|
| Doctor | Clinician, 20–40 patients/day | Fast accurate notes, anomaly alerts, no friction |
| Admin | Hospital administrator | Compliance dashboard, audit trail across all doctors |
| Hackathon Judge | Demo evaluator | One clear "wow" moment — AI catches something the doctor missed |

**Out of scope for v1:** EHR integration (Epic/Cerner), patient portal, mobile app, multi-language transcription, billing/insurance, offline mode, Neo4j drug interaction graph, real-time multi-doctor collaboration on the same note.

---

## 4. Full Tech Stack

### 4.1 Backend Language and Framework

**Python 3.11+** is the backend language. The web framework is **FastAPI**, chosen for its native async support, automatic OpenAPI documentation, and Pydantic v2 integration. All route handlers are async. The ASGI server is **Uvicorn with standard extras** (which includes `uvloop` and `httptools` for performance).

### 4.2 Database Layer

**PostgreSQL 15** is the primary database, hosted on **Supabase** (free tier). The pgvector extension is enabled on the same PostgreSQL instance — this means embeddings live in the same database as structured data, no separate vector store needed. The ORM is **SQLAlchemy 2.0 in async mode** using the `asyncpg` driver. Schema migrations are managed by **Alembic**.

**Redis** is used for two separate purposes: as the message broker and result backend for Celery task queuing, and as an in-memory cache for precomputed patient summary cards. Redis is hosted on **Upstash free tier** (DB 0 only — Upstash free only gives one database). The Redis URL must include `?ssl_cert_reqs=none` when using Upstash TLS. The cache key format for patient summaries is `patient_summary:{patient_id}`. Cache is invalidated explicitly after a note is saved — no TTL-based expiry.

**Backblaze B2** is used for raw audio file object storage. Audio blobs uploaded from the browser are stored here and referenced by URL in the visits table. This keeps the PostgreSQL row size manageable.

### 4.3 Task Queue

**Celery 5.x** handles all async post-processing tasks that should not block the HTTP response. The two primary Celery tasks are: generating and storing visit embeddings after a note is saved, and invalidating and rebuilding the Redis patient summary cache. Celery uses Redis (same Upstash instance) as both the broker and result backend. A single Celery worker process runs alongside the FastAPI server in the Docker Compose setup.

### 4.4 Authentication

Auth uses **JWT (JSON Web Tokens)**. Token generation and verification uses `python-jose` with the cryptography backend. Passwords are hashed with `passlib` using bcrypt. On login, the server issues a signed JWT containing the user's ID and role. Every protected route reads the JWT from the Authorization header and resolves the current user. Doctor-scoped routes additionally verify that the user's role is `doctor`. All patient and visit queries are filtered by `doctor_id = current_user.id` unless the user is an admin.

### 4.5 AI and ML Layer

**Groq** is the inference provider for all LLM and transcription tasks. Groq's free tier allows 30 requests/minute, 6,000 tokens/minute, and 14,400 requests/day. All prompts must be written concisely — visit history context is always summarized before injection, never passed verbatim.

The models used on Groq are:
- `whisper-large-v3-turbo` for audio transcription — this is Groq's fastest Whisper variant and produces timestamped, diarized output when called with `response_format: verbose_json`
- `llama-3.3-70b-versatile` for all LLM inference tasks: SOAP generation, anomaly detection, differential diagnosis, compliance simulation, and bias review
- `llama-3.1-8b-instant` for the lightweight trajectory scoring logic where speed matters more than reasoning depth

**Embeddings** are generated locally using `sentence-transformers` with the `all-MiniLM-L6-v2` model. This is a 384-dimensional model that runs on CPU, requires no GPU, and produces embeddings fast enough for real-time use. It is used for two purposes: embedding the full SOAP note for semantic history retrieval, and embedding patient speech turns only for linguistic drift detection.

### 4.6 RAG Stack

The RAG (Retrieval Augmented Generation) pipeline is used to inject relevant patient history into the LLM context before running anomaly detection, differential diagnosis, and compliance simulation. The full RAG stack is:

**Ingestion side:** After every visit note is saved and signed, a Celery task runs that takes the complete SOAP note text, embeds it using `all-MiniLM-L6-v2`, and stores the resulting 384-dim vector in the `visit_embeddings` table alongside the patient ID and visit ID. A second embedding of patient speech turns only (filtered from the diarized transcript) is also stored in the same row — this is used specifically for drift detection, not general retrieval.

**Retrieval side:** When the pipeline runs for a new visit, the current SOAP note text (generated in Step 2) is embedded and used as a query vector. A pgvector cosine similarity search runs against all `visit_embeddings` rows for the same patient, ordered by distance, returning the top 5 most semantically relevant past visits. This is semantic retrieval — not just "last 5 visits" — meaning if the current visit mentions chest pain, it will retrieve previous visits that also discussed cardiac symptoms even if they were 8 months ago.

**Injection side:** The retrieved past visit SOAP notes are summarized (not passed verbatim) and injected into the system prompt for the anomaly agent, differential agent, and compliance agent. The injection format is a structured block that lists each retrieved visit's date, SOAP summary, and any anomalies previously flagged.

**Why pgvector over a separate vector DB:** For a hackathon with a single patient dataset, pgvector on Supabase is more than sufficient and eliminates an entire infrastructure dependency. The ivfflat index on the embedding columns keeps similarity search fast.

### 4.7 Frontend

The frontend is **Next.js 14.2.15** — pin this exact version. Version 14.2.35 and later break the Edge runtime. The App Router is used throughout. The language is **TypeScript in strict mode** — no `any` types anywhere. Styling is **Tailwind CSS only** — no inline styles, no CSS modules. Animations on the SOAP note streaming are handled by **Framer Motion**.

Audio is captured directly in the browser using the **MediaRecorder API** — no native app, no third-party SDK. When recording stops, the audio blob is sent to the backend transcription endpoint as a multipart form upload.

Real-time SOAP note streaming from backend to frontend uses **Server-Sent Events (SSE)**. As each SOAP field is generated by the LLM, it is pushed to the frontend via an SSE connection so the doctor sees the note building live during the session, not as a batch result after. The SSE helper lives in `lib/sse.ts`.

State management uses React hooks only — no Redux, no Zustand. The only external state concern is auth (JWT stored in localStorage via `lib/auth.ts`).

### 4.8 Infrastructure

Local development runs entirely on **Docker Compose** with four services: PostgreSQL, Redis, the FastAPI backend, and the Celery worker. The backend and Celery worker share the same Docker image but different entrypoints.

Backend is deployed to **Railway**. Frontend is deployed to **Vercel**. No CI/CD for the hackathon — manual deploy via Railway CLI and `vercel --prod`.

### 4.9 Frontend Component Map

Every UI element is a standalone component. The components required are:

**AudioRecorder** — Handles MediaRecorder lifecycle (start, stop, pause). Shows a recording indicator and elapsed time. On stop, sends the audio blob to `POST /pipeline/transcribe`. Lives at the top of the session view.

**SOAPNote** — Displays the four SOAP fields (Subjective, Objective, Assessment, Plan) as they stream in via SSE. Each field is editable by the doctor before sign-off. Clicking any field reveals the source transcript lines that generated it (audit trail). Uses Framer Motion for the appear animation as each field populates.

**PatientCard** — The "at a glance" summary shown at the top of every session. Loaded from the Redis-cached `GET /patients/{id}/summary` endpoint. Displays: patient name, DOB, last 3 visit dates, active medications, known allergies, and the trajectory badge.

**TrajectoryCard** — Displays the trajectory direction arrow (↑ improving / → stable / ↓ declining), the confidence score as a percentage, and the watch zones list. Only renders if the patient has at least 2 prior visits. Shown prominently at the top of the dashboard, not buried in a panel.

**AnomalyFlag** — An inline highlight rendered within or alongside the SOAP note for each detected anomaly. Shows severity badge (high/medium/low with color coding), anomaly type, description, and the source transcript line number. Clicking the line number scrolls the transcript panel to that line.

**DifferentialPanel** — A collapsible panel showing the ranked list of differential diagnoses. Each differential shows the diagnosis name, confidence score as a percentage bar, and which SOAP fields contributed to it. Clearly labelled as AI suggestions — not clinical decisions.

**ComplianceBadge** — A status badge (pass/warn/fail) shown in the note header. Clicking it expands a panel listing each compliance note: the field with the issue, the issue description, and the suggested fix. Doctor must acknowledge warn and fail status before signing.

**BiasReviewPanel** — A panel listing each bias flag. Each flag shows the flagged phrase highlighted, the bias type (gender/age/socioeconomic), and the suggested neutral rewrite. Each flag has an Accept and Dismiss button — neither blocks note completion.

**CognitiveLoadNudge** — A dismissable banner that appears at the top of the session view when the doctor's session count for the day exceeds the threshold (default 6). Text reads: "You've completed 6+ sessions today — review this note carefully before signing." One click dismisses it.

---

## 5. Database Schema

### Table: users
Stores doctor and admin accounts. Fields: UUID primary key, email (unique), hashed password, full name, role (doctor or admin), session count for today (integer, incremented on each session start), last session date (date, used to reset the counter daily), and created timestamp.

### Table: patients
Stores patient records. Fields: UUID primary key, full name, date of birth, gender, assigned doctor ID (foreign key to users), known allergies (text array), active medications (text array), and created timestamp.

### Table: visits
The central table. One row per clinical session. Fields: UUID primary key, patient ID (foreign key), doctor ID (foreign key), visit date timestamp, raw transcript (full diarized text), audio URL (Backblaze B2 object URL), SOAP note (JSONB — four fields each with text and source line indices), SOAP audit trail (JSONB — maps each field to its source line numbers), anomalies (JSONB array), differentials (JSONB array), drift flag (JSONB), compliance status (text — pass/warn/fail), compliance notes (JSONB array), bias flags (JSONB array), trajectory score (float), trajectory direction (text — up/stable/down), trajectory watch zones (text array), is signed (boolean, default false), signed timestamp, and created timestamp.

### Table: visit_embeddings
Stores embeddings for RAG retrieval and drift detection. One row per visit. Fields: UUID primary key, visit ID (foreign key with cascade delete), patient ID (foreign key), full note embedding (384-dim vector — embedding of the complete SOAP note text, used for history retrieval), patient speech embedding (384-dim vector — embedding of patient dialogue turns only, used for linguistic drift), and created timestamp. Both vector columns are indexed with ivfflat cosine distance indexes for fast similarity search.

---

## 6. API Endpoints

### Auth
- `POST /auth/register` — Create a new doctor account. Body: email, password, full name, role.
- `POST /auth/login` — Returns a signed JWT. Body: email, password.

### Patients
- `POST /patients` — Create a new patient record. Doctor-scoped.
- `GET /patients` — List all patients for the current doctor (admin sees all).
- `GET /patients/{id}` — Full patient detail.
- `GET /patients/{id}/summary` — Returns the precomputed at-a-glance card. Response is served from Redis if cached. If not cached, computed from DB and cached before returning.

### Visits
- `POST /visits` — Create an empty visit record at session start. Returns the visit ID which is used for SSE streaming.
- `GET /visits/{id}` — Full visit detail including all pipeline outputs.
- `GET /visits/patient/{patient_id}` — Paginated list of all visits for a patient, newest first.

### Pipeline
- `POST /pipeline/transcribe` — Accepts an audio file upload (multipart). Calls Groq Whisper, returns the diarized transcript JSON. Also triggers async B2 audio upload via Celery.
- `POST /pipeline/run` — Accepts a transcript JSON and visit ID. Runs the full pipeline synchronously (transcription already done). Returns the complete pipeline output payload.
- `GET /pipeline/stream/{visit_id}` — SSE endpoint. The client connects here before calling `/pipeline/run`. As each pipeline step completes, it pushes a named event to this stream. Frontend updates the UI incrementally.

### Notes
- `POST /notes/save` — Saves the (possibly doctor-edited) note to the visit record. Triggers Celery tasks: generate embeddings, invalidate patient summary cache.
- `POST /notes/sign` — Marks the visit as signed. Sets `is_signed = true` and `signed_at`. After signing, the note becomes immutable — any further save attempts return 409.

### Analytics
- `GET /analytics/trajectory/{patient_id}` — Returns trajectory direction, confidence score, watch zones, and the number of visits it was computed from.
- `GET /analytics/load` — Returns the current doctor's session count for today and whether the cognitive load threshold has been crossed.

### Admin
- `GET /admin/visits` — All visits across all doctors. Admin only.
- `GET /admin/compliance-summary` — Breakdown of pass/warn/fail counts across all notes.

---

## 7. Full Pipeline — Step by Step

The pipeline is the core of the product. It runs when the doctor ends a session and the audio has been transcribed. The full sequence from audio blob to complete dashboard payload must complete in under 15 seconds.

### Step 1 — Transcription

The audio blob from the browser MediaRecorder is sent to `POST /pipeline/transcribe`. The backend forwards it to Groq's Whisper endpoint (`whisper-large-v3-turbo`) with `response_format: verbose_json`. Groq returns a timestamped transcript with individual segments. The backend post-processes this into a diarized format: each line is labelled as either "doctor" or "patient" using turn-taking heuristics (questions labelled doctor, responses labelled patient, with a fallback to alternating). The output is a numbered list of dialogue lines, each with a speaker label, text, and line index. This line index is what the audit trail uses throughout the rest of the pipeline. Simultaneously, a Celery task uploads the raw audio blob to Backblaze B2 and updates `visits.audio_url` with the returned object URL.

### Step 2 — SOAP Generation

The diarized transcript is sent to `llama-3.3-70b-versatile` on Groq. The system prompt instructs the model to act as a clinical documentation assistant and return a JSON object only — no prose, no preamble. The user message contains the full diarized transcript with line numbers. The model is instructed to fill four fields (Subjective, Objective, Assessment, Plan) and for each field, list the exact line numbers from the transcript that the text is derived from. Temperature is set to 0.1 for determinism. The response is parsed and validated against the SOAP schema. If any field is missing, it is filled with an empty string and an empty source lines array — the pipeline never errors on incomplete SOAP. The resulting SOAP JSON is stored in `visits.soap_note` and the source line mapping is stored in `visits.soap_audit_trail`. This output is immediately pushed to the SSE stream so the doctor sees the note appear.

### Step 3 — History Retrieval (RAG)

The full SOAP note text (all four fields concatenated) is embedded using `all-MiniLM-L6-v2` locally. The resulting 384-dim vector is used to run a pgvector cosine similarity search against `visit_embeddings.full_note_embedding` filtered to the current patient. The top 5 most semantically similar past visits are retrieved, ordered by similarity score. Each retrieved visit's SOAP note is summarized into a compact 3-line string (date, one-line assessment, plan summary) before being injected into downstream agent prompts. Full SOAP text is never passed verbatim — this keeps the prompt within Groq's token limits.

### Step 4 — Parallel Intelligence Agents

Three agents run concurrently using `asyncio.gather`. They share the current SOAP note and the summarized history context from Step 3 as input.

**Anomaly Agent:** Sends the current SOAP note plus history summaries to `llama-3.3-70b-versatile`. The system prompt instructs it to look for: drug interactions (compared against `active_medications` from the patient record), symptoms that contradict the patient's documented history, vitals mentioned that are outside normal ranges, and any clinical inconsistency between the current assessment and prior assessments. Output is a JSON array of anomaly objects, each with a severity (high/medium/low), type, description, and the source line number from the transcript. If no anomalies are found, it returns an empty array — not null.

**Differential Diagnosis Agent:** Sends only the current SOAP note (no history) to `llama-3.3-70b-versatile`. The system prompt instructs it to return a ranked list of 3–5 possible diagnoses consistent with the subjective and objective sections, each with a confidence score between 0 and 1 and the list of SOAP fields that contributed to the suggestion. Output is a JSON array. The prompt emphasizes that these are suggestions for the doctor's consideration, not clinical determinations.

**Linguistic Drift Agent:** This agent does not call the LLM. It extracts all lines labelled "patient" from the current diarized transcript and concatenates them into a single string. This string is embedded using `all-MiniLM-L6-v2`. The resulting vector is compared via cosine similarity against the `patient_speech_embedding` vectors from the patient's last 3 visits retrieved from `visit_embeddings`. The drift score is `1 - average_cosine_similarity` — a higher score means the patient's language has shifted more. If the drift score exceeds `DRIFT_THRESHOLD` (default 0.25), a drift flag is set. The direction label is derived from which semantic cluster the current speech is closest to using a simple keyword-presence check on the embedding's nearest neighbors: if the current speech is closer to pain-descriptor vocabulary, the direction is "increased_pain_descriptors"; if closer to negative-affect vocabulary, it is "increased_negative_affect". If fewer than 2 prior patient speech embeddings exist, the drift flag is set to null and the UI shows "insufficient history."

### Step 5 — Compliance Simulation

After Step 4 completes, the SOAP note is sent to `llama-3.3-70b-versatile` for compliance checking. The system prompt includes a condensed ICD-10 reference for common primary care codes and a checklist of HIPAA documentation requirements (patient identifier present, date of service, provider identifier, reason for visit, plan of care). The model checks: whether all four SOAP fields are populated, whether a plausible ICD-10 code can be mapped to the assessment, whether the plan field includes a follow-up or disposition, and whether any required documentation markers are missing. Output is a compliance status (pass/warn/fail) and a JSON array of compliance notes, each identifying the field, the issue, and a suggested fix. Status is "pass" if no issues are found, "warn" if there are suggestions but nothing blocking, and "fail" if required fields are empty or the note is clinically unsafe to file as written.

### Step 6 — Bias Review

The compliance-corrected SOAP note (after the doctor has seen the compliance suggestions) is sent to `llama-3.3-70b-versatile` for bias review. The bias review sees the corrected note, not the original — this prevents double-flagging issues that compliance already caught. The system prompt instructs the model to identify language patterns associated with: gender bias (pain underreporting, emotionality language applied to specific genders), age bias (dismissive language toward elderly patients, overattribution of symptoms to age), and socioeconomic bias (assumptions about compliance or lifestyle based on social markers). Output is a JSON array of bias flag objects, each with the flagged phrase, bias type, and a suggested neutral rewrite. If no flags are found, the array is empty.

### Step 7 — Trajectory Scoring

Trajectory scoring runs in parallel with Step 6 (both can start after Step 4 finishes — Step 6 depends on Step 5, trajectory depends on Step 4 and history). Trajectory is computed from the full visit history for the patient using a rule-based scoring system, not an LLM call, to keep it fast and deterministic.

**How trajectory scoring works:**

The scoring engine retrieves all visits for the patient from the database, ordered oldest to newest. It then evaluates four signals across the most recent 5 visits (or however many exist):

**Signal 1 — Anomaly frequency trend:** Counts the number of anomalies flagged per visit. If the count is increasing visit over visit, this contributes a negative score. Specifically: if the last 3 visits show a strictly increasing anomaly count, score −2. If the last 3 visits show a non-decreasing count (flat or up), score −1. If decreasing, score +1.

**Signal 2 — Drift flag trend:** Counts how many of the last 3 visits had a drift flag triggered. 0 flags = +1, 1 flag = 0, 2–3 flags = −2.

**Signal 3 — Visit frequency trend:** If the gap between visits is shortening (patient is coming back sooner), this is a warning signal. Compute the average inter-visit gap in days across the last 4 visits. If the gap has shortened by more than 30% compared to the prior average, score −1.

**Signal 4 — Symptom recurrence:** Check whether the same symptom keywords appear in the subjective section of the last 3 visits. Extract the top 5 noun phrases from each subjective field and compare sets. If the same symptom appears in all 3 of the last visits, score −1 per recurring symptom (capped at −3).

**Total score mapping:**
- Score ≥ +2: direction = "up", label = improving
- Score between −1 and +1 inclusive: direction = "stable"  
- Score ≤ −2: direction = "down", label = declining

**Confidence score:** Computed as `(number_of_visits_used / 5) * 100`, capped at 100. A patient with 5+ visits gets 100% confidence. A patient with 2 visits gets 40% confidence — the UI shows this so the doctor knows how much to weight the signal.

**Watch zones:** Any signal that contributed a negative score generates a watch zone string. For example: "Anomaly count increasing 3 visits in a row", "Drift flagged in 2 of last 3 visits", "Chief complaint recurring: chest pain". These are plain English strings shown in the TrajectoryCard.

**Minimum visits:** If the patient has fewer than 2 visits, trajectory returns null and the TrajectoryCard shows "Insufficient visit history for trajectory analysis."

### Final — Dashboard Payload Assembly

All outputs from Steps 2–7 are assembled into a single JSON payload and returned from `POST /pipeline/run`. The payload structure mirrors the `visits` table JSONB fields. This payload is also used to update the visit record in the database. The SSE stream receives named events for each step as it completes: `soap_ready`, `anomalies_ready`, `differentials_ready`, `drift_ready`, `compliance_ready`, `bias_ready`, `trajectory_ready`. The frontend subscribes to this stream before the pipeline starts and updates each UI component as its corresponding event arrives.

---

## 8. SOAP Note Processing — Detailed

### How the SOAP note is generated

The SOAP generation prompt is structured as follows: the system message establishes the clinical documentation role and instructs JSON-only output. The user message contains the numbered diarized transcript. The model fills four fields. Each field contains the clinical text and an array of line indices from the transcript that the text is derived from. These line indices are stored in the audit trail and used by the frontend to highlight source lines when a doctor clicks a SOAP field.

### How SOAP fields map to the transcript

- **Subjective:** Everything the patient says about their symptoms, how they feel, duration, severity. Sourced from patient-labelled turns.
- **Objective:** Clinical observations, any vitals mentioned, physical examination notes mentioned by the doctor. Sourced from doctor-labelled turns describing observations.
- **Assessment:** The working diagnosis or clinical impression. Sourced from doctor turns that include diagnostic language.
- **Plan:** Treatment plan, prescriptions mentioned, referrals, follow-up timing. Sourced from doctor turns describing next steps.

### How the doctor interacts with the note

The SOAP note renders as four editable text areas in the frontend. The doctor can edit any field freely before signing. Edits do not affect the audit trail — the stored source line indices always reflect what the AI generated, not what the doctor changed. If the doctor edits a field, the frontend marks that field as "doctor-modified" with a visual indicator. This is stored in the visit record as a boolean per field. The sign-off action requires the doctor to have viewed (scrolled through) all four fields — enforced client-side.

---

## 9. Implementation Phases and Team Split

### Dependency Rules

- Phase 1 (Foundation) has no dependencies. Everyone can start here.
- Phase 2 (Patient/Visit CRUD) depends on Phase 1.
- Phase 3 (Transcription + SOAP) depends on Phase 2.
- Phase 4 (Intelligence Agents) depends on Phase 3. The three agents within Phase 4 are independent of each other and can be built by three different team members simultaneously.
- Phase 5 (Compliance) depends on Phase 4 completing.
- Phase 6 (Bias Review) depends on Phase 5 — bias sees the compliance-corrected note.
- Phase 7 (Trajectory) depends on Phase 3 (needs visit history) and Phase 4c (needs drift flag data structure). It is independent of Phase 5 and 6 and can be built in parallel with them.
- Phase 8 (Frontend) depends on Phase 1 for auth endpoints. All frontend components can be built in parallel with backend Phases 3–7 using mock data.
- Phase 9 (Demo data and polish) depends on all phases completing.

### Suggested Team Split (3–4 members)

**Member A — Backend Core:**
Owns Phases 1 and 2. Sets up FastAPI, SQLAlchemy, Alembic migrations, auth (JWT), all CRUD routes, Docker Compose, and the Celery/Redis setup. This is the foundation everyone else depends on. Should be the most experienced backend person on the team.

**Member B — Pipeline and RAG:**
Owns Phase 3 (transcription, SOAP generation, embedding service, RAG retrieval, SSE streaming) and Phase 7 (trajectory scoring). This is the most technically complex backend work and should be owned by whoever is most comfortable with async Python, LLM prompting, and vector search.

**Member C — Intelligence Agents:**
Owns Phases 4, 5, and 6. Builds the anomaly agent, differential agent, drift agent, compliance service, and bias review service. All of these follow the same pattern: construct a prompt, call Groq, parse the JSON response, return a typed object. Once Phase 3 is done and the SOAP output schema is clear, Member C can build all five services in parallel.

**Member D — Frontend:**
Owns Phase 8 entirely. Builds all components against mock data from day 1. Integrates with real backend endpoints as Member A and B ship them. The AudioRecorder and SOAPNote SSE streaming components are the most complex and should be built first.

---

### Phase 1 — Foundation (~Day 1)
**Owner: Member A. No dependencies.**

Tasks: Initialize the FastAPI app with CORS middleware and global error handlers. Set up pydantic-settings for all env var loading. Write JWT token creation and verification helpers. Set up the async SQLAlchemy engine and session factory. Write all four ORM models (User, Patient, Visit, VisitEmbedding). Write the Alembic initial migration that creates all four tables and enables pgvector. Write all Pydantic request/response schemas. Write auth routes (register, login). Set up Docker Compose with PostgreSQL, Redis, backend, and Celery worker services. Write `.env.example` with all required variables.

**Exit criteria:** `POST /auth/register` creates a user. `POST /auth/login` returns a valid JWT. All four DB tables exist via migration. Docker Compose starts all services without errors.

---

### Phase 2 — Patient and Visit CRUD (~Day 1–2)
**Owner: Member A. Depends on Phase 1.**

Tasks: Write the `get_current_user` and `require_doctor` auth dependency functions. Write patient CRUD routes (create, get, list). Write visit routes (create, get, list by patient). Write the Redis cache helper module (get, set, invalidate). Initialize the Celery app.

**Exit criteria:** Authenticated doctor can create a patient, create a visit under that patient, and retrieve both. JWT auth gates all routes — unauthenticated requests return 401.

---

### Phase 3 — Core Pipeline: Transcription, SOAP, RAG (~Day 2)
**Owner: Member B. Depends on Phase 2.**

Tasks: Write the transcription service that calls Groq Whisper and post-processes the response into a diarized numbered transcript. Write the SOAP generation service that constructs the LLM prompt and parses the structured response. Write the SSE pipeline route that streams named events to the frontend as each step completes. Write the embedding service that uses sentence-transformers to produce 384-dim vectors from text. Write the history retrieval service that embeds the current note and runs the pgvector cosine search. Write the Celery task that runs embeddings asynchronously after note save. Write the Backblaze B2 storage service for audio upload.

**Exit criteria:** Given a raw audio file, `POST /pipeline/transcribe` returns a valid diarized transcript. Given a transcript, `POST /pipeline/run` returns a valid SOAP JSON. The pgvector similarity search returns the top 5 past visits for a patient with existing history.

---

### Phase 4 — Intelligence Agents (~Day 3)
**Owner: Member C. Depends on Phase 3. All three agents are parallel.**

**Phase 4a — Anomaly Agent:** Write the service that takes the current SOAP note and history summaries, constructs the anomaly detection prompt, calls `llama-3.3-70b-versatile`, and parses the response into the anomaly flag schema.

**Phase 4b — Differential Diagnosis Agent:** Write the service that takes the current SOAP note only, constructs the differential diagnosis prompt, calls `llama-3.3-70b-versatile`, and parses the ranked differentials schema.

**Phase 4c — Linguistic Drift Agent:** Write the service that extracts patient speech turns, embeds them, compares against prior patient speech embeddings via cosine similarity, computes the drift score, applies the threshold, and returns the drift flag schema.

After all three are written, wire them into the pipeline route using `asyncio.gather` so all three run concurrently.

**Exit criteria:** `POST /pipeline/run` returns anomalies, differentials, and drift flag alongside the SOAP note.

---

### Phase 5 — Compliance Simulation (~Day 3–4)
**Owner: Member C. Depends on Phase 4.**

Tasks: Write the compliance service that constructs the compliance prompt with the ICD-10 reference snippet and HIPAA checklist, calls `llama-3.3-70b-versatile`, and parses compliance status and notes. Wire into the pipeline route after the parallel agents complete.

**Exit criteria:** Pipeline output includes `compliance_status`, `compliance_notes`. A test note with a missing plan field returns status "warn" or "fail".

---

### Phase 6 — Bias Review (~Day 4)
**Owner: Member C. Depends on Phase 5.**

Tasks: Write the bias review service that takes the compliance-corrected SOAP note, constructs the bias detection prompt, calls `llama-3.3-70b-versatile`, and parses the bias flag schema. Wire into the pipeline route after compliance completes.

**Exit criteria:** A test note containing the phrase "patient seems overly anxious" returns at least one gender_bias flag.

---

### Phase 7 — Trajectory Scoring (~Day 3–4)
**Owner: Member B. Depends on Phase 3 and 4c. Parallel with Phases 5 and 6.**

Tasks: Write the trajectory scoring engine using the rule-based signal system described in Section 7. Write the analytics routes for trajectory and cognitive load. Wire trajectory computation into the pipeline route so it runs after the parallel agents complete (in parallel with compliance and bias).

**Exit criteria:** `GET /analytics/trajectory/{patient_id}` returns direction, confidence, and watch zones for a patient with 3+ visits. A patient with 2 visits returns a confidence score of 40%.

---

### Phase 8 — Frontend (~Day 2–5, parallel with backend Phases 3–7)
**Owner: Member D. Depends on Phase 1 for auth.**

Tasks in priority order: Auth flow (login page, JWT storage). AudioRecorder component. SSE connection helper. SOAPNote streaming component. PatientCard component. TrajectoryCard component. AnomalyFlag component. DifferentialPanel component. ComplianceBadge component. BiasReviewPanel component. CognitiveLoadNudge component. Wire everything together in the session page. Wire the dashboard patient list.

Member D should build all components against hardcoded mock data first and integrate with live backend endpoints as they become available. The mock data shapes should mirror the exact JSON schemas defined in the system prompt.

---

### Phase 9 — Demo Data and Polish (~Day 5)
**Owner: Everyone. Depends on all phases.**

Tasks: Write a seed script that creates one doctor account, one patient, and 6 visits with progressively worsening data. Visit 1–2: normal. Visit 3: first drift flag appears. Visit 4: anomaly flagged, trajectory starts declining. Visit 5: compliance warning injected. Visit 6: clear downward trajectory with watch zones and a bias flag. Run end-to-end test against the seeded data. Write README with setup instructions.

---

## 10. Environment Variables

### Backend `.env`
```
DATABASE_URL          — asyncpg connection string to Supabase PostgreSQL
REDIS_URL             — Upstash Redis connection string (include ?ssl_cert_reqs=none)
GROQ_API_KEY          — Groq API key for Whisper and LLaMA inference
JWT_SECRET_KEY        — Secret used to sign JWTs (long random string)
SECRET_KEY            — App-level secret (can be the same as JWT_SECRET_KEY)
BACKBLAZE_KEY_ID      — Backblaze B2 application key ID
BACKBLAZE_APP_KEY     — Backblaze B2 application key
BACKBLAZE_BUCKET      — Backblaze B2 bucket name for audio storage
EMBEDDING_MODEL       — all-MiniLM-L6-v2 (can be overridden)
DRIFT_THRESHOLD       — 0.25 (float, cosine distance threshold for drift detection)
COGNITIVE_LOAD_THRESHOLD — 6 (int, session count that triggers the nudge)
```

### Frontend `.env`
```
NEXT_PUBLIC_API_URL   — Backend base URL (no trailing slash)
```

---

## 11. Out of Scope for v1

- EHR integration (Epic, Cerner, any HL7/FHIR)
- Patient-facing portal
- Mobile app
- Multi-language transcription (English only)
- Neo4j drug interaction graph
- Billing and insurance claim generation
- Offline mode
- Real-time multi-doctor collaboration on the same note

---

## 12. Success Metrics for Demo Day

| Metric | Target |
|---|---|
| Full pipeline latency | ≤ 15 seconds from recording stop to complete dashboard |
| SOAP field accuracy on test transcript | ≥ 85% field placement accuracy |
| Trajectory demo | Seeded patient shows ↓ direction with watch zones on visit 4 |
| Compliance catch rate | Catches all 3 injected HIPAA violations in seed data |
| Bias catch rate | Catches both injected biased phrases in seed data |
| Drift detection | Flagged on visit 3 of seeded patient |
| Cognitive load nudge | Appears after 6 sessions logged for the demo doctor account |