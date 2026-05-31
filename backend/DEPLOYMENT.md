# MedScribe AI — Deployment Guide

Step-by-step setup for every external service the app uses, followed by how
to deploy the backend (Railway or Render) and the frontend (Vercel).

> **Order matters.** Get Supabase + Upstash + Backblaze set up first, collect
> all the credentials, then deploy the backend, then deploy the frontend.

---

## 1. Supabase (PostgreSQL database)

1. Go to [supabase.com](https://supabase.com) → **New project**.
2. Choose a region close to your users. Set a strong database password and save it.
3. Wait for provisioning (~2 min).
4. In the sidebar go to **Project Settings → Database**.
5. Scroll to **Connection string → URI**. Switch the tab to **Transaction pooler** (port 6543) — this is the connection pool-safe URL.  
   It looks like:
   ```
   postgresql://postgres.xxxx:PASSWORD@aws-0-ap-south-1.pooler.supabase.com:6543/postgres
   ```
6. For asyncpg, change `postgresql://` to `postgresql+asyncpg://`. That's your `DATABASE_URL`.
7. Use the **Transaction pooler** URI (port **6543**), not the direct session connection on 5432, for Railway/serverless backends. The app disables asyncpg prepared statements for PgBouncer compatibility (see `db/session.py`).
8. Enable the **pgvector** extension:
   - Sidebar → **Database → Extensions**.
   - Search for `vector` → toggle it **ON**.
   - ⚠️ The app migration (`001_initial_schema.py`) also runs `CREATE EXTENSION IF NOT EXISTS vector`, so this is belt-and-suspenders.

**Credential to save:**
```
DATABASE_URL=postgresql+asyncpg://postgres.XXXX:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres
```

---

## 2. Upstash (Redis — Celery broker + cache)

1. Go to [upstash.com](https://upstash.com) → **Create database**.
2. Type: **Redis**. Region: same as Supabase. Enable **TLS**. Click Create.
3. On the database page, find the **REST URL** section and copy the **Redis CLI URL**. It looks like:
   ```
   rediss://default:PASSWORD@REGION.upstash.io:6379
   ```
4. Append `?ssl_cert_reqs=none` to suppress the SSL cert validation error that
   the Python redis client raises in some environments:
   ```
   rediss://default:PASSWORD@REGION.upstash.io:6379?ssl_cert_reqs=none
   ```

**Credential to save:**
```
REDIS_URL=rediss://default:PASSWORD@REGION.upstash.io:6379?ssl_cert_reqs=none
```

---

## 3. Backblaze B2 (audio file storage)

1. Go to [backblaze.com](https://www.backblaze.com/cloud-storage.html) → sign up → **Cloud Storage**.
2. Sidebar → **Buckets → Create a Bucket**.
   - Bucket name: `mediscribe-audio` (or anything; save the exact name).
   - Files in bucket: **Public** (so audio URLs are directly accessible).
   - Default encryption: off is fine for hackathon.
3. Go to **App Keys → Add a New Application Key**.
   - Name: `mediscribe-backend`
   - Allow access to bucket: select `mediscribe-audio`
   - Type of access: **Read and Write**
   - Click **Create New Key**.
4. Copy the **keyID** and **applicationKey** immediately — the app key is shown only once.

**Credentials to save:**
```
BACKBLAZE_KEY_ID=your_keyID_here
BACKBLAZE_APP_KEY=your_applicationKey_here
BACKBLAZE_BUCKET=mediscribe-audio
```

---

## 4. Groq (LLM + Whisper inference)

1. Go to [console.groq.com](https://console.groq.com) → sign up.
2. Sidebar → **API Keys → Create API Key**.
3. Name it anything, copy the key.

**Credential to save:**
```
GROQ_API_KEY=gsk_...
```

Models the app uses (no config needed — already hardcoded in the services):
- Whisper: `whisper-large-v3-turbo` (transcription)
- LLaMA: `llama-3.3-70b-versatile` (SOAP + agents)

---

## 5. Generate secret keys

You need two random strings (can be the same value):

```bash
# Run this in any terminal with Python
python -c "import secrets; print(secrets.token_hex(32))"
```

Run it twice, use the outputs as `JWT_SECRET_KEY` and `SECRET_KEY`.

---

## 6. Deploy the backend

### Option A — Railway (recommended, fastest)

1. Go to [railway.app](https://railway.app) → **New Project → Deploy from GitHub repo**.
2. Connect your GitHub account and select the `mediscribe` repository.
3. Railway detects `backend/Dockerfile`. In project settings set the **root directory** to `backend/`.
4. Go to **Variables** and add every env var from the table below.
5. Go to **Settings → Networking → Generate Domain**. Copy the URL (e.g. `https://mediscribe-backend.up.railway.app`).
6. After deploy succeeds, run migrations (one-time):
   - Railway dashboard → your service → **Shell** tab, or
   - Locally: `DATABASE_URL=<prod_url> alembic upgrade head`
7. Swagger UI will be live at `https://YOUR_RAILWAY_URL/docs`.

### Option B — Render

1. Go to [render.com](https://render.com) → **New → Web Service**.
2. Connect your GitHub repo. Set:
   - **Root directory:** `backend`
   - **Runtime:** Docker
   - **Dockerfile path:** `Dockerfile`
   - **Start command:** leave blank (uses `CMD` from Dockerfile)
3. Add all env vars in the **Environment** tab.
4. Click **Deploy**.
5. After deploy, open the **Shell** tab and run `alembic upgrade head`.
6. Free tier spins down after 15 min of inactivity — fine for hackathon, but the first request after sleep takes ~30 s.

---

## 7. Full environment variable reference

Set all of these in your Railway/Render dashboard. Never commit real values to git.

| Variable | Value | Where to get it |
|---|---|---|
| `DATABASE_URL` | `postgresql+asyncpg://...` | Supabase §1 |
| `REDIS_URL` | `rediss://default:...?ssl_cert_reqs=none` | Upstash §2 |
| `JWT_SECRET_KEY` | long random hex string | Generated in §5 |
| `SECRET_KEY` | long random hex string | Generated in §5 |
| `JWT_ALGORITHM` | `HS256` | Keep default |
| `JWT_EXPIRE_MINUTES` | `1440` | 24 h; adjust if needed |
| `GROQ_API_KEY` | `gsk_...` | Groq §4 |
| `BACKBLAZE_KEY_ID` | `003...` | Backblaze §3 |
| `BACKBLAZE_APP_KEY` | `K003...` | Backblaze §3 |
| `BACKBLAZE_BUCKET` | `mediscribe-audio` | Backblaze §3 |
| `EMBEDDING_MODEL` | `all-MiniLM-L6-v2` | Keep default |
| `DRIFT_THRESHOLD` | `0.25` | Keep default |
| `COGNITIVE_LOAD_THRESHOLD` | `6` | Keep default |
| `CORS_ORIGINS` | `https://YOUR_VERCEL_URL,http://localhost:3000` | Set after Vercel deploy |

---

## 8. Run database migrations

Must be run **once** after first deploy and after any schema change:

```bash
# From your local machine with the production DATABASE_URL set
DATABASE_URL="postgresql+asyncpg://..." alembic upgrade head

# Or from the Railway/Render shell tab
alembic upgrade head
```

Migration file: `backend/db/migrations/versions/001_initial_schema.py`  
Creates: `users`, `patients`, `visits`, `visit_embeddings` tables + pgvector extension + ivfflat indexes.

---

## 9. Seed demo data (optional but strongly recommended for demo day)

Once the backend is live and migrations are done:

```bash
# From local machine with production DATABASE_URL + REDIS_URL in your shell env
DATABASE_URL="postgresql+asyncpg://..." REDIS_URL="rediss://..." \
  python seed/seed_demo_data.py
```

This creates:
- **Doctor:** `dr.demo@example.com` / `demo1234`
- **Patient:** Maria Hernandez (6 visits, declining trajectory — demo-ready)

Re-running wipes the prior demo data and recreates everything fresh.

---

## 10. Deploy the frontend (Vercel)

1. Go to [vercel.com](https://vercel.com) → **New Project → Import Git Repository**.
2. Select `mediscribe`. Set **Root Directory** to `frontend/`.
3. Framework preset: depends on your setup — Vite (select **Vite**) or CRA (select **Create React App**).
4. Under **Environment Variables** add:
   ```
   VITE_API_URL=https://YOUR_RAILWAY_URL
   ```
   (or `REACT_APP_API_URL=...` if using CRA)
5. Click **Deploy**. Vercel gives you a URL like `https://mediscribe.vercel.app`.
6. **Go back to the backend** (Railway/Render) and update `CORS_ORIGINS`:
   ```
   CORS_ORIGINS=https://mediscribe.vercel.app,http://localhost:3000
   ```
   Redeploy the backend (Railway auto-redeploys on env var change).

---

## 11. Celery worker (for background tasks)

The main web service handles HTTP. A separate Celery worker handles:
- `upload_audio_to_b2` — uploads visit audio to Backblaze B2
- `invalidate_patient_summary` — clears Redis summary cache
- `embed_visit` — generates and stores SOAP + patient-speech embeddings

### On Railway
1. In your Railway project, click **+ New Service → GitHub Repo** (same repo, same `backend/` root directory).
2. Override the start command to:
   ```
   celery -A workers.celery_app worker --loglevel=info --concurrency=2
   ```
3. Add the **same env vars** as the web service (it needs `DATABASE_URL`, `REDIS_URL`, `BACKBLAZE_*`, `GROQ_API_KEY`).

### On Render
1. New service → **Background Worker** (not Web Service).
2. Same Docker setup as the web service.
3. Start command: `celery -A workers.celery_app worker --loglevel=info --concurrency=2`
4. Same env vars.

> For the hackathon, the worker is optional if you don't mind B2 uploads and
> embeddings not running. The main pipeline (SOAP, agents, SSE) works without
> it. Visits just won't have `audio_url` populated and RAG history retrieval
> will return empty results until embeddings are generated.

---

## 12. Verify everything is working

Once all services are live:

```bash
# 1. Health check
curl https://YOUR_BACKEND_URL/healthz
# → {"status":"ok","service":"mediscribe-api"}

# 2. Swagger UI
open https://YOUR_BACKEND_URL/docs

# 3. Register a user
curl -X POST https://YOUR_BACKEND_URL/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"test1234","full_name":"Test","role":"doctor"}'

# 4. Login
curl -X POST https://YOUR_BACKEND_URL/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@test.com","password":"test1234"}'
# → {"access_token":"...","token_type":"bearer"}
```

If health check passes and login returns a token, the backend is wired correctly.

---

## 13. Common issues

| Problem | Likely cause | Fix |
|---|---|---|
| `asyncpg` SSL error on Supabase | Missing `+asyncpg` in URL | Make sure URL starts `postgresql+asyncpg://` |
| `InvalidSQLStatementNameError` / prepared statement does not exist | PgBouncer (Supabase pooler) + asyncpg cache | Use port **6543** pooler URL; deploy latest backend (`NullPool` + `statement_cache_size=0` in `db/session.py`) |
| Intermittent 500 on `GET /analytics/load` or `/visits/{id}` | Same PgBouncer issue under load | Redeploy backend; avoid trailing-slash URLs like `/patients/` |
| Redis `SSL: CERTIFICATE_VERIFY_FAILED` | Missing query param | Append `?ssl_cert_reqs=none` to `REDIS_URL` |
| `relation "users" does not exist` | Migrations haven't run | Run `alembic upgrade head` |
| `extension "vector" does not exist` | pgvector not enabled | Enable in Supabase Dashboard → Extensions |
| CORS error from frontend | `CORS_ORIGINS` missing Vercel URL | Update env var, redeploy backend |
| B2 upload silently falls back to in-memory | B2 credentials missing or wrong | Check all three `BACKBLAZE_*` vars |
| Celery tasks queued but never run | Worker not deployed | Deploy the worker service (§11) |
| First request after Render sleep takes 30s | Free tier spin-down | Upgrade to paid, or use Railway which doesn't spin down |
