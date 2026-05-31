import { useCallback, useEffect, useRef, useState } from 'react';
import { useParams } from 'react-router-dom';
import AppNav from '../../components/AppNav/AppNav';
import AnomalyFlag from '../../components/AnomalyFlag/AnomalyFlag';
import AudioRecorder from '../../components/AudioRecorder/AudioRecorder';
import BiasReviewPanel from '../../components/BiasReviewPanel/BiasReviewPanel';
import CognitiveLoadNudge from '../../components/CognitiveLoadNudge/CognitiveLoadNudge';
import ComplianceBadge from '../../components/ComplianceBadge/ComplianceBadge';
import DifferentialPanel from '../../components/DifferentialPanel/DifferentialPanel';
import PatientCard from '../../components/PatientCard/PatientCard';
import SOAPNote from '../../components/SOAPNote/SOAPNote';
import TrajectoryCard from '../../components/TrajectoryCard/TrajectoryCard';
import {
  apiFetch,
  fetchPatient,
  fetchPatientSummary,
  fetchVisit,
  isDemoVisitId,
  readApiError,
} from '../../lib/api.js';
import { connectSSE } from '../../lib/sse.js';
import {
  getInitialTrajectory,
  getSessionPatient,
  parseSSEData,
  simulateSessionSSE,
} from '../../lib/sessionMock.js';
import { JUDGE_DEMO_PATIENT_NAME } from '../../lib/buildPatient.js';
import {
  mapPatientReadToSummary,
  mapSummaryToPatientCard,
  mapVisitToTrajectory,
} from '../../lib/sessionPatient.js';
import './SessionPage.css';

const SOAP_FIELD_ORDER = ['subjective', 'objective', 'assessment', 'plan'];

const EMPTY_SOAP = {
  subjective: '',
  objective: '',
  assessment: '',
  plan: '',
};

// ── helpers ────────────────────────────────────────────────────────────────

function normalizeSoap(payload) {
  const note = payload?.soap_note ?? payload;
  if (!note) return null;
  return {
    subjective: note.subjective?.text ?? note.subjective ?? '',
    objective: note.objective?.text ?? note.objective ?? '',
    assessment: note.assessment?.text ?? note.assessment ?? '',
    plan: note.plan?.text ?? note.plan ?? '',
  };
}

function soapToRequest(soap, doctorModifiedFields) {
  const toField = (text) => ({ text: text ?? '', source_lines: [] });
  return {
    soap_note: {
      subjective: toField(soap.subjective),
      objective: toField(soap.objective),
      assessment: toField(soap.assessment),
      plan: toField(soap.plan),
    },
    doctor_modified_fields: [...doctorModifiedFields],
  };
}

function staggerSoapFields(setVisibleFields, setSoap, soapData) {
  SOAP_FIELD_ORDER.forEach((field, index) => {
    setTimeout(() => {
      setVisibleFields((prev) => new Set([...prev, field]));
      setSoap((prev) => ({ ...prev, [field]: soapData[field] }));
    }, index * 350);
  });
}

// ── component ──────────────────────────────────────────────────────────────

