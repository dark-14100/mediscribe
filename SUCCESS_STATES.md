# Success & Feedback States — Coverage Audit

*Before we build the big features (grounding gate, EHR write-back, etc.), this documents every place the app should tell the user "this worked / this is loading / this failed / there's nothing here / this is only partly done" — what's already built, what's missing, and how important each gap is.*

Last updated: 2026-06-12 · Companion to `BUILD_PLAN.md`.

---

## 1. What "success states" means here (plain English)

A "state" is the visual feedback the app gives so the user is never left guessing. We track **five kinds**:

| State | Plain meaning | Typical UI |
|---|---|---|
| **Loading** | "Working on it, hang on." | Skeletons, spinners, "Saving…" |
| **Success** | "That worked." | Toast (a small pop-up), a green check, a confirmation card |
| **Error** | "That failed, here's why / what to do." | Red banner, toast, inline message |
| **Empty** | "There's nothing here yet." | An empty-state card with a call to action |
| **Degraded** | "It worked, but **only partly** — some pieces are missing." | A warning banner listing what's incomplete |

**Jargon used below:**
- **Toast** — a small temporary pop-up message (we have a `ToastProvider` with `success` / `error` / `info`).
- **SSE** — the live feed from server to browser during the AI pipeline (see `BUILD_PLAN.md`).
- **`degraded_steps`** — a list the backend already sends naming which AI steps failed but were skipped so the rest could finish. This is the heart of the "Degraded" state.
- **Skeleton** — grey placeholder boxes shown while real data loads.

## 2. Magnitude scale (how important is each gap)

| Magnitude | Meaning | Why |
|---|---|---|
| **P0 — critical** | Affects safety or trust. A doctor could act on wrong/incomplete info without knowing. | Must fix before big features. |
| **P1 — important** | Noticeable UX gap; user confusion or dead-ends, but not unsafe. | Fix soon. |
| **P2 — polish** | Minor; missing confirmation or a silent non-critical failure. | Nice to have. |

---

## 3. The headline finding

**Most success/feedback states are already implemented** — the app is in good shape. There is **one P0 gap** worth fixing before we build anything big:

> The backend already computes and sends **`degraded_steps`** (e.g. "the anomaly agent failed but we finished the note"), but the **frontend ignores it**. So when a note is only *partially* generated, the doctor is shown a normal, complete-looking note with **no warning**. For a clinical tool, that's a trust/safety issue.

Everything else is either already done or low-magnitude polish.

---

## 4. Coverage matrix (by surface)

Legend: ✅ implemented · ⚠️ partial · ❌ missing

### 4.1 Login (`LoginPage.jsx`)

| State | Status | Notes | Magnitude |
|---|---|---|---|
| Loading | ✅ | Button shows "Signing in…", disabled while submitting | — |
| Error | ✅ | Mapped messages for network / credentials / 404 / server; missing-config warning | — |
| Success | ✅ (implicit) | Navigates straight to dashboard on success | — |
| Empty / Degraded | n/a | Not applicable to a login form | — |

**Verdict: complete.**

### 4.2 Dashboard (`DashboardPage.jsx`)

| State | Status | Notes | Magnitude |
|---|---|---|---|
| Loading | ✅ | Skeleton cards + skeleton rows | — |
| Empty | ✅ | "No patients yet" / "No sessions yet" with CTA | — |
| Error (patients) | ✅ | Inline error banner + 401 → sign-out redirect | — |
| Error (recent visits) | ⚠️ | Failure is **silent** (only `console.warn`); list just shows empty | P2 |
| Success | ✅ | "Opening…" state on session open | — |
| Degraded | ❌ | No pipeline degradation surfaced here (lives on Session) | — |

**Verdict: solid. One P2: recent-visits load failure is invisible.**

### 4.3 Patients (`PatientsPage.jsx`)

| State | Status | Notes | Magnitude |
|---|---|---|---|
| Loading | ✅ | `PatientRegistry` gets a `loading` flag | — |
| Empty | ✅ | Handled inside registry | — |
| Error (load) | ✅ | Inline error banner; 401 → sign-out | — |
| Error (create) | ⚠️ | Sets an error banner, but reuses the page-level `loadError` slot; no toast | P2 |
| Success (create) | ❌ | New patient is added to the list, but **no "Patient added" toast** | P2 |

**Verdict: works. P2 polish: add a success toast + dedicated create-error feedback.**

### 4.4 Sessions list (`SessionsPage.jsx`)

| State | Status | Notes | Magnitude |
|---|---|---|---|
| Loading | ✅ | Skeleton rows | — |
| Empty | ✅ | Full empty-state card + filtered-empty ("No draft sessions") | — |
| Error | ✅ | Inline error banner | — |
| Success / Degraded | n/a | Read-only list | — |

**Verdict: complete.**

### 4.5 Session — the workhorse (`SessionPage.jsx` + `AudioRecorder.jsx`)

This screen has the richest state handling in the app.

