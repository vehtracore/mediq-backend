
import logging
from datetime import datetime, timezone
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User
from app.models.doctor import Doctor
from app.models.vault import AIChatSummary, ConsultationRecord
from app.schemas.vault import AISummaryCreate, VaultHistoryResponse
from app.api import deps

logger = logging.getLogger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# POST /vault/ai-summary
# ---------------------------------------------------------------------------

@router.post(
    "/ai-summary",
    response_model=VaultHistoryResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save an AI chat summary to the patient's Health Vault",
)
def create_ai_summary(
    payload: AISummaryCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> VaultHistoryResponse:
    """
    Persists a structured AI chat summary for the authenticated patient.
    The patient_id is injected server-side from the JWT — never trusted from
    the request body.
    """
    now = datetime.now(timezone.utc)

    record = AIChatSummary(
        patient_id=current_user.id,
        topic=payload.topic,
        summary_text=payload.summary_text,
        created_at=now,
    )
    db.add(record)
    db.commit()
    db.refresh(record)

    logger.info(
        "[Vault] AI summary saved — patient_id=%s topic=%r id=%s",
        current_user.id,
        payload.topic,
        record.id,
    )

    return VaultHistoryResponse(
        id=record.id,
        type="ai_summary",
        date=record.created_at,
        doctor_name=None,
        topic_or_reason=record.topic,
        details=record.summary_text,
        prescriptions=None,
        referrals=None,
    )


# ---------------------------------------------------------------------------
# GET /vault/history
# ---------------------------------------------------------------------------

@router.get(
    "/history",
    response_model=List[VaultHistoryResponse],
    summary="Retrieve the full Health Vault history for the authenticated patient",
)
def get_vault_history(
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> List[VaultHistoryResponse]:
    """
    Returns a merged, time-sorted list of:
      1. All AI chat summaries for the patient.
      2. All consultation records for the patient, with the doctor's name
         resolved via a JOIN on the doctors table.

    Results are ordered newest-first by date.
    """
    patient_id = current_user.id
    results: List[VaultHistoryResponse] = []

    # ── 1. AI chat summaries ─────────────────────────────────────────────────
    summaries = (
        db.query(AIChatSummary)
        .filter(AIChatSummary.patient_id == patient_id)
        .all()
    )

    for s in summaries:
        results.append(
            VaultHistoryResponse(
                id=s.id,
                type="ai_summary",
                date=s.created_at,
                doctor_name=None,
                topic_or_reason=s.topic,
                details=s.summary_text,
                prescriptions=None,
                referrals=None,
            )
        )

    # ── 2. Consultation records (joined to doctors for the doctor's name) ────
    consultations = (
        db.query(ConsultationRecord, Doctor)
        .outerjoin(Doctor, ConsultationRecord.doctor_id == Doctor.id)
        .filter(ConsultationRecord.patient_id == patient_id)
        .all()
    )

    for consult, doctor in consultations:
        doctor_name = doctor.full_name if doctor else None

        # topic_or_reason: use clinical_notes as a brief label (first 120 chars)
        # or fall back to a generic string when notes are absent.
        notes_preview = None
        if consult.clinical_notes:
            notes_preview = (
                consult.clinical_notes[:120] + "…"
                if len(consult.clinical_notes) > 120
                else consult.clinical_notes
            )
        topic_or_reason = notes_preview or "Consultation record"

        results.append(
            VaultHistoryResponse(
                id=consult.id,
                type="consultation",
                date=consult.created_at,
                doctor_name=doctor_name,
                topic_or_reason=topic_or_reason,
                details=consult.clinical_notes,
                prescriptions=consult.prescriptions,
                referrals=consult.referrals,
            )
        )

    # ── 3. Sort combined list newest-first ───────────────────────────────────
    results.sort(key=lambda item: item.date, reverse=True)

    logger.info(
        "[Vault] History fetched — patient_id=%s total=%d (summaries=%d, consultations=%d)",
        patient_id,
        len(results),
        len(summaries),
        len(consultations),
    )

    return results