export default function SessionPage() {
  const { visitId } = useParams();
  const apiBase = import.meta.env.VITE_API_URL;
  const useRealApi = Boolean(apiBase) && Boolean(visitId) && !isDemoVisitId(visitId);

  // ── state ────────────────────────────────────────────────────────────────
  const [nudgeDismissed, setNudgeDismissed] = useState(false);
  const [cognitiveLoad, setCognitiveLoad] = useState(null); // {session_count, threshold, threshold_exceeded}

  const [patient, setPatient] = useState(() => (useRealApi ? null : getSessionPatient(visitId)));
  const [trajectory, setTrajectory] = useState(() =>
    useRealApi ? null : getInitialTrajectory(visitId),
  );
  const [sessionLoading, setSessionLoading] = useState(useRealApi);
  const [sessionLoadError, setSessionLoadError] = useState(null);
  const [transcriptError, setTranscriptError] = useState(null);

  const [soap, setSoap] = useState(EMPTY_SOAP);
  const [visibleFields, setVisibleFields] = useState(() => new Set());
  const [doctorModifiedFields, setDoctorModifiedFields] = useState(() => new Set());

  const [anomalies, setAnomalies] = useState([]);
  const [differentials, setDifferentials] = useState([]);
  const [compliance, setCompliance] = useState(null);
  const [biasFlags, setBiasFlags] = useState([]);
  const [dismissedBias, setDismissedBias] = useState(() => new Set());

  const [driftFlag, setDriftFlag] = useState(null);

  const [pipelineStatus, setPipelineStatus] = useState('idle');
  // 'idle' | 'running' | 'done' | 'saving' | 'signing' | 'signed' | 'error'

  const [saveError, setSaveError] = useState(null);
  const sseRef = useRef(null);

  // ── SSE event handlers ───────────────────────────────────────────────────

  const sseHandlers = useRef({
    soap_ready(event) {
      const data = parseSSEData(event);
      const normalized = normalizeSoap(data);
      if (normalized) staggerSoapFields(setVisibleFields, setSoap, normalized);
    },
    anomalies_ready(event) {
      const data = parseSSEData(event);
      if (data?.anomalies) setAnomalies(data.anomalies);
    },
    differentials_ready(event) {
      const data = parseSSEData(event);
      if (data?.differentials) setDifferentials(data.differentials);
    },
    drift_ready(event) {
      const data = parseSSEData(event);
      // Drift influences trajectory's watch zones; we hold the raw flag in state
      // so future UI (e.g. a watch-zone enrichment) can read it without another fetch.
      if (data?.drift_flag !== undefined) {
        setDriftFlag(data.drift_flag);
      }
    },
    compliance_ready(event) {
      const data = parseSSEData(event);
      if (data?.status) {
        setCompliance(data);
      } else if (data?.compliance_status) {
        setCompliance({ status: data.compliance_status, notes: data.compliance_notes ?? [] });
      }
    },
    bias_ready(event) {
      const data = parseSSEData(event);
      const flags = data?.bias_flags ?? data;
      if (Array.isArray(flags)) {
        setBiasFlags(flags.map((f, i) => ({ ...f, id: f.id ?? `bias-${i}` })));
      }
    },
    trajectory_ready(event) {
      const data = parseSSEData(event);
      if (data?.trajectory) {
        setTrajectory(data.trajectory);
        return;
      }
      if (data?.direction) setTrajectory(data);
    },
    pipeline_done() {
      setPipelineStatus('done');
    },
    error(event) {
      const data = parseSSEData(event);
      console.error('[SessionPage] pipeline error:', data?.detail);
      setPipelineStatus('error');
    },
  });

  // ── load visit + patient from API ────────────────────────────────────────

  useEffect(() => {
    if (!useRealApi || !visitId) return;

    let cancelled = false;
    (async () => {
      setSessionLoadError(null);
      setSessionLoading(true);
      try {
        const visit = await fetchVisit(visitId);
        if (cancelled) return;

        let summary;
        try {
          summary = await fetchPatientSummary(visit.patient_id);
        } catch (summaryErr) {
          console.warn('[SessionPage] summary failed, falling back to patient', summaryErr);
          const patient = await fetchPatient(visit.patient_id);
          summary = mapPatientReadToSummary(patient);
        }
        if (cancelled) return;

        setPatient(mapSummaryToPatientCard(summary, visit));
        const traj = mapVisitToTrajectory(visit, summary);
        setTrajectory(traj);

        const existingSoap = normalizeSoap({ soap_note: visit.soap_note });
        if (existingSoap) {
          setSoap(existingSoap);
          setVisibleFields(new Set(SOAP_FIELD_ORDER));
        }

        if (visit.anomalies?.length) setAnomalies(visit.anomalies);
        if (visit.differentials?.length) setDifferentials(visit.differentials);
        if (visit.compliance_status) {
          setCompliance({
            status: visit.compliance_status,
            notes: visit.compliance_notes ?? [],
          });
        }
        if (visit.bias_flags?.length) {
          setBiasFlags(visit.bias_flags.map((f, i) => ({ ...f, id: f.id ?? `bias-${i}` })));
        }
        if (visit.is_signed) setPipelineStatus('signed');
        else if (existingSoap) setPipelineStatus('done');
      } catch (err) {
        console.error('[SessionPage] failed to load visit:', err);
        if (!cancelled) {
          let message = 'Could not load this session from the server.';
          if (err?.response) {
            try {
              message = await readApiError(err.response);
            } catch {
              // keep default
            }
          } else if (err?.status === 401) {
            message = 'Session expired. Sign in again.';
          }
          setSessionLoadError(message);
          setPatient(null);
        }
      } finally {
        if (!cancelled) setSessionLoading(false);
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [visitId, useRealApi]);

  // ── cognitive load ───────────────────────────────────────────────────────

  useEffect(() => {
    if (!useRealApi) return;
    apiFetch('/analytics/load', {}, { retries: 2 })
      .then((r) => r.json())
      .then(setCognitiveLoad)
      .catch((err) => {
        console.warn('[SessionPage] cognitive load unavailable:', err);
      });
  }, [useRealApi]);

  // Surface drift via console for now — the visual element lives in the
  // trajectory watch zones, so there's nothing new to render here.
  useEffect(() => {
    if (driftFlag) {
      console.info('[SessionPage] drift_ready', driftFlag);
    }
  }, [driftFlag]);

  // ── SSE connection on mount (real only) ──────────────────────────────────

  useEffect(() => {
    if (!useRealApi) {
      // Demo mode: staggered mock events
      const conn = simulateSessionSSE(sseHandlers.current, visitId);
      sseRef.current = conn;
      return () => conn.close();
    }

    const sse = connectSSE(visitId, sseHandlers.current);
    sseRef.current = sse;
    sse.source.onerror = () => {
      console.error('[SessionPage] SSE connection failed');
      sse.close();
      if (!import.meta.env.PROD) {
        const conn = simulateSessionSSE(sseHandlers.current, visitId);
        sseRef.current = conn;
      } else {
        setPipelineStatus('error');
      }
    };

    return () => {
      sse.close();
      sseRef.current?.close?.();
    };
  }, [visitId, useRealApi]);

  // ── transcript ready → run pipeline ─────────────────────────────────────

  const handleTranscriptReady = useCallback(
    async (transcript) => {
      if (!useRealApi) return; // mock already simulated
      setTranscriptError(null);
      if (!transcript?.length) {
        setTranscriptError(
          'No transcript returned. Check GROQ_API_KEY on Railway and speak for at least a few seconds.',
        );
        return;
      }

      setPipelineStatus('running');
      try {
        await apiFetch('/pipeline/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ visit_id: visitId, transcript }),
        });
        // SSE events drive the UI; pipeline_done event will flip status to 'done'
      } catch (err) {
        console.error('[SessionPage] pipeline/run failed:', err);
        setPipelineStatus('error');
      }
    },
    [visitId, useRealApi],
  );

  // ── SOAP edits ───────────────────────────────────────────────────────────

  const handleSoapChange = useCallback((key, value) => {
    setSoap((prev) => ({ ...prev, [key]: value }));
    setDoctorModifiedFields((prev) => new Set([...prev, key]));
  }, []);

  // ── bias accept / dismiss ────────────────────────────────────────────────

  const handleAcceptBias = useCallback(
    (id) => {
      const flag = biasFlags.find((f) => f.id === id);
      if (flag) {
        setSoap((prev) => {
          const updated = { ...prev };
          // Search all four fields — not just subjective
          for (const field of SOAP_FIELD_ORDER) {
            if (updated[field].includes(flag.phrase)) {
              updated[field] = updated[field].replace(flag.phrase, flag.suggested_rewrite);
              setDoctorModifiedFields((m) => new Set([...m, field]));
              break;
            }
          }
          return updated;
        });
      }
      setDismissedBias((prev) => new Set([...prev, id]));
    },
    [biasFlags],
  );

  const handleDismissBias = useCallback((id) => {
    setDismissedBias((prev) => new Set([...prev, id]));
  }, []);

  // ── save draft ───────────────────────────────────────────────────────────

  function applyComplianceFromVisit(visit) {
    if (!visit?.compliance_status) return;
    setCompliance({
      status: visit.compliance_status,
      notes: visit.compliance_notes ?? [],
    });
  }

  async function handleSaveDraft() {
    if (!useRealApi) return;
    setSaveError(null);
    setPipelineStatus('saving');
    try {
      const res = await apiFetch(`/notes/save/${visitId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(soapToRequest(soap, doctorModifiedFields)),
      });
      const saved = await res.json();
      applyComplianceFromVisit(saved);
      setPipelineStatus('done');
    } catch (err) {
      console.error('[SessionPage] save failed:', err);
      setSaveError('Failed to save — please try again.');
      setPipelineStatus('done');
    }
  }

  // ── sign off ─────────────────────────────────────────────────────────────

  async function handleSignOff() {
    if (!useRealApi) return;
    if (pipelineStatus === 'signed') return;
    setSaveError(null);

    // Save latest edits first, then sign
    try {
      setPipelineStatus('signing');
      const saveRes = await apiFetch(`/notes/save/${visitId}`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(soapToRequest(soap, doctorModifiedFields)),
      });
      const saved = await saveRes.json();
      applyComplianceFromVisit(saved);
      await apiFetch(`/notes/sign/${visitId}`, { method: 'POST' });
      setPipelineStatus('signed');
    } catch (err) {
      const already = err?.status === 409;
      if (already) {
        setPipelineStatus('signed');
      } else {
        console.error('[SessionPage] sign failed:', err);
        setSaveError('Failed to sign — please try again.');
        setPipelineStatus('done');
      }
    }
  }

  // ── derived ──────────────────────────────────────────────────────────────

  const isSigned = pipelineStatus === 'signed';
  const isSaving = pipelineStatus === 'saving' || pipelineStatus === 'signing';
  const recorderDisabled = pipelineStatus === 'running' || isSaving || isSigned;

  const showNudge =
    !nudgeDismissed &&
    (cognitiveLoad?.threshold_exceeded ?? false);

  // ── render ───────────────────────────────────────────────────────────────

  return (
    <div className="session-page">
      <AppNav />

      <div className="session-page__body">
        <div className="session-page__main">
          {showNudge && (
            <CognitiveLoadNudge
              sessionCount={cognitiveLoad.session_count}
              onDismiss={() => setNudgeDismissed(true)}
            />
          )}

          {sessionLoadError ? (
            <p className="session-page__error" role="alert">
              {sessionLoadError}
            </p>
          ) : null}

          {sessionLoading ? (
            <p className="session-page__pipeline-status">Loading session…</p>
          ) : null}

          <div className="session-page__cards-row">
            {patient ? (
              <PatientCard patient={patient} variant="session" />
            ) : (
              <p className="session-page__panel-empty">Patient data unavailable</p>
            )}
            <div className="session-page__trajectory-wrap">
              <TrajectoryCard trajectory={trajectory} />
            </div>
          </div>

          <AudioRecorder
            visitId={visitId}
            onTranscriptReady={handleTranscriptReady}
            disabled={recorderDisabled || sessionLoading || !patient}
          />

          {transcriptError ? (
            <p className="session-page__error" role="alert">
              {transcriptError}
            </p>
          ) : null}

          {pipelineStatus === 'running' && (
            <p className="session-page__pipeline-status">
              Analysing session — results streaming in…
            </p>
          )}

          <SOAPNote
            soap={soap}
            visibleFields={visibleFields}
            onChange={isSigned ? undefined : handleSoapChange}
          />

          <ComplianceBadge compliance={compliance} />

          {useRealApi &&
          patient?.name === JUDGE_DEMO_PATIENT_NAME &&
          compliance?.status === 'fail' ? (
            <p className="session-page__demo-hint" role="note">
              Judge tip: fill in Assessment and Plan with clinical detail, then Save Draft — compliance
              re-runs on save.
            </p>
          ) : null}

          {saveError && <p className="session-page__error">{saveError}</p>}

          <div className="session-page__actions">
            {isSigned ? (
              <span className="session-page__signed-badge">✓ Note signed</span>
            ) : !useRealApi ? (
              <p className="session-page__demo-hint">
                Demo session: connect the API and open a real visit to save or sign notes.
              </p>
            ) : (
              <>
                <button
                  type="button"
                  className="session-page__draft"
                  onClick={handleSaveDraft}
                  disabled={isSaving}
                >
                  {pipelineStatus === 'saving' ? 'Saving…' : 'Save Draft'}
                </button>
                <button
                  type="button"
                  className="session-page__sign"
                  onClick={handleSignOff}
                  disabled={isSaving}
                >
                  {pipelineStatus === 'signing' ? 'Signing…' : 'Sign Off'}
                </button>
              </>
            )}
          </div>
        </div>

        <aside className="session-page__sidebar">
          <section className="session-page__panel-section">
            <h3 className="session-page__panel-title">Anomalies</h3>
            <div className="session-page__anomalies">
              {anomalies.length > 0 ? (
                anomalies.map((a) => <AnomalyFlag key={a.id} anomaly={a} />)
              ) : (
                <p className="session-page__panel-empty">Waiting for pipeline…</p>
              )}
            </div>
          </section>

          <DifferentialPanel differentials={differentials} />

          <BiasReviewPanel
            flags={biasFlags}
            dismissed={dismissedBias}
            onAccept={handleAcceptBias}
            onDismiss={handleDismissBias}
          />
        </aside>
      </div>
    </div>
  );
}
