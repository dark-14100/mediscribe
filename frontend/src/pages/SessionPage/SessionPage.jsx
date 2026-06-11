import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import AppNav from '../../components/AppNav/AppNav';
import AnomalyFlag from '../../components/AnomalyFlag/AnomalyFlag';
import AudioRecorder from '../../components/AudioRecorder/AudioRecorder';
import BiasReviewPanel from '../../components/BiasReviewPanel/BiasReviewPanel';
import CognitiveLoadNudge from '../../components/CognitiveLoadNudge/CognitiveLoadNudge';
import ComplianceBadge from '../../components/ComplianceBadge/ComplianceBadge';
import ConfirmDialog from '../../components/ConfirmDialog/ConfirmDialog';
import DifferentialPanel from '../../components/DifferentialPanel/DifferentialPanel';
import PatientCard from '../../components/PatientCard/PatientCard';
import PipelineStepper from '../../components/PipelineStepper/PipelineStepper';
import SidePanel from '../../components/SidePanel/SidePanel';
import SOAPNote from '../../components/SOAPNote/SOAPNote';
import TrajectoryCard from '../../components/TrajectoryCard/TrajectoryCard';
import TranscriptPanel from '../../components/TranscriptPanel/TranscriptPanel';
import { useToast } from '../../components/Toast/toastContext.js';
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

