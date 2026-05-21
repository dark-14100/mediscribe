import { useCallback, useEffect, useState } from 'react';
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
import { connectSSE } from '../../lib/sse.js';
import {
  getInitialTrajectory,
  getSessionPatient,
  parseSSEData,
  simulateSessionSSE,
} from '../../lib/sessionMock.js';
import './SessionPage.css';

const EMPTY_SOAP = {
  subjective: '',
  objective: '',
  assessment: '',
  plan: '',
};

const SOAP_FIELD_ORDER = ['subjective', 'objective', 'assessment', 'plan'];

function normalizeSoap(payload) {
  const note = payload?.soap_note ?? payload;
  if (!note) {
    return null;
  }
  return {
    subjective: note.subjective?.text ?? note.subjective ?? '',
    objective: note.objective?.text ?? note.objective ?? '',
    assessment: note.assessment?.text ?? note.assessment ?? '',
    plan: note.plan?.text ?? note.plan ?? '',
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

export default function SessionPage() {
  const { visitId } = useParams();
  const [nudgeDismissed, setNudgeDismissed] = useState(false);
  const [patient] = useState(() => getSessionPatient(visitId));
  const [trajectory, setTrajectory] = useState(() => getInitialTrajectory(visitId));
  const [soap, setSoap] = useState(EMPTY_SOAP);
  const [visibleFields, setVisibleFields] = useState(() => new Set());
  const [anomalies, setAnomalies] = useState([]);
  const [differentials, setDifferentials] = useState([]);
  const [compliance, setCompliance] = useState(null);
  const [biasFlags, setBiasFlags] = useState([]);
  const [dismissedBias, setDismissedBias] = useState(() => new Set());

  const handleSoapChange = useCallback((key, value) => {
    setSoap((prev) => ({ ...prev, [key]: value }));
  }, []);

  const handleAcceptBias = useCallback((id) => {
    const flag = biasFlags.find((f) => f.id === id);
    if (flag) {
      setSoap((prev) => ({
        ...prev,
        subjective: prev.subjective.replace(flag.phrase, flag.suggested_rewrite),
      }));
    }
    setDismissedBias((prev) => new Set([...prev, id]));
  }, [biasFlags]);

  const handleDismissBias = useCallback((id) => {
    setDismissedBias((prev) => new Set([...prev, id]));
  }, []);

  useEffect(() => {
    const handlers = {
      soap_ready(event) {
        const data = parseSSEData(event);
        const normalized = normalizeSoap(data);
        if (normalized) {
          staggerSoapFields(setVisibleFields, setSoap, normalized);
        }
      },
      anomalies_ready(event) {
        const data = parseSSEData(event);
        if (data?.anomalies) {
          setAnomalies(data.anomalies);
        }
      },
      differentials_ready(event) {
        const data = parseSSEData(event);
        if (data?.differentials) {
          setDifferentials(data.differentials);
        }
      },
      compliance_ready(event) {
        const data = parseSSEData(event);
        if (data?.status) {
          setCompliance(data);
        } else if (data?.compliance_status) {
          setCompliance({
            status: data.compliance_status,
            notes: data.compliance_notes ?? [],
          });
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
        if (data?.direction) {
          setTrajectory(data);
        }
      },
    };

    let connection = null;
    let simStarted = false;
    const apiBase = import.meta.env.VITE_API_URL;

    function startSimulation() {
      if (!simStarted) {
        simStarted = true;
        connection = simulateSessionSSE(handlers, visitId);
      }
    }

    if (apiBase && visitId) {
      const sse = connectSSE(visitId, handlers);
      sse.source.onerror = () => {
        sse.close();
        startSimulation();
      };
      connection = sse;
      const fallbackTimer = setTimeout(startSimulation, 2000);
      return () => {
        clearTimeout(fallbackTimer);
        sse.close();
        connection?.close?.();
      };
    }

    startSimulation();
    return () => connection?.close?.();
  }, [visitId]);

  function handleSaveDraft() {
    /* demo — wire to POST /notes/save when backend is ready */
  }

  function handleSignOff() {
    /* demo — wire to POST /notes/sign when backend is ready */
  }

  return (
    <div className="session-page">
      <AppNav />

      <div className="session-page__body">
        <div className="session-page__main">
          {!nudgeDismissed ? (
            <CognitiveLoadNudge sessionCount={6} onDismiss={() => setNudgeDismissed(true)} />
          ) : null}

          <div className="session-page__cards-row">
            <PatientCard patient={patient} variant="session" />
            <div className="session-page__trajectory-wrap">
              <TrajectoryCard trajectory={trajectory} />
            </div>
          </div>

          <AudioRecorder />

          <SOAPNote soap={soap} visibleFields={visibleFields} onChange={handleSoapChange} />

          <ComplianceBadge compliance={compliance} />

          <div className="session-page__actions">
            <button type="button" className="session-page__draft" onClick={handleSaveDraft}>
              Save Draft
            </button>
            <button type="button" className="session-page__sign" onClick={handleSignOff}>
              Sign Off
            </button>
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
