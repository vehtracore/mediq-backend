"""PostgreSQL chat claims, live-worker fencing, and crash recovery."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.api_errors import ApiError
from app.models.ai_chat_claim import AIChatClaim
from app.services.ai_request_guard import ai_request_digest

LEASE_SECONDS = 300
_LOCK_NAMESPACE = 0x4D4451


@dataclass(frozen=True)
class ChatOperation:
    user_id: int
    request_id: str
    owner: str
    fingerprint: str
    disposition: str


def _lock_chat_user(db: Session, user_id: int) -> bool:
    # Transaction-scoped locks work through the Supabase transaction pooler.
    if db.bind.dialect.name != "postgresql":
        raise ApiError(503, "operation_unavailable", "AI requests are temporarily unavailable.")
    return bool(db.execute(
        text("SELECT pg_try_advisory_xact_lock(:namespace, :user_id)"),
        {"namespace": _LOCK_NAMESPACE, "user_id": user_id},
    ).scalar_one())


def _disposition(claim: AIChatClaim, digest: str, fingerprint: str) -> str:
    if claim.request_digest == digest:
        if claim.request_fingerprint != fingerprint:
            raise ApiError(409, "request_conflict", "This request ID was used for different content.")
        return "active"
    return "busy"


def _operation(
    user_id: int, request_id: str, owner: str, fingerprint: str, disposition: str,
) -> ChatOperation:
    if disposition == "busy":
        raise ApiError(409, "ai_operation_active", "An AI request is still processing.")
    return ChatOperation(user_id, request_id, owner, fingerprint, disposition)


def acquire_chat_operation(
    db: Session, user_id: int, request_id: str, fingerprint: str,
) -> ChatOperation:
    """Commit a visible claim before provider work; stale claims need a free lock."""
    digest = ai_request_digest(request_id)
    owner = str(uuid.uuid4())
    for _ in range(3):
        now = datetime.now(timezone.utc)
        inserted = db.execute(
            insert(AIChatClaim).values(
                patient_id=user_id,
                request_digest=digest,
                request_fingerprint=fingerprint,
                owner=owner,
                lease_expires_at=now + timedelta(seconds=LEASE_SECONDS),
            ).on_conflict_do_nothing(index_elements=["patient_id"])
            .returning(AIChatClaim.patient_id)
        ).scalar_one_or_none()
        if inserted is not None:
            db.commit()
            return _operation(user_id, request_id, owner, fingerprint, "started")

        claim = db.get(AIChatClaim, user_id)
        if claim is None:
            db.rollback()
            continue
        disposition = _disposition(claim, digest, fingerprint)
        if claim.lease_expires_at > now:
            db.rollback()
            return _operation(user_id, request_id, owner, fingerprint, disposition)

        if not _lock_chat_user(db, user_id):
            db.rollback()
            return _operation(user_id, request_id, owner, fingerprint, disposition)

        db.refresh(claim)
        if claim.lease_expires_at > datetime.now(timezone.utc):
            db.rollback()
            continue
        _disposition(claim, digest, fingerprint)
        claim.request_digest = digest
        claim.request_fingerprint = fingerprint
        claim.owner = owner
        claim.lease_expires_at = datetime.now(timezone.utc) + timedelta(seconds=LEASE_SECONDS)
        db.commit()
        return _operation(user_id, request_id, owner, fingerprint, "started")
    raise ApiError(503, "operation_unavailable", "The request could not be claimed. Please try again.")


def start_chat_operation(db: Session, operation: ChatOperation) -> bool:
    """Hold one PostgreSQL transaction lock until provider work commits or rolls back."""
    if not _lock_chat_user(db, operation.user_id):
        db.rollback()
        return False
    claim = db.get(AIChatClaim, operation.user_id)
    if (
        claim is None
        or claim.owner != operation.owner
        or claim.request_digest != ai_request_digest(operation.request_id)
        or claim.request_fingerprint != operation.fingerprint
    ):
        db.rollback()
        return False
    return True


def require_chat_operation_owner(db: Session, operation: ChatOperation) -> None:
    owner = db.execute(
        text("SELECT owner FROM ai_chat_claims WHERE patient_id = :user_id FOR UPDATE"),
        {"user_id": operation.user_id},
    ).scalar_one_or_none()
    if owner != operation.owner:
        raise ApiError(409, "operation_superseded", "This request is no longer active.")


def finish_chat_operation(db: Session, operation: ChatOperation, *, succeeded: bool) -> None:
    if not succeeded:
        db.rollback()
    db.execute(delete(AIChatClaim).where(
        AIChatClaim.patient_id == operation.user_id,
        AIChatClaim.owner == operation.owner,
    ))
    db.commit()


def chat_operation_status(db: Session, user_id: int, request_id: str) -> dict:
    claim = db.get(AIChatClaim, user_id)
    if claim is None or claim.request_digest != ai_request_digest(request_id):
        return {"status": "failed", "retryable": True}
    if claim.lease_expires_at > datetime.now(timezone.utc):
        return {"status": "processing"}
    if _lock_chat_user(db, user_id):
        db.rollback()
        return {"status": "failed", "retryable": True}
    db.rollback()
    return {"status": "processing"}


def cleanup_expired_chat_receipts() -> int:
    from app.core.database import SessionLocal
    from app.models.ai_chat_receipt import AIChatRequestReceipt

    db = SessionLocal()
    try:
        deleted = (
            db.query(AIChatRequestReceipt)
            .filter(AIChatRequestReceipt.expires_at <= datetime.now(timezone.utc))
            .delete(synchronize_session=False)
        )
        db.commit()
        return deleted
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()
