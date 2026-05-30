# MedScribe AI — Backend

Hackathon backend for the MedScribe AI clinical assistant. Converts
doctor-patient conversations into structured SOAP notes and wraps a
longitudinal intelligence layer around them. See `PRD.md` and `SYSTEM_PROMPT.md`
for full product context.

This README covers backend setup, migrations, the test suite, and the demo
seed data. AI/ML service implementations (transcription, SOAP generation,
agents) are owned by the AI team and load dynamically into the backend at
runtime — the backend works without them and returns HTTP 503 from any route
that requires a missing service.

---

## Tech Stack

| Layer | Tool |
|---|---|
| Web framework | FastAPI (async) + Uvicorn |
| Database | PostgreSQL 15 + pgvector (Supabase) |
| ORM / migrations | SQLAlchemy 2.0 async (`asyncpg`) + Alembic |
| Auth | JWT (`python-jose`) + bcrypt (`passlib`) |
| Cache + queue | Redis (Upstash) + Celery |
| Object storage | Backblaze B2 (`b2sdk`) |
| Realtime | Server-Sent Events via in-process event bus |
| Tests | pytest, pytest-asyncio, respx, aiosqlite |

---

## Local Setup

### 1. Prerequisites

- Python 3.11+
- Docker Desktop (recommended for PostgreSQL + Redis)
- A virtual environment tool you like (`venv`, `uv`, etc.)

### 2. Clone and create a virtualenv

```bash
git clone https://github.com/dark-14100/mediscribe.git
cd mediscribe/backend
python -m venv .venv
.venv\Scripts\activate          # PowerShell on Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt
```

### 3. Configure environment variables

Copy the template and fill in your secrets:

```bash
cp .env.example .env
```

Required:

| Var | Notes |
|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://user:pass@host:5432/db` |
| `REDIS_URL` | `redis://...` (Upstash needs `?ssl_cert_reqs=none`) |
| `JWT_SECRET_KEY` | Any long random string |

Optional (graceful no-op if absent):

| Var | Default | Used by |
|---|---|---|
| `GROQ_API_KEY` | — | AI team's services (transcription, SOAP, agents) |
| `BACKBLAZE_KEY_ID` / `BACKBLAZE_APP_KEY` / `BACKBLAZE_BUCKET` | — | Audio upload Celery task (falls back to in-memory) |
| `DRIFT_THRESHOLD` | `0.25` | Drift agent (AI team) |
| `COGNITIVE_LOAD_THRESHOLD` | `6` | `/analytics/load` nudge |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated list |

### 4. Bring up Postgres + Redis with Docker Compose

From the repo root:

```bash
docker compose up -d postgres redis
```

This boots the `pgvector/pgvector:pg15` image and a Redis container on
their default ports.

### 5. Run database migrations

```bash
cd backend
alembic upgrade head
```

The initial migration creates the `users`, `patients`, `visits`, and
`visit_embeddings` tables and enables the `vector` extension.

### 6. Start the API

```bash
uvicorn main:app --reload --port 8000
```

Smoke check: `curl http://localhost:8000/healthz` → `{"status":"ok"}`.

### 7. (Optional) Start the Celery worker

```bash
celery -A workers.celery_app worker --loglevel=info
```

Used for: patient-summary cache invalidation and async audio uploads to B2.

---

## Demo Seed Data

Populate the demo doctor + patient + 6 scripted visits described in PRD §11
and §12:

```bash
cd <repo root>
python seed/seed_demo_data.py
```

The script is **idempotent** — running it again wipes the prior demo doctor
(cascades to their patients and visits) and recreates everything fresh.

| Demo identity | Value |
|---|---|
| Doctor email | `dr.demo@example.com` |
| Doctor password | `demo1234` |
| Patient name | `Maria Hernandez` (58F, HTN + T2DM) |
| Visits | 6 across ~130 days, progressively worsening |

PRD §12 success metrics the seed satisfies:

- Visit 3 has the **first drift flag** (`increased_negative_affect`)
- Visit 4 introduces the **first anomaly** + declining trajectory begins
- Visit 5 carries **3 injected HIPAA compliance violations**
- Visit 6 carries **2 bias flags** + a confirmed `direction='down'` trajectory
  with multiple watch zones
