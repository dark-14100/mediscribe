"""Remove all patients (and cascaded visits) for the demo doctor — keeps the login account.

Usage (from repo root, with production DATABASE_URL set):

    python seed/clear_demo_patients.py

Or:

    railway run python seed/clear_demo_patients.py
"""
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "backend"))

from sqlalchemy import delete, func, select  # noqa: E402

from db.session import AsyncSessionLocal  # noqa: E402
from models.patient import Patient  # noqa: E402
from models.user import User  # noqa: E402

DEMO_EMAIL = "dr.demo@example.com"  # keep in sync with seed/seed_demo_data.py

logging.basicConfig(
    level=logging.INFO, format="[clear-demo] %(message)s", stream=sys.stdout
)
log = logging.getLogger("clear_demo")


async def clear_demo_patients() -> int:
    """Delete every patient owned by the demo doctor. Returns rows deleted."""
    async with AsyncSessionLocal() as session:
        doctor = await session.scalar(select(User).where(User.email == DEMO_EMAIL))
        if doctor is None:
            log.warning("no user with email %s — nothing to clear", DEMO_EMAIL)
            return 0

        count = await session.scalar(
            select(func.count()).select_from(Patient).where(Patient.doctor_id == doctor.id)
        )
        await session.execute(delete(Patient).where(Patient.doctor_id == doctor.id))
        doctor.session_count_today = 0
        doctor.last_session_date = None
        await session.commit()
        deleted = count or 0
        log.info(
            "cleared %d patient(s) for %s (doctor_id=%s); visits removed via cascade",
            deleted,
            DEMO_EMAIL,
            doctor.id,
        )
        return deleted


async def _main() -> None:
    await clear_demo_patients()


if __name__ == "__main__":
    asyncio.run(_main())
