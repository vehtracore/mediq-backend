"""
Family Plan Invite API
======================
Provides two stateless endpoints for managing family plan member invitations:

  GET  /api/v1/family/invite-code  — primary account holder generates a signed invite code
  POST /api/v1/family/join         — a new dependent redeems the invite code to join

Design notes
------------
• The invite token is a short-lived HS256 JWT (72 h) whose payload carries only the
  primary user's integer ID and a ``typ`` discriminator of ``"family_invite"``.
  Using the app's existing SECRET_KEY keeps the system stateless — no DB table needed.
• All validation (plan check, capacity check, already-a-dependent check) is done at
  both generation time *and* redemption time so the invite is always consistent even
  if the primary account's state changes after the code was generated.
• The dependent's plan and subscription_expiry are synchronised to the primary account
  on redemption so they immediately inherit the family benefit.
"""

import logging
import os
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
import jwt
from jwt.exceptions import PyJWTError
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.core.database import get_db
from app.models.user import User

logger = logging.getLogger("uvicorn.error")

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FAMILY_PLAN_NAME  = "family"
_MAX_DEPENDENTS    = 4          # primary + 4 = 5 total members
_INVITE_TTL_HOURS  = 72         # invite codes expire after 3 days
_INVITE_TOKEN_TYPE = "family_invite"

# We reuse the app-wide SECRET_KEY / ALGORITHM already established in security.py
_SECRET_KEY = os.getenv("SECRET_KEY")
_ALGORITHM  = os.getenv("ALGORITHM", "HS256")

router = APIRouter()


# ---------------------------------------------------------------------------
# Helper: encode / decode invite tokens
# ---------------------------------------------------------------------------

def _create_invite_token(primary_user_id: int) -> str:
    """Return a signed JWT that encodes the primary account's ID.

    The token is intentionally narrow: it cannot be reused as an access token
    because ``typ`` != ``"access"``, which the main deps.get_current_user guard
    rejects. It also carries a hard expiry so stale links self-invalidate.
    """
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(primary_user_id),   # keep convention: sub is always a string
        "typ": _INVITE_TOKEN_TYPE,
        "iat": now,
        "exp": now + timedelta(hours=_INVITE_TTL_HOURS),
    }
    return jwt.encode(payload, _SECRET_KEY, algorithm=_ALGORITHM)


def _decode_invite_token(token: str) -> int:
    """Decode and validate an invite token.  Returns the primary user's ID.

    Raises HTTP 400 on any tampering, expiry, or wrong ``typ``.
    """
    try:
        payload = jwt.decode(token, _SECRET_KEY, algorithms=[_ALGORITHM])
    except PyJWTError as exc:
        logger.warning("[FAMILY] Invite token decode failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired invite code.",
        )

    if payload.get("typ") != _INVITE_TOKEN_TYPE:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid invite code type.",
        )

    try:
        return int(payload["sub"])
    except (KeyError, ValueError):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed invite code.",
        )


# ---------------------------------------------------------------------------
# Shared guard: assert a user is a valid, non-full family primary account
# ---------------------------------------------------------------------------

def _assert_valid_primary(user: User) -> None:
    """Raise HTTP 4xx if *user* cannot accept new dependents."""
    if user.plan != _FAMILY_PLAN_NAME:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Primary account does not have a family plan.",
        )
    if len(user.dependents) >= _MAX_DEPENDENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Family plan is full (maximum 4 dependents reached).",
        )


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

class InviteCodeResponse(BaseModel):
    invite_code: str


class JoinRequest(BaseModel):
    invite_code: str


class JoinResponse(BaseModel):
    message: str
    primary_account_id: int


# ---------------------------------------------------------------------------
# GET /invite-code  — primary account generates an invite link
# ---------------------------------------------------------------------------

@router.get(
    "/invite-code",
    response_model=InviteCodeResponse,
    summary="Generate a family plan invite code",
    description=(
        "Only callable by a primary account holder on a **family** plan with fewer "
        "than 4 dependents. Returns a short-lived (72 h) signed invite code that "
        "another user can redeem via **POST /join**."
    ),
)
def generate_invite_code(
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db),
):
    # ── Guard 1: must be on the family plan ──────────────────────────────────
    if current_user.plan != _FAMILY_PLAN_NAME:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account is not on a family plan.",
        )

    # ── Guard 2: must be a primary account (not already a dependent) ─────────
    if current_user.primary_account_id is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only the primary account holder can generate invite codes. "
                "Dependent accounts cannot invite others."
            ),
        )

    # ── Guard 3: capacity check ───────────────────────────────────────────────
    # Refresh so SQLAlchemy loads the latest dependents list within this session.
    db.refresh(current_user)
    if len(current_user.dependents) >= _MAX_DEPENDENTS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Family plan is full (maximum 4 dependents reached).",
        )

    token = _create_invite_token(current_user.id)

    logger.info(
        "[FAMILY] Invite code generated by user id=%s (dependents=%d/%d)",
        current_user.id,
        len(current_user.dependents),
        _MAX_DEPENDENTS,
    )

    return InviteCodeResponse(invite_code=token)


# ---------------------------------------------------------------------------
# POST /join  — dependent redeems an invite code
# ---------------------------------------------------------------------------

@router.post(
    "/join",
    response_model=JoinResponse,
    summary="Redeem a family plan invite code",
    description=(
        "Accepts the invite code produced by **GET /invite-code**, links the "
        "current user as a dependent of the primary account, and synchronises "
        "the family plan and its subscription expiry."
    ),
)
def join_family(
    body: JoinRequest,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db),
):
    # ── Step 1: decode the token ──────────────────────────────────────────────
    primary_id = _decode_invite_token(body.invite_code)

    # ── Step 2: prevent self-invite ───────────────────────────────────────────
    if primary_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You cannot join your own family plan.",
        )

    # ── Step 3: prevent a primary account from becoming someone's dependent ───
    if current_user.primary_account_id is None and len(current_user.dependents) > 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Primary account holders with existing dependents cannot join "
                "another family group."
            ),
        )

    # ── Step 4: prevent double-joining ───────────────────────────────────────
    if current_user.primary_account_id is not None:
        if current_user.primary_account_id == primary_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You are already a member of this family plan.",
            )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="You are already linked to a different family plan.",
        )

    # ── Step 5: load & validate the primary account ───────────────────────────
    primary_user: User | None = db.query(User).filter(User.id == primary_id).first()
    if primary_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="The family account associated with this invite no longer exists.",
        )

    # Re-validate the primary's plan and capacity at redemption time so a code
    # generated before the plan downgraded or the group filled up is rejected.
    _assert_valid_primary(primary_user)

    # ── Step 6: link the current user as a dependent ──────────────────────────
    current_user.primary_account_id  = primary_user.id
    current_user.plan                 = _FAMILY_PLAN_NAME
    current_user.subscription_expiry  = primary_user.subscription_expiry

    db.commit()
    db.refresh(current_user)

    logger.info(
        "[FAMILY] User id=%s joined family of primary id=%s. "
        "Plan set to '%s', expiry=%s.",
        current_user.id,
        primary_user.id,
        _FAMILY_PLAN_NAME,
        primary_user.subscription_expiry,
    )

    return JoinResponse(
        message="Successfully joined the family plan.",
        primary_account_id=primary_user.id,
    )
