
import io
import hashlib
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import List
from uuid import UUID, uuid5

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from fpdf import FPDF
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.limiter import limiter
from app.models.user import User
from app.models.doctor import Doctor
from app.models.vault import (
    AIChatSummary,
    AISummarySaveIdempotency,
    ConsultationRecord,
)
from app.schemas.vault import (
    AISummarySaveRequest,
    VaultExportRequest,
    VaultHistoryResponse,
)
from app.api import deps
from app.api.v1.ai_consent import require_active_ai_consent
from app.services.ai_request_guard import (
    acquire_ai_request_lease,
    ai_request_digest,
    enforce_ai_save_rate_limit,
    get_ai_save_result,
    release_ai_request_lease,
    store_ai_save_result,
)
from app.services.ai_summary_service import (
    AISummaryGenerationError,
    AISummaryInputError,
    SummaryTurn,
    generate_ai_vault_summary,
)
from app.services.ai_usage import (
    enforce_ai_text_usage_available,
    record_successful_ai_text_usage,
)
from app.services.subscription_entitlement import has_active_paid_entitlement

logger = logging.getLogger(__name__)

router = APIRouter()

_AI_SUMMARY_SAVE_NAMESPACE = UUID("a9c9f8d6-1bf6-4f7d-b0f5-e461665af16a")


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _raise_stale_summary_conflict() -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail=(
            "This saved conversation was updated elsewhere. Your current chat "
            "is still available; refresh the saved conversation before saving."
        ),
    )


def _summary_response(record: AIChatSummary) -> VaultHistoryResponse:
    return VaultHistoryResponse(
        id=record.id,
        type="ai_summary",
        date=record.updated_at or record.created_at,
        doctor_name=None,
        topic_or_reason=record.topic,
        details=record.summary_text,
        source=record.source,
        doctor_review_status=record.doctor_review_status,
        reviewed_by_doctor_id=record.reviewed_by_doctor_id,
        reviewed_at=record.reviewed_at,
        created_at=record.created_at,
        updated_at=record.updated_at,
        prescriptions=None,
        referrals=None,
    )


def _owned_summary(
    db: Session,
    summary_id: UUID,
    user_id: int,
) -> AIChatSummary | None:
    return (
        db.query(AIChatSummary)
        .filter(
            AIChatSummary.id == summary_id,
            AIChatSummary.patient_id == user_id,
        )
        .first()
    )


def _new_summary_id(user_id: int, request_id: str) -> UUID:
    return uuid5(_AI_SUMMARY_SAVE_NAMESPACE, f"{user_id}:{request_id}")


def _owned_save_idempotency(
    db: Session,
    user_id: int,
    request_key_digest: str,
) -> AISummarySaveIdempotency | None:
    return (
        db.query(AISummarySaveIdempotency)
        .filter(
            AISummarySaveIdempotency.patient_id == user_id,
            AISummarySaveIdempotency.request_key_digest == request_key_digest,
        )
        .first()
    )


def _fingerprint_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _as_utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _save_request_fingerprint(
    user_id: int,
    payload: AISummarySaveRequest,
) -> str:
    identity = {
        "user_id": user_id,
        "turns": [
            {"role": turn.role, "text": turn.text}
            for turn in payload.turns
        ],
        "source_summary_id": (
            str(payload.source_summary_id) if payload.source_summary_id else None
        ),
        "source_updated_at": _fingerprint_datetime(payload.source_updated_at),
    }
    canonical = json.dumps(
        identity,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _raise_idempotency_conflict() -> None:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="This idempotency key was already used for a different summary save.",
    )


_AI_TEXT_USAGE_FIELDS = (
    "chat_blocked_until",
    "burst_start_time",
    "burst_chat_count",
    "monthly_chat_count",
    "monthly_chat_image_count",
    "last_chat_month_reset",
    "rolling_chat_count",
    "rolling_chat_image_count",
    "rolling_chat_window_start",
)


def _capture_ai_text_usage_state(user: User) -> dict[str, object]:
    return {
        field: getattr(user, field, None)
        for field in _AI_TEXT_USAGE_FIELDS
    }


def _restore_ai_text_usage_state(user: User, state: dict[str, object]) -> None:
    for field, value in state.items():
        setattr(user, field, value)


