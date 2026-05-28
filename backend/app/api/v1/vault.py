
import io
import logging
from datetime import datetime, timezone
from typing import List
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from fpdf import FPDF
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.limiter import limiter
from app.models.user import User
from app.models.doctor import Doctor
from app.models.vault import AIChatSummary, ConsultationRecord
from app.schemas.vault import AISummaryCreate, VaultExportRequest, VaultHistoryResponse
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


# ---------------------------------------------------------------------------
# POST /vault/export
# ---------------------------------------------------------------------------

@router.post(
    "/export",
    summary="Export selected Health Vault records as a PDF",
    response_class=StreamingResponse,
)
@limiter.limit("5/minute")
def export_vault_records(
    request: Request,
    payload: VaultExportRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> StreamingResponse:
    """
    Generates an on-the-fly PDF containing the requested vault records.

    Security: only records that belong to the authenticated patient are
    included — records owned by other patients are silently excluded even
    if their IDs are supplied in the request body.

    Returns a downloadable PDF file named ``vehtr_records.pdf``.
    """
    patient_id = current_user.id
    requested_ids = payload.record_ids  # list[UUID]

    # ── 1. Fetch AI chat summaries that belong to this patient ───────────────
    ai_summaries = (
        db.query(AIChatSummary)
        .filter(
            AIChatSummary.id.in_(requested_ids),
            AIChatSummary.patient_id == patient_id,
        )
        .all()
    )

    # ── 2. Fetch consultation records that belong to this patient ────────────
    consultations = (
        db.query(ConsultationRecord)
        .filter(
            ConsultationRecord.id.in_(requested_ids),
            ConsultationRecord.patient_id == patient_id,
        )
        .all()
    )

    if not ai_summaries and not consultations:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No matching vault records found for the provided IDs.",
        )

    # ── 3. Build a unified, time-sorted list of records ──────────────────────
    # Each entry: (created_at, title, date_str, body)
    entries: list[tuple] = []

    for s in ai_summaries:
        title = f"AI Health Summary — {s.topic}"
        date_str = s.created_at.strftime("%d %b %Y, %H:%M UTC")
        body = s.summary_text or ""
        entries.append((s.created_at, title, date_str, body))

    for c in consultations:
        title = "Consultation Record"
        date_str = c.created_at.strftime("%d %b %Y, %H:%M UTC")
        body_parts = []
        if c.clinical_notes:
            body_parts.append(f"Clinical Notes:\n{c.clinical_notes}")
        if c.prescriptions:
            body_parts.append(f"Prescriptions:\n{c.prescriptions}")
        if c.referrals:
            body_parts.append(f"Referrals:\n{c.referrals}")
        body = "\n\n".join(body_parts) if body_parts else "No clinical details recorded."
        entries.append((c.created_at, title, date_str, body))

    # Sort newest-first
    entries.sort(key=lambda e: e[0], reverse=True)

    # ── 4. Build the PDF ─────────────────────────────────────────────────────
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    for idx, (_, title, date_str, body) in enumerate(entries):
        pdf.add_page()

        # ── Header bar ──────────────────────────────────────────────────────
        pdf.set_fill_color(30, 90, 180)
        pdf.rect(0, 0, 210, 18, style="F")
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(10, 4)
        pdf.cell(0, 10, "VehtraCore — Health Vault Export", ln=False)

        # ── Record title ─────────────────────────────────────────────────────
        pdf.set_xy(10, 25)
        pdf.set_font("Helvetica", "B", 14)
        pdf.set_text_color(20, 20, 60)
        pdf.multi_cell(0, 8, title)

        # ── Date ─────────────────────────────────────────────────────────────
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(100, 100, 120)
        pdf.cell(0, 6, date_str, ln=True)

        # ── Divider ──────────────────────────────────────────────────────────
        pdf.set_draw_color(200, 200, 220)
        pdf.ln(2)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)

        # ── Body text ─────────────────────────────────────────────────────────
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(30, 30, 50)
        safe_body = body.encode("latin-1", "replace").decode("latin-1")
        pdf.multi_cell(0, 6, safe_body)

        # ── Footer ───────────────────────────────────────────────────────────
        pdf.set_y(-15)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(150, 150, 160)
        pdf.cell(0, 8, f"Page {idx + 1} of {len(entries)}  |  Confidential — VehtraCore MediQ", align="C")

    # ── 5. Serialise to bytes and stream back ─────────────────────────────────
    pdf_bytes = pdf.output()  # returns bytearray in fpdf2
    buffer = io.BytesIO(bytes(pdf_bytes))
    buffer.seek(0)

    logger.info(
        "[Vault] PDF export — patient_id=%s records=%d",
        patient_id,
        len(entries),
    )

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": "attachment; filename=vehtr_records.pdf"},
    )


# ---------------------------------------------------------------------------
# DELETE /vault/ai-summary/{summary_id}
# ---------------------------------------------------------------------------

@router.delete(
    "/ai-summary/{summary_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete an AI chat summary from the patient's Health Vault",
)
def delete_ai_summary(
    summary_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> dict:
    """
    Permanently removes a single AI chat summary that belongs to the
    authenticated patient.

    Security: the query filters on both ``id`` and ``patient_id`` so a
    patient can never delete another patient's record even if they know
    the UUID.
    """
    record = (
        db.query(AIChatSummary)
        .filter(
            AIChatSummary.id == summary_id,
            AIChatSummary.patient_id == current_user.id,
        )
        .first()
    )

    if record is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Record not found.",
        )

    db.delete(record)
    db.commit()

    logger.info(
        "[Vault] AI summary deleted — patient_id=%s summary_id=%s",
        current_user.id,
        summary_id,
    )

    return {"detail": "Summary deleted successfully."}