| Interaction | State | Status | Notes | Magnitude |
|---|---|---|---|---|
| Load visit | Loading | ✅ | "Loading session…" | — |
| Load visit | Error | ✅ | Inline alert with server message | — |
| Load visit | Empty | ✅ | "Patient data unavailable" fallback | — |
| Record audio | Loading/active | ✅ | idle / recording / transcribing / error labels + live meter | — |
| Transcribe | Error | ✅ | Too-short guard, no-speech guard, API error message | — |
| Run pipeline | Loading | ✅ | `pipelineStatus='running'` + stepper + "Analysing…" | — |
| Run pipeline | Per-step progress | ✅ | Stepper marks Transcribe / Analyze / SOAP / Compliance | — |
| Run pipeline | **Hard failure** | ⚠️ | Status flips to `error`, stepper + SOAP show error, **but no explicit toast/banner with a retry action** | P1 |
| Run pipeline | **Degraded (partial)** | ❌ | Backend sends `degraded_steps` in the `pipeline_done` event + `/run` response; **frontend discards it**. No "partial note" warning. | **P0** |
| Per-agent results | Empty vs failed | ⚠️ | A degraded agent shows the same "No anomalies detected." as a genuinely clean result — **misleading** | P1 |
| Save draft | Loading | ✅ | "Saving…" | — |
| Save draft | Success | ✅ | `toast.success('Draft saved')` | — |
| Save draft | Error | ✅ | Inline `saveError` + `toast.error` | — |
| Sign off | Loading | ✅ | "Signing…" + confirm dialog `busy` | — |
| Sign off | Success | ✅ | Signed card + `toast.success` | — |
| Sign off | Already-signed | ✅ | 409 handled → `toast.info('already signed')` | — |
| Sign off | Error | ✅ | Inline + `toast.error` | — |
| Unsaved changes | Guard | ✅ | `beforeunload` warning | — |

**Verdict: strong, with one P0 and two P1 gaps — all centered on *partial/failed pipeline runs*.**

### 4.6 Global plumbing

| Concern | Status | Notes | Magnitude |
|---|---|---|---|
| Toast system | ✅ | `success` / `error` / `info`, auto-dismiss, accessible (`aria-live`) | — |
| 401 / session expiry | ✅ | `apiFetch` throws 401 → pages sign out + redirect | — |
| Network unreachable | ✅ | `formatApiLoadError` returns a friendly "can't reach API" | — |
| GET auto-retry | ✅ | `apiFetch` retries GET on 500 (with backoff) | — |
| SSE connection drop | ⚠️ | In prod, flips to `error`; no auto-reconnect / "reconnecting…" state | P1 |

---

## 5. The to-do list (only the gaps), by magnitude

> **Update 2026-06-12:** **All listed gaps are now implemented.** P0 #1 (partial-note banner from `degraded_steps`), P1 #2 (panels distinguish failed vs empty), P1 #3 ("Analysis failed" banner + toast + Retry), P1 #4 (SSE "Reconnecting…" state with bounded retry and run-status recovery), P2 #5 ("Patient added" / create-error toasts), and P2 #6 (dashboard recent-sessions load-failure note).

### P0 — do before big features
1. ✅ **Surface `degraded_steps` on the Session page.** When the `pipeline_done` event (or `/run` response) carries a non-empty `degraded_steps`, show a clear **warning banner**: "This note is partial — the following steps couldn't complete: …". This is the frontend half of work already done on the backend, and the "quick win" flagged in `BUILD_PLAN.md`.

### P1 — important UX
2. ✅ **Distinguish "failed agent" from "clean result"** in the side panels (Anomalies / Differentials / Bias). If a step is in `degraded_steps`, show "Couldn't analyze — try re-running" instead of "No anomalies detected."
3. ✅ **Explicit pipeline-failure feedback.** On a hard `error`, show a toast/banner with a **Retry** action, not just a colored stepper.
4. ✅ **SSE reconnect state.** Show "Reconnecting…" and attempt a reconnect instead of silently dropping to `error` in production.

### P2 — polish
5. ✅ **"Patient added" success toast** on create (and a dedicated create-error message).
6. ✅ **Dashboard recent-visits load failure** should show a small inline note instead of failing silently.

---

## 6. Recommended scope for "implement success states"

The cleanest, highest-value bundle to implement **now** (and what I'd suggest we ship before the big features):

- **P0 #1** (degraded banner) — required for trust/safety.
- **P1 #2 + #3** (failed-vs-empty agents, pipeline retry) — they're the same theme as P0 and small once the degraded data is wired through.

That bundle makes the **entire pipeline honest about partial results** — which is exactly the foundation the grounding gate (next big feature) builds on. P1 #4 and the P2 items can follow as polish.

---

## 7. Status check (the answer to "is it already implemented?")

- **Loading, empty, error, and success states across Login / Dashboard / Patients / Sessions / Save / Sign: already implemented.** ✅
- **Degraded / partial-result state: NOT implemented on the frontend** (backend already provides the data). ❌ — this is the one real gap.
- A handful of P1/P2 polish items remain.

**Proposed next step:** implement the **P0 + the two related P1 items** (degraded banner + honest agent panels + pipeline retry). Say the word and I'll proceed.
