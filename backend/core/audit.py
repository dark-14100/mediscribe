"""Lightweight PHI-access audit logging.

Emits a structured log line to the dedicated ``medscribe.audit`` logger whenever
a user reads protected health information. This gives an append-only trail (who
accessed which resource, when) for incident review without standing up a full
audit-table subsystem. Ship these logs to your retained, tamper-evident log sink
in production.
"""
import logging

log = logging.getLogger("medscribe.audit")


def log_phi_access(
    *,
    user_id: str,
    action: str,
    resource_type: str,
    resource_id: str,
) -> None:
    """Record a single PHI access event.

    Args:
        user_id: ID of the authenticated user performing the access.
        action: What was done, e.g. "read" or "download".
        resource_type: The kind of resource, e.g. "visit" or "audio".
        resource_id: ID of the specific resource accessed.
    """
    log.info(
        "phi_access user_id=%s action=%s resource_type=%s resource_id=%s",
        user_id,
        action,
        resource_type,
        resource_id,
    )
