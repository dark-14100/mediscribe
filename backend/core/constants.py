"""Reference data and named constants used across the pipeline.

Anything tunable via environment lives in core/config.py instead.
"""
from typing import Final

# --- User roles ---
DOCTOR_ROLE: Final[str] = "doctor"
ADMIN_ROLE: Final[str] = "admin"
ALLOWED_ROLES: Final[tuple[str, ...]] = (DOCTOR_ROLE, ADMIN_ROLE)

# --- Drift detection keyword lists (drift_agent.py uses these for direction labeling) ---
PAIN_KEYWORDS: Final[tuple[str, ...]] = (
    "pain",
    "hurt",
    "ache",
    "aching",
    "burning",
    "throbbing",
    "stabbing",
    "sharp",
    "worse",
    "sore",
    "tender",
)

NEGATIVE_AFFECT_KEYWORDS: Final[tuple[str, ...]] = (
    "hopeless",
    "tired",
    "exhausted",
    "can't",
    "cannot",
    "never",
    "always bad",
    "afraid",
    "scared",
    "anxious",
    "depressed",
    "useless",
    "worthless",
)

# --- Compliance reference: condensed ICD-10 primary care codes (compliance.py prompt context) ---
ICD10_PRIMARY_CARE: Final[dict[str, str]] = {
    "J06.9": "Acute upper respiratory infection, unspecified",
    "R51": "Headache",
    "K21.9": "Gastro-esophageal reflux disease without esophagitis",
    "I10": "Essential (primary) hypertension",
    "E11.9": "Type 2 diabetes mellitus without complications",
    "M54.5": "Low back pain",
    "R10.9": "Unspecified abdominal pain",
    "J45.909": "Unspecified asthma, uncomplicated",
    "N39.0": "Urinary tract infection, site not specified",
    "R05": "Cough",
    "R50.9": "Fever, unspecified",
    "F41.9": "Anxiety disorder, unspecified",
    "F32.9": "Major depressive disorder, single episode, unspecified",
    "H66.90": "Otitis media, unspecified, unspecified ear",
    "J02.9": "Acute pharyngitis, unspecified",
    "R07.9": "Chest pain, unspecified",
    "R42": "Dizziness and giddiness",
    "G43.909": "Migraine, unspecified, not intractable, without status migrainosus",
    "L20.9": "Atopic dermatitis, unspecified",
    "Z00.00": "Encounter for general adult medical examination without abnormal findings",
}

# --- CPT / E&M reference (coding.py prompt context) ---
# Office-visit Evaluation & Management codes (the most common primary-care
# billing decision) plus a few frequent procedures. Not exhaustive — anchors the
# model and lets us fill descriptions for known codes.
CPT_EM_REFERENCE: Final[dict[str, str]] = {
    # Established patient office visit
    "99211": "Established patient, minimal (may not require physician)",
    "99212": "Established patient, straightforward complexity",
    "99213": "Established patient, low complexity",
    "99214": "Established patient, moderate complexity",
    "99215": "Established patient, high complexity",
    # New patient office visit
    "99202": "New patient, straightforward complexity",
    "99203": "New patient, low complexity",
    "99204": "New patient, moderate complexity",
    "99205": "New patient, high complexity",
    # Common primary-care procedures
    "93000": "Electrocardiogram, complete",
    "36415": "Routine venipuncture (blood draw)",
    "90471": "Immunization administration",
    "94010": "Spirometry",
}

# Valid office-visit E&M codes per patient class (coding.py validation).
EM_CODES_ESTABLISHED: Final[tuple[str, ...]] = (
    "99211", "99212", "99213", "99214", "99215",
)
EM_CODES_NEW: Final[tuple[str, ...]] = ("99202", "99203", "99204", "99205")

# --- HIPAA documentation checklist (compliance.py prompt context) ---
HIPAA_DOCUMENTATION_CHECKLIST: Final[tuple[str, ...]] = (
    "Patient identifier present in note",
    "Date of service documented",
    "Provider identifier present",
    "Reason for visit clearly stated",
    "Plan of care with disposition or follow-up",
)

# --- SSE event names (pipeline route emits these in order) ---
EVENT_SOAP_READY: Final[str] = "soap_ready"
EVENT_GROUNDING_READY: Final[str] = "grounding_ready"
EVENT_ANOMALIES_READY: Final[str] = "anomalies_ready"
EVENT_DIFFERENTIALS_READY: Final[str] = "differentials_ready"
EVENT_DRIFT_READY: Final[str] = "drift_ready"
EVENT_COMPLIANCE_READY: Final[str] = "compliance_ready"
EVENT_CODING_READY: Final[str] = "coding_ready"
EVENT_BIAS_READY: Final[str] = "bias_ready"
EVENT_TRAJECTORY_READY: Final[str] = "trajectory_ready"
EVENT_PIPELINE_DONE: Final[str] = "pipeline_done"
EVENT_ERROR: Final[str] = "error"

# --- Pipeline-related fixed values ---
SOAP_FIELDS: Final[tuple[str, ...]] = ("subjective", "objective", "assessment", "plan")
EMBEDDING_DIM: Final[int] = 384
TRAJECTORY_MAX_VISITS: Final[int] = 5
PATIENT_SUMMARY_CACHE_KEY: Final[str] = "patient_summary:{patient_id}"
