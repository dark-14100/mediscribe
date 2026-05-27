import { useState } from 'react';
import './AddPatientModal.css';

const EMPTY_FORM = {
  fullName: '',
  dob: '',
  gender: '',
  mrn: '',
  condition: '',
};

export default function AddPatientModal({ open, onClose, onSubmit }) {
  const [form, setForm] = useState(EMPTY_FORM);

  if (!open) {
    return null;
  }

  function handleChange(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  function handleSubmit(event) {
    event.preventDefault();
    onSubmit(form);
    setForm(EMPTY_FORM);
  }

  function handleClose() {
    setForm(EMPTY_FORM);
    onClose();
  }

  function handleBackdropClick(event) {
    if (event.target === event.currentTarget) {
      handleClose();
    }
  }

  return (
    <div
      className="add-patient-modal__backdrop"
      onClick={handleBackdropClick}
      role="presentation"
    >
      <div
        className="add-patient-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="add-patient-modal-title"
      >
        <header className="add-patient-modal__header">
          <h2 id="add-patient-modal-title">Add patient</h2>
          <button
            type="button"
            className="add-patient-modal__close"
            onClick={handleClose}
            aria-label="Close"
          >
            ×
          </button>
        </header>

        <form className="add-patient-modal__form" onSubmit={handleSubmit}>
          <label className="add-patient-modal__field">
            <span>Full name</span>
            <input
              type="text"
              value={form.fullName}
              onChange={(e) => handleChange('fullName', e.target.value)}
              required
            />
          </label>

          <label className="add-patient-modal__field">
            <span>Date of birth</span>
            <input
              type="date"
              value={form.dob}
              onChange={(e) => handleChange('dob', e.target.value)}
              required
            />
          </label>

          <label className="add-patient-modal__field">
            <span>Gender</span>
            <select
              value={form.gender}
              onChange={(e) => handleChange('gender', e.target.value)}
              required
            >
              <option value="">Select gender</option>
              <option value="female">Female</option>
              <option value="male">Male</option>
              <option value="other">Other</option>
            </select>
          </label>

          <label className="add-patient-modal__field">
            <span>MRN</span>
            <input
              type="text"
              value={form.mrn}
              onChange={(e) => handleChange('mrn', e.target.value)}
              placeholder="MRN-00000"
              required
            />
          </label>

          <label className="add-patient-modal__field">
            <span>Primary condition</span>
            <input
              type="text"
              value={form.condition}
              onChange={(e) => handleChange('condition', e.target.value)}
              required
            />
          </label>

          <div className="add-patient-modal__actions">
            <button type="button" className="add-patient-modal__cancel" onClick={handleClose}>
              Cancel
            </button>
            <button type="submit" className="add-patient-modal__submit">
              Add patient
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