@router.post(
    "/ai-summary/save",
    response_model=VaultHistoryResponse,
    summary="Generate and save a bounded AI conversation summary",
)
@limiter.limit("3/minute")
async def save_ai_summary(
    request: Request,
    payload: AISummarySaveRequest,
    x_ai_request_id: str = Header(
        alias="X-AI-Request-ID",
        min_length=8,
        max_length=128,
    ),
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> VaultHistoryResponse:
    """Own validation, generation, metering, and persistence server-side."""
    if not has_active_paid_entitlement(current_user):
        logger.info(
            "[Vault] AI summary save denied — plan=free quota_outcome=not_consumed"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Saving AI conversations is available on Premium and Family plans.",
        )
    require_active_ai_consent(current_user)

    request_fingerprint = _save_request_fingerprint(current_user.id, payload)
    request_key_digest = ai_request_digest(x_ai_request_id)
    cached_summary_id = get_ai_save_result(
        current_user.id,
        x_ai_request_id,
        request_fingerprint,
    )
    if cached_summary_id:
        try:
            cached = _owned_summary(db, UUID(cached_summary_id), current_user.id)
        except ValueError:
            cached = None
        if cached is not None:
            return _summary_response(cached)

    idempotency = _owned_save_idempotency(
        db,
        current_user.id,
        request_key_digest,
    )
    if idempotency is not None:
        if idempotency.request_fingerprint != request_fingerprint:
            _raise_idempotency_conflict()
        existing = _owned_summary(db, idempotency.summary_id, current_user.id)
        if existing is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This saved conversation is no longer available.",
            )
        store_ai_save_result(
            current_user.id,
            x_ai_request_id,
            str(existing.id),
            request_fingerprint,
        )
        return _summary_response(existing)

    new_summary_id = None
    source = None
    if payload.source_summary_id is None:
        new_summary_id = _new_summary_id(current_user.id, x_ai_request_id)
        existing = _owned_summary(db, new_summary_id, current_user.id)
        if existing is not None:
            if (
                getattr(existing, "save_request_fingerprint", None)
                != request_fingerprint
            ):
                _raise_idempotency_conflict()
            store_ai_save_result(
                current_user.id,
                x_ai_request_id,
                str(existing.id),
                request_fingerprint,
            )
            return _summary_response(existing)
    else:
        source = _owned_summary(db, payload.source_summary_id, current_user.id)
        if source is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="This saved conversation is no longer available.",
            )
        if _as_utc(source.updated_at) != _as_utc(payload.source_updated_at):
            _raise_stale_summary_conflict()

    enforce_ai_save_rate_limit(current_user.id)
    lease = acquire_ai_request_lease(current_user.id, x_ai_request_id)
    usage_state_before_commit = None
    usage_committed = False
    try:
        usage_now = datetime.now(timezone.utc).replace(tzinfo=None)
        enforce_ai_text_usage_available(current_user, usage_now, db)
        turns = [
            SummaryTurn(role=turn.role, text=turn.text)
            for turn in payload.turns
        ]
        generated = await generate_ai_vault_summary(
            turns,
            historical_summary=source.summary_text if source is not None else None,
        )

        now = datetime.now(timezone.utc)
        if source is None:
            record = AIChatSummary(
                id=new_summary_id,
                patient_id=current_user.id,
                topic="AI Symptom Analysis",
                summary_text=generated.text,
                source="ai_generated",
                save_request_fingerprint=request_fingerprint,
                created_at=now,
                updated_at=now,
            )
            db.add(record)
        else:
            if now <= _as_utc(source.updated_at):
                now = _as_utc(source.updated_at) + timedelta(microseconds=1)
            updated_rows = (
                db.query(AIChatSummary)
                .filter(
                    AIChatSummary.id == source.id,
                    AIChatSummary.patient_id == current_user.id,
                    AIChatSummary.updated_at == payload.source_updated_at,
                )
                .update(
                    {
                        AIChatSummary.summary_text: generated.text,
                        AIChatSummary.updated_at: now,
                    },
                    synchronize_session="fetch",
                )
            )
            if updated_rows != 1:
                db.rollback()
                _raise_stale_summary_conflict()
            record = source

        db.add(
            AISummarySaveIdempotency(
                patient_id=current_user.id,
                request_key_digest=request_key_digest,
                request_fingerprint=request_fingerprint,
                summary_id=record.id,
                created_at=now,
            )
        )
        usage_state_before_commit = _capture_ai_text_usage_state(current_user)
        record_successful_ai_text_usage(current_user)
        db.add(current_user)
        db.commit()
        usage_committed = True
        lease.completed = True
        store_ai_save_result(
            current_user.id,
            x_ai_request_id,
            str(record.id),
            request_fingerprint,
        )
        db.refresh(record)
        logger.info(
            "[Vault] AI summary save completed — patient_id=%s summary_id=%s continuation=%s",
            current_user.id,
            record.id,
            source is not None,
        )
        return _summary_response(record)
    except HTTPException:
        if usage_state_before_commit is not None and not usage_committed:
            _restore_ai_text_usage_state(current_user, usage_state_before_commit)
        raise
    except AISummaryInputError:
        db.rollback()
        if usage_state_before_commit is not None and not usage_committed:
            _restore_ai_text_usage_state(current_user, usage_state_before_commit)
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail="This conversation is too large to summarise safely.",
        ) from None
    except AISummaryGenerationError:
        db.rollback()
        if usage_state_before_commit is not None and not usage_committed:
            _restore_ai_text_usage_state(current_user, usage_state_before_commit)
        logger.error(
            "[Vault] AI summary generation failed — patient_id=%s",
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The summary could not be saved. Please try again.",
        ) from None
    except IntegrityError:
        db.rollback()
        if usage_state_before_commit is not None and not usage_committed:
            _restore_ai_text_usage_state(current_user, usage_state_before_commit)
        if new_summary_id is not None:
            existing = _owned_summary(db, new_summary_id, current_user.id)
            if (
                existing is not None
                and getattr(existing, "save_request_fingerprint", None)
                == request_fingerprint
            ):
                lease.completed = True
                store_ai_save_result(
                    current_user.id,
                    x_ai_request_id,
                    str(existing.id),
                    request_fingerprint,
                )
                return _summary_response(existing)
        idempotency = _owned_save_idempotency(
            db,
            current_user.id,
            request_key_digest,
        )
        if idempotency is not None:
            if idempotency.request_fingerprint != request_fingerprint:
                _raise_idempotency_conflict()
            existing = _owned_summary(db, idempotency.summary_id, current_user.id)
            if existing is not None:
                lease.completed = True
                store_ai_save_result(
                    current_user.id,
                    x_ai_request_id,
                    str(existing.id),
                    request_fingerprint,
                )
                return _summary_response(existing)
        logger.error(
            "[Vault] AI summary persistence conflict — patient_id=%s",
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The summary could not be saved. Please try again.",
        ) from None
    except Exception:
        db.rollback()
        if usage_state_before_commit is not None and not usage_committed:
            _restore_ai_text_usage_state(current_user, usage_state_before_commit)
        logger.error(
            "[Vault] AI summary save failed — patient_id=%s",
            current_user.id,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The summary could not be saved. Please try again.",
        ) from None
    finally:
        release_ai_request_lease(lease)


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

    Security: both queries explicitly bind to current_user.id so that a
    compromised or swapped token can never surface another patient's records.
    """
    results: List[VaultHistoryResponse] = []

    # ── 1. AI chat summaries ─────────────────────────────────────────────────
    # Filter is pinned directly to current_user.id — no intermediate variable
    # that could be shadowed or mutated before the query executes.
    summaries = (
        db.query(AIChatSummary)
        .filter(AIChatSummary.patient_id == current_user.id)
        .all()
    )

    for s in summaries:
        results.append(
            VaultHistoryResponse(
                id=s.id,
                type="ai_summary",
                date=s.updated_at or s.created_at,
                doctor_name=None,
                topic_or_reason=s.topic,
                details=s.summary_text,
                source=s.source,
                doctor_review_status=s.doctor_review_status,
                reviewed_by_doctor_id=s.reviewed_by_doctor_id,
                reviewed_at=s.reviewed_at,
                created_at=s.created_at,
                updated_at=s.updated_at,
                prescriptions=None,
                referrals=None,
            )
        )

    # ── 2. Consultation records (joined to doctors for the doctor's name) ────
    # patient_id filter is also pinned to current_user.id for the same reason.
    consultations = (
        db.query(ConsultationRecord, Doctor)
        .outerjoin(Doctor, ConsultationRecord.doctor_id == Doctor.id)
        .filter(ConsultationRecord.patient_id == current_user.id)
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
        current_user.id,
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

    Returns a downloadable PDF file named ``MDQ_Plus_Records.pdf``.
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
    # Each entry:
    # (created_at, title, date_str, body, body_parts, is_ai_summary)
    entries: list[tuple] = []

    for s in ai_summaries:
        title = "AI Summary"
        activity_date = s.updated_at or s.created_at
        created_date_str = _as_utc(s.created_at).strftime(
            "%d %b %Y, %H:%M UTC"
        )
        updated_date_str = _as_utc(activity_date).strftime(
            "%d %b %Y, %H:%M UTC"
        )
        date_str = f"Created: {created_date_str}"
        if _as_utc(activity_date) != _as_utc(s.created_at):
            date_str += f"\nLast updated: {updated_date_str}"
        body = f"Topic: {s.topic}\n\n{s.summary_text or ''}"
        entries.append((activity_date, title, date_str, body, [], True))

    for c in consultations:
        title = "Consultation Record"
        date_str = c.created_at.strftime("%d %b %Y, %H:%M UTC")
        # Each section is stored separately so the PDF renderer can style them
        # independently (e.g. prescriptions get a dedicated header block).
        body_parts = []
        if c.clinical_notes:
            body_parts.append(("clinical", f"Clinical Notes:\n{c.clinical_notes}"))
        if c.prescriptions:
            body_parts.append(("prescription", c.prescriptions))
        if c.referrals:
            body_parts.append(("clinical", f"Referrals:\n{c.referrals}"))
        body = "\n\n".join(text for _, text in body_parts) if body_parts else "No clinical details recorded."
        entries.append((c.created_at, title, date_str, body, body_parts, False))

    # Sort newest-first
    entries.sort(key=lambda e: e[0], reverse=True)

    # ── 4. Build the PDF ─────────────────────────────────────────────────────
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)

    for idx, (_, title, date_str, body, body_parts, is_ai_summary) in enumerate(entries):
        pdf.add_page()

        # ── Header bar ──────────────────────────────────────────────────────
        pdf.set_fill_color(30, 90, 180)
        pdf.rect(0, 0, 210, 18, style="F")
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(255, 255, 255)
        pdf.set_xy(10, 4)
        pdf.cell(0, 10, "MDQ+ Health Vault Export", ln=False)

        # ── Record title ─────────────────────────────────────────────────────
        pdf.set_xy(10, 25)
        pdf.set_font("Helvetica", "B", 16)
        pdf.set_text_color(20, 20, 60)
        pdf.multi_cell(0, 8, title)

        # ── Date ─────────────────────────────────────────────────────────────
        pdf.set_font("Helvetica", "I", 10)
        pdf.set_text_color(100, 100, 120)
        if is_ai_summary:
            pdf.set_x(10)
            pdf.multi_cell(190, 6, date_str, align="R")
        else:
            pdf.cell(0, 6, date_str, align="R", ln=True)

        # ── Divider ──────────────────────────────────────────────────────────
        pdf.set_draw_color(200, 200, 220)
        pdf.ln(2)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)

        # ── Body text ─────────────────────────────────────────────────────────
        # Render prescription sections with a distinct labelled header; all
        # other sections are rendered as plain paragraphs.
        def _clean(raw: str) -> str:
            safe = raw.encode("latin-1", "replace").decode("latin-1")
            return safe.replace("**", "").replace("*", "")

        if body_parts:
            # Typed rendering (consultation records)
            for section_type, section_text in body_parts:
                if section_type == "prescription":
                    # ── Prescription banner ──────────────────────────────────
                    pdf.set_fill_color(0, 128, 110)          # teal accent
                    pdf.set_text_color(255, 255, 255)
                    pdf.set_font("Helvetica", "B", 10)
                    pdf.cell(0, 7, "  Prescriptions & Medications", fill=True, ln=True)
                    pdf.ln(2)
                    pdf.set_text_color(30, 30, 50)
                    pdf.set_font("Helvetica", "", 11)
                    pdf.multi_cell(0, 8, _clean(section_text))
                    pdf.ln(4)
                else:
                    # Plain clinical / referral section
                    pdf.set_font("Helvetica", "", 11)
                    pdf.set_text_color(30, 30, 50)
                    for para in _clean(section_text).split("\n\n"):
                        if para.strip():
                            pdf.multi_cell(0, 8, para.strip())
                            pdf.ln(4)
        else:
            # Plain rendering (AI summaries and legacy records)
            pdf.set_font("Helvetica", "", 11)
            pdf.set_text_color(30, 30, 50)
            safe_body = body.encode("latin-1", "replace").decode("latin-1")
            clean_body = safe_body.replace("**", "").replace("*", "")
            for section in clean_body.split("\n\n"):
                if section.strip():
                    pdf.multi_cell(0, 8, section.strip())
                    pdf.ln(4)

        # ── Footer ───────────────────────────────────────────────────────────
        if is_ai_summary:
            pdf.set_draw_color(220, 220, 230)
            pdf.line(10, pdf.get_y(), 200, pdf.get_y())
            pdf.ln(4)
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(100, 100, 120)
            pdf.multi_cell(
                0,
                6,
                (
                    "Generated with AI assistance. Review important health "
                    "decisions with a qualified healthcare professional."
                ),
            )

        pdf.set_y(-15)
        pdf.set_font("Helvetica", "I", 8)
        pdf.set_text_color(150, 150, 160)
        pdf.cell(0, 8, f"Page {idx + 1} of {len(entries)}  |  Confidential - MDQ+", align="C")

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
        headers={"Content-Disposition": "attachment; filename=MDQ_Plus_Records.pdf"},
    )


# ---------------------------------------------------------------------------
# DELETE /vault/ai-summary/{summary_id}  (legacy — kept for compatibility)
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


# ---------------------------------------------------------------------------
# DELETE /vault/record/{record_id}  (generic — handles any vault record type)
# ---------------------------------------------------------------------------

@router.delete(
    "/record/{record_id}",
    status_code=status.HTTP_200_OK,
    summary="Delete any Health Vault record owned by the authenticated patient",
)
def delete_vault_record(
    record_id: UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
) -> dict:
    """
    Permanently removes a single Health Vault record (either an AI chat
    summary or a consultation record) that belongs to the authenticated
    patient.

    Security:
      - The record is first fetched without a patient_id filter to determine
        if it exists at all.
      - If it exists but belongs to a *different* patient, a 403 Forbidden is
        returned so the caller cannot infer the owner by comparing 403 vs 404.
      - Only after ownership is confirmed is the record deleted.
    """
    # ── Try AI chat summary first ────────────────────────────────────────────
    ai_record = (
        db.query(AIChatSummary)
        .filter(AIChatSummary.id == record_id)
        .first()
    )
    if ai_record is not None:
        if ai_record.patient_id != current_user.id:
            logger.warning(
                "[Vault] Forbidden delete attempt — patient_id=%s tried to delete "
                "AI summary owned by patient_id=%s (record_id=%s)",
                current_user.id,
                ai_record.patient_id,
                record_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete this record.",
            )
        db.delete(ai_record)
        db.commit()
        logger.info(
            "[Vault] AI summary deleted via generic endpoint — patient_id=%s record_id=%s",
            current_user.id,
            record_id,
        )
        return {"detail": "Record deleted successfully."}

    # ── Try consultation record next ─────────────────────────────────────────
    consult_record = (
        db.query(ConsultationRecord)
        .filter(ConsultationRecord.id == record_id)
        .first()
    )
    if consult_record is not None:
        if consult_record.patient_id != current_user.id:
            logger.warning(
                "[Vault] Forbidden delete attempt — patient_id=%s tried to delete "
                "consultation record owned by patient_id=%s (record_id=%s)",
                current_user.id,
                consult_record.patient_id,
                record_id,
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete this record.",
            )
        db.delete(consult_record)
        db.commit()
        logger.info(
            "[Vault] Consultation record deleted via generic endpoint — patient_id=%s record_id=%s",
            current_user.id,
            record_id,
        )
        return {"detail": "Record deleted successfully."}

    # ── Record not found in either table ─────────────────────────────────────
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail="Record not found.",
    )
