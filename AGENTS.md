# AGENTS.md — working guide for AI agents on MediScribe

Read this first. It captures how the repo is laid out, how to run/test things, the
conventions to follow, and the deployment gotchas that have actually bitten us.

## What this is

MediScribe is an AI medical-scribe platform: it transcribes a doctor–patient
visit, generates a SOAP note, runs a panel of analyst agents (anomaly,
differential, drift, compliance, bias, trajectory), and remembers patients
across visits. The differentiators are **cross-visit memory** and a **trust
layer** (grounding gate + de-identification).

Read these for context before large changes:
- `BUILD_PLAN.md` — roadmap (Phase 1 trust → Phase 2 clinic integration → Phase 3 scale) + architecture diagrams.
- `GROUNDING_GATE_SPEC.md`, `DEID_SPEC.md` — shipped trust features (Phase A each).
- `EVAL_HARNESS_SPEC.md`, `GROUNDING_PHASE_BC_SPEC.md` — specced, building next.

## Repo layout

```
backend/        FastAPI app (Python 3.11, async)
  api/routes/   HTTP routes (auth, patients, visits, pipeline, notes, analytics)
  api/deps.py   auth dependencies (cookie OR bearer token)
  core/         config, constants, security, cookies, csrf, ratelimit, audit
  services/     AI + infra services (soap_generator, grounding, deid, groq_retry, ...)
  schemas/      Pydantic models
  models/       SQLAlchemy ORM
  workers/      Celery tasks
  tests/        pytest suite
  eval/         offline evaluation harness (quality / hallucination / PHI-leak)
frontend/       React + Vite SPA (deployed to Vercel)
seed/           demo data seeding scripts
docker-compose.yml   local stack: postgres(pgvector) + redis + backend + worker
```

## Running locally

The whole stack runs via Docker (preferred — matches prod):

```bash
docker compose up --build        # postgres + redis + backend(:8000) + worker
```

IMPORTANT: after changing `backend/requirements.txt`, you MUST rebuild
(`docker compose up --build`) — a plain `up` reuses the old image and the new
dependency will be missing (this exact issue took the API down once).

Backend without Docker (needs Python 3.11 + a venv + a local Postgres/Redis):

```bash
cd backend
python -m venv .venv && .venv/Scripts/activate    # Windows
pip install -r requirements.txt
uvicorn main:app --reload                          # http://localhost:8000
```

Frontend:

```bash
cd frontend
npm install
npm run dev      # Vite dev server (default port 5173)
```

Create `frontend/.env` with `VITE_API_URL=http://localhost:8000`. The backend's
`CORS_ORIGINS` already allows `:3000` and `:5173`.

## Testing & linting

```bash
# Backend (from backend/)
pytest                       # full suite (uses aiosqlite; rate limiter disabled when ENVIRONMENT=test)
pytest tests/test_x.py -q    # a single file
ruff check .                 # lint

# Eval harness (from backend/)
python -m eval.run --dataset eval/datasets/smoke.jsonl   # replay mode, no Groq/DB

# Frontend (from frontend/)
npm run lint
```

Notes:
- Tests stub the AI services and use SQLite, so they don't need Groq or Postgres.
- `eval/run.py` sets safe env defaults for replay so it runs with zero setup; `--live` needs `GROQ_API_KEY`.

CI (`.github/workflows/ci.yml`) runs on every push to `main` and every PR:
- **backend-tests** — full `pytest` against SQLite.
- **eval-harness** — the replay-mode regression gate (fails the build if note quality
  drops or any PHI leaks); uploads the scorecard as an artifact.
- **frontend** — `npm ci` + lint + build.

## Conventions (follow these)

- **Config:** ALL env access goes through `core/config.py` (`settings`). Never call
  `os.environ.get()` in service/route code.
- **Constants:** SSE event names, SOAP field names, etc. live in `core/constants.py`.
- **Pipeline resilience:** every optional pipeline step runs through `_maybe_call(...)`
  in `api/routes/pipeline.py`, which degrades gracefully and appends to
  `degraded_steps` (surfaced to the UI). Don't let a step crash the whole run.
- **SSE:** the pipeline streams each step's result over the event bus; the frontend
  listens in `frontend/src/lib/sse.js` (event names must match `core/constants.py`).
- **Trust patterns:**
  - Grounding (`services/grounding.py`) verifies SOAP claims vs the transcript; result
    persisted to `visit.soap_audit_trail["grounding"]`, gated by `GROUNDING_MODE`.
  - De-id (`services/deid.py`) strips PHI before any LLM call and re-identifies outputs;
    the reversible map is in-memory only — only a PHI-free report is persisted.
- **Auth:** cookie-based (HttpOnly access token + readable CSRF token, double-submit).
  `api/deps.py` also accepts `Authorization: Bearer` (API clients/tests, CSRF-exempt).
- **Comments:** explain *why*, not *what*. No narration comments. Run `ruff`.
- **No new deps** unless necessary; prefer reusing existing ones.

## Deployment

- **Backend → Railway** (Docker, built from `backend/Dockerfile`).
- **Frontend → Vercel** (root directory = `frontend/`; `frontend/vercel.json` has the
  SPA rewrite so client-side routes don't 404).

Required production env (Railway) — and the gotchas that have broken us:
- `ENVIRONMENT=production` — REQUIRED. Without it, auth cookies are `SameSite=Lax`
  and are NOT sent on cross-site requests (Vercel ↔ Railway), so login "succeeds"
  (200) but `/auth/me` returns 401 and the user bounces to login.
- `ENVIRONMENT=production` also activates fail-fast startup guards in `main.py`:
  - `JWT_SECRET_KEY` must be strong (≥32 chars, no "secret"/"change_me") or boot fails.
  - `REDIS_URL` must be `rediss://` (TLS) unless local, or boot fails.
- `CORS_ORIGINS` must list the exact frontend origin (e.g. `https://<app>.vercel.app`).
- Frontend (Vercel): `VITE_API_URL=https://<railway-app>` (and it must be HTTPS to
  avoid mixed-content blocking).

Cross-site cookies are inherently fragile (Safari/Chrome third-party cookie
blocking). If they ever break despite correct config, the durable fix is to make the
API same-origin via a Vercel rewrite (`/api/*` → Railway) and set `VITE_API_URL=/api`.

## Environment / shell

- Dev shell here is **PowerShell** — chain commands with `;`, not `&&`. No `head`/`tail`/`cat`.
- Git: after a self-contained change, commit with a concise message and
  `git push origin <branch>` (see `.cursor/rules/auto-commit-push.mdc`). Don't commit
  secrets (`backend/.env`).