- Demo doctor has `session_count_today = 6` so the cognitive-load nudge fires
  on first dashboard load

After insert the script runs the rule-based trajectory engine against the
seeded patient and prints its independent verdict, which must match the
hand-authored direction (`down`).

---

## Running the Test Suite

```bash
cd backend
pytest -v
```

Tests use an in-memory SQLite database, a stubbed Celery `send_task`, an
`InMemoryCache`, and dependency overrides for storage — no external services
are required.

Current coverage at a glance:

| Area | Tests |
|---|---|
| Auth | `test_auth.py` |
| Patient CRUD + caching | `test_patients.py` |
| Visit CRUD + session counter | `test_visits.py` |
| In-process event bus | `test_event_bus.py` |
| Storage (B2 mock) | `test_storage.py` |
| Notes save / sign | `test_notes.py` |
| Pipeline orchestration + SSE | `test_pipeline_routes.py` |
| Trajectory engine (4 signals) | `test_trajectory.py` |
| Analytics routes | `test_analytics.py` |
| Demo seed contract | `test_seed_demo_data.py` |

---

## API Surface

| Route | Method | Notes |
|---|---|---|
| `/healthz` | GET | Liveness probe |
| `/auth/register` | POST | Create doctor or admin user |
| `/auth/login` | POST | Returns a JWT |
| `/patients` | POST, GET | Doctor-scoped; admin sees all |
| `/patients/{id}` | GET | Owner only (or admin) |
| `/patients/{id}/summary` | GET | Cache-aside via Redis |
| `/visits` | POST | Increments `session_count_today` |
| `/visits/{id}` | GET | Owner only (or admin) |
| `/visits/patient/{id}` | GET | Paginated, newest first |
| `/pipeline/transcribe` | POST | Calls AI transcription service; 503 if missing |
| `/pipeline/run` | POST | Orchestrates SOAP → agents → compliance → bias → trajectory; publishes SSE |
| `/pipeline/stream/{visit_id}` | GET | SSE stream, owner only |
| `/pipeline/run-status/{visit_id}` | GET | Persisted pipeline output |
| `/notes/save/{visit_id}` | POST | Persists doctor edits, invalidates summary cache, queues AI embedding |
| `/notes/sign/{visit_id}` | POST | Marks visit immutable |
| `/analytics/trajectory/{patient_id}` | GET | Rule-based trajectory result |
| `/analytics/load` | GET | Daily session count + cognitive-load threshold |

---

## Architecture Notes

- **Backend / AI separation.** `api/routes/pipeline.py` resolves AI services by
  name (`services.transcription`, `services.soap_generator`, etc.). If a
  required service is missing the route returns HTTP 503 with a clear message
  rather than crashing. Optional services (history retrieval, bias review,
  trajectory) gracefully default and the pipeline continues.
- **Trajectory is rule-based, never an LLM call.** `services/trajectory.py`
  implements the four signals from PRD §7 deterministically.
- **SSE without external pub/sub.** `services/event_bus.py` is an in-process
  `asyncio.Queue` registry keyed by visit ID. Fine for a single-process
  uvicorn worker — switch to Redis pub/sub before horizontal scaling.
- **B2 in async context.** `services/storage.py` wraps `b2sdk` (sync) in
  `asyncio.to_thread`. Falls back to `InMemoryStorage` when B2 credentials
  are absent so tests and local runs don't need a bucket.

---

## Project Layout

```
backend/
├── api/routes/      auth, patients, visits, pipeline, notes, analytics
├── core/            config (env), security (JWT), constants
├── db/              base, session, types (dialect-aware), migrations
├── models/          user, patient, visit, embedding (ORM)
├── schemas/         user, patient, visit, pipeline (Pydantic)
├── services/        cache, storage, event_bus, trajectory
├── workers/         celery_app, tasks
├── tests/           pytest suite (10 files, ~94 tests)
├── main.py          FastAPI app factory
├── alembic.ini
├── Dockerfile
└── requirements.txt

seed/
└── seed_demo_data.py     idempotent demo seeder (run from repo root)

docker-compose.yml         postgres (pgvector) + redis + backend + worker
```
