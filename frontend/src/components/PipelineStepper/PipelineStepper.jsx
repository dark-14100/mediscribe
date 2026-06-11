import './PipelineStepper.css';

/**
 * Horizontal progress stepper for the AI pipeline.
 *
 * Props:
 *   steps – [{ label, status }] where status ∈ 'pending' | 'active' | 'done' | 'error'
 */
export default function PipelineStepper({ steps }) {
  if (!steps?.length) return null;

  return (
    <ol className="pipeline-stepper" aria-label="Analysis progress">
      {steps.map((step, i) => (
        <li key={step.label} className={`pipeline-stepper__step pipeline-stepper__step--${step.status}`}>
          <span className="pipeline-stepper__marker" aria-hidden="true">
            {step.status === 'done' ? '✓' : step.status === 'error' ? '!' : i + 1}
          </span>
          <span className="pipeline-stepper__label">{step.label}</span>
          {i < steps.length - 1 ? (
            <span className="pipeline-stepper__bar" aria-hidden="true" />
          ) : null}
        </li>
      ))}
    </ol>
  );
}