// Parse a stored `raw_transcript` string (`[doctor] hello\n[patient] hi`) back
// into structured lines for the transcript panel.
function parseRawTranscript(raw) {
  if (!raw || typeof raw !== 'string') return [];
  return raw
    .split('\n')
    .map((line, i) => {
      const match = line.match(/^\[(doctor|patient)\]\s?(.*)$/i);
      if (!match) return null;
      return { speaker: match[1].toLowerCase(), text: match[2], line_index: i };
    })
    .filter(Boolean);
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
  const navigate = useNavigate();
  const toast = useToast();
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

  const [transcript, setTranscript] = useState([]);
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
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false);
  const [confirmSignOpen, setConfirmSignOpen] = useState(false);
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

        const existingTranscript = parseRawTranscript(visit.raw_transcript);
        if (existingTranscript.length) setTranscript(existingTranscript);

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

      setTranscript(transcript);
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
    setHasUnsavedChanges(true);
  }, []);

  // Warn before leaving with unsaved edits (covers refresh / tab close).
  useEffect(() => {
    if (!hasUnsavedChanges) return undefined;
    function onBeforeUnload(e) {
      e.preventDefault();
      e.returnValue = '';
    }
    window.addEventListener('beforeunload', onBeforeUnload);
    return () => window.removeEventListener('beforeunload', onBeforeUnload);
  }, [hasUnsavedChanges]);

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
              setHasUnsavedChanges(true);
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
      setHasUnsavedChanges(false);
      setPipelineStatus('done');
      toast.success('Draft saved');
    } catch (err) {
      console.error('[SessionPage] save failed:', err);
      setSaveError('Failed to save — please try again.');
      setPipelineStatus('done');
      toast.error('Could not save the note. Please try again.');
    }
  }

  // ── sign off ─────────────────────────────────────────────────────────────

  async function handleConfirmSignOff() {
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
      setHasUnsavedChanges(false);
      setPipelineStatus('signed');
      setConfirmSignOpen(false);
      toast.success('Note signed and locked');
    } catch (err) {
      const already = err?.status === 409;
      if (already) {
        setHasUnsavedChanges(false);
        setPipelineStatus('signed');
        setConfirmSignOpen(false);
        toast.info('This note was already signed.');
      } else {
        console.error('[SessionPage] sign failed:', err);
        setSaveError('Failed to sign — please try again.');
        setPipelineStatus('done');
        setConfirmSignOpen(false);
        toast.error('Could not sign the note. Please try again.');
      }
    }
  }

  // ── derived ──────────────────────────────────────────────────────────────

  const isSigned = pipelineStatus === 'signed';
  const isSaving = pipelineStatus === 'saving' || pipelineStatus === 'signing';
  const recorderDisabled = pipelineStatus === 'running' || isSaving || isSigned;

  const pipelineSteps = useMemo(() => {
    const soapHasContent = SOAP_FIELD_ORDER.some((f) => (soap[f] || '').trim().length > 0);
    const done = [
      transcript.length > 0,
      anomalies.length > 0 || differentials.length > 0,
      visibleFields.size >= SOAP_FIELD_ORDER.length || soapHasContent,
      Boolean(compliance),
    ];
    const labels = ['Transcribe', 'Analyze', 'SOAP note', 'Compliance'];
    const running = pipelineStatus === 'running';
    const errored = pipelineStatus === 'error';
    const firstPending = done.findIndex((d) => !d);

    return labels.map((label, i) => {
      let status = done[i] ? 'done' : 'pending';
      if (!done[i] && i === firstPending) {
        if (errored) status = 'error';
        else if (running) status = 'active';
      }
      return { label, status };
    });
  }, [transcript, anomalies, differentials, visibleFields, soap, compliance, pipelineStatus]);

  const showStepper =
    pipelineStatus === 'running' ||
    pipelineStatus === 'error' ||
    pipelineSteps.some((s) => s.status === 'done');

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

          {showStepper ? <PipelineStepper steps={pipelineSteps} /> : null}

          {pipelineStatus === 'running' && (
            <p className="session-page__pipeline-status">
              Analysing session — results streaming in…
            </p>
          )}

          <TranscriptPanel lines={transcript} />

          <SOAPNote
            soap={soap}
            visibleFields={visibleFields}
            modifiedFields={doctorModifiedFields}
            onChange={isSigned ? undefined : handleSoapChange}
            errored={pipelineStatus === 'error'}
          />

          <ComplianceBadge compliance={compliance} />

          {saveError && <p className="session-page__error">{saveError}</p>}

          {isSigned ? (
            <div className="session-page__signed-card" role="status">
              <div className="session-page__signed-head">
                <span className="session-page__signed-check" aria-hidden="true">
                  ✓
                </span>
                <div>
                  <p className="session-page__signed-title">Note signed and locked</p>
                  <p className="session-page__signed-sub">
                    This visit is finalized and can no longer be edited.
                  </p>
                </div>
              </div>
              <div className="session-page__signed-actions">
                <button
                  type="button"
                  className="session-page__signed-primary"
                  onClick={() => navigate('/patients')}
                >
                  Back to patients
                </button>
                <button
                  type="button"
                  className="session-page__signed-secondary"
                  onClick={() => navigate('/sessions')}
                >
                  View all sessions
                </button>
              </div>
            </div>
          ) : null}

          <div className="session-page__actions">
            {isSigned ? null : !useRealApi ? (
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
                  onClick={() => setConfirmSignOpen(true)}
                  disabled={isSaving}
                >
                  {pipelineStatus === 'signing' ? 'Signing…' : 'Sign Off'}
                </button>
              </>
            )}
          </div>
        </div>

        <aside className="session-page__sidebar">
          <SidePanel
            title="Anomalies"
            count={anomalies.length}
            tone={anomalies.some((a) => a.severity === 'high') ? 'danger' : 'alert'}
            emptyLabel={
              pipelineStatus === 'running' ? 'Analysing…' : 'No anomalies detected.'
            }
          >
            <div className="session-page__anomalies">
              {anomalies.map((a) => (
                <AnomalyFlag key={a.id} anomaly={a} />
              ))}
            </div>
          </SidePanel>

          <DifferentialPanel differentials={differentials} />

          <BiasReviewPanel
            flags={biasFlags}
            dismissed={dismissedBias}
            onAccept={handleAcceptBias}
            onDismiss={handleDismissBias}
          />
        </aside>
      </div>

      <ConfirmDialog
        open={confirmSignOpen}
        title="Sign off this note?"
        message="Signing locks the note permanently — it can no longer be edited. Any unsaved changes will be saved first."
        confirmLabel="Sign & lock"
        cancelLabel="Keep editing"
        busy={pipelineStatus === 'signing'}
        onConfirm={handleConfirmSignOff}
        onCancel={() => setConfirmSignOpen(false)}
      />
    </div>
  );
}
