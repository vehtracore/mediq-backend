"""
Emergency Trigger Endpoint
===========================
POST /api/v1/emergency/trigger

Dispatches an emergency alert to the patient's Next of Kin (NoK) via Termii
SMS and/or voice call.

Subscription gating (added 2026-05-02)
---------------------------------------
NOK automated alerts (Termii SMS + voice) are a **paid feature**.

• FREE users  → Emergency is logged for MDQ+ internal dispatch.
               Termii calls are NOT fired (saves API cost).
               HTTP 202 is returned with a clear message.

• PREMIUM users → Termii SMS and/or voice call are fired via BackgroundTasks.
                  HTTP 202 returned immediately; calls run asynchronously.

• FAMILY tier  → Treated identically to PREMIUM once the family_groups table
                  is implemented.  A TODO stub is clearly marked below.

Design decisions
-----------------
• HTTP 202 Accepted is returned in ALL cases — the client should never block
  waiting for a Termii result.
• try/except inside every background task ensures a Termii outage can never
  crash the main application thread.
• GPS coordinates are appended to the message when supplied.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api import deps
from app.core.database import get_db
from app.models.user import User
from app.services.termii_service import termii_service

logger = logging.getLogger("uvicorn.error")

router = APIRouter()


# ─── Subscription Gate ─────────────────────────────────────────────────────────

def _has_active_premium(user: User) -> bool:
    """
    Return True if the user is entitled to NOK automated alerts.

    Entitlement conditions (any one is sufficient):
      1. user.plan == 'premium'  AND  subscription_expiry is in the future
         (or expiry is NULL, meaning lifetime/manual grant).
      2. TODO: user is a member of an active family_groups record
         (implement once the family_groups table exists).

    Free users always return False.
    """
    if user.plan != "premium":
        return False

    # If expiry is set, verify it hasn't lapsed
    if user.subscription_expiry is not None:
        now = datetime.now(timezone.utc)
        # subscription_expiry may be timezone-naive from older rows
        expiry = user.subscription_expiry
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        if expiry < now:
            logger.info(
                "[EMERGENCY] User %s has expired premium subscription (expired %s)",
                user.id,
                expiry.isoformat(),
            )
            return False

    return True


# TODO: implement when family_groups table is available
# def _is_family_member(user: User, db: Session) -> bool:
#     from app.models.family_group import FamilyGroupMember
#     return db.query(FamilyGroupMember).filter(
#         FamilyGroupMember.user_id == user.id,
#         FamilyGroupMember.is_active == True,
#     ).first() is not None


# ─── Background Tasks ──────────────────────────────────────────────────────────

async def _dispatch_sms(kin_phone: str, message: str) -> None:
    """
    Background task: send emergency SMS via Termii.
    All exceptions are caught and logged; they must NOT propagate.
    """
    try:
        logger.info("[EMERGENCY] 🚨 Dispatching SMS to %s", kin_phone)
        success = await termii_service.send_sms(to=kin_phone, message=message)
        if not success:
            logger.error(
                "[EMERGENCY] ❌ SMS to %s was not delivered. "
                "Check Termii credentials and recipient number.",
                kin_phone,
            )
        else:
            logger.info("[EMERGENCY] ✅ Emergency SMS delivered to %s", kin_phone)
    except Exception as exc:
        logger.error(
            "[EMERGENCY] 💥 Unhandled error in SMS background task: %s: %s",
            type(exc).__name__,
            exc,
        )


async def _dispatch_voice(kin_phone: str, message: str) -> None:
    """
    Background task: trigger Termii voice call.
    All exceptions are caught and logged; they must NOT propagate.
    """
    try:
        logger.info("[EMERGENCY] 🚨 Triggering voice call to %s", kin_phone)
        success = await termii_service.send_voice_call(to=kin_phone, message=message)
        if not success:
            logger.error(
                "[EMERGENCY] ❌ Voice call to %s was not completed. "
                "Check Termii credentials and recipient number.",
                kin_phone,
            )
        else:
            logger.info("[EMERGENCY] ✅ Emergency voice call initiated to %s", kin_phone)
    except Exception as exc:
        logger.error(
            "[EMERGENCY] 💥 Unhandled error in voice call background task: %s: %s",
            type(exc).__name__,
            exc,
        )


# ─── Endpoint ─────────────────────────────────────────────────────────────────

class EmergencyTriggerRequest(BaseModel):
    """
    Payload for POST /trigger.

    latitude and longitude are optional — they are appended to the alert
    message when provided so the Next of Kin can locate the patient.
    """
    latitude: Optional[float] = None
    longitude: Optional[float] = None


@router.post(
    "/trigger",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger an emergency alert",
    description=(
        "Logs an emergency for MDQ+ dispatch. For premium subscribers, also "
        "dispatches an SMS and/or voice call to the patient's Next of Kin via "
        "Termii. Returns 202 immediately; Termii calls run asynchronously."
    ),
)
async def trigger_emergency(
    payload: EmergencyTriggerRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    POST /api/v1/emergency/trigger

    Steps:
      1. Validate that the user has a Next of Kin phone number configured.
      2. Validate that at least one alert channel (SMS / voice) is enabled.
      3. Build the alert message, appending GPS coordinates when available.
      4. [SUBSCRIPTION GATE] Check if user is premium/family.
           • Free  → log emergency, skip Termii, return 202 with upgrade prompt.
           • Premium → queue Termii calls as background tasks, return 202.
      5. Return HTTP 202 immediately.
    """
    patient_name = f"{current_user.first_name} {current_user.last_name}".strip()

    # ── 1. Guard: Next of Kin phone must be present ───────────────────────────
    kin_phone: Optional[str] = getattr(current_user, "kin_phone", None)
    if not kin_phone or not kin_phone.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Emergency alert could not be sent: no Next of Kin phone number "
                "is configured. Please update your emergency settings."
            ),
        )

    # ── 2. Guard: at least one channel must be enabled ────────────────────────
    sms_enabled: bool   = bool(getattr(current_user, "emergency_sms_enabled", False))
    voice_enabled: bool = bool(getattr(current_user, "emergency_voice_enabled", False))

    if not sms_enabled and not voice_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Emergency alert could not be sent: both SMS and voice alerts "
                "are disabled. Enable at least one channel in your emergency settings."
            ),
        )

    # ── 3. Build alert message ────────────────────────────────────────────────
    message = (
        f"EMERGENCY ALERT: {patient_name} requires immediate medical assistance."
    )
    if payload.latitude is not None and payload.longitude is not None:
        message += (
            f" Last known GPS location: "
            f"Lat {payload.latitude:.6f}, Lon {payload.longitude:.6f}. "
            f"https://maps.google.com/?q={payload.latitude:.6f},{payload.longitude:.6f}"
        )

    logger.info(
        "[EMERGENCY] 🚨 Alert triggered | user_id=%s (%s) | plan=%s "
        "| sms=%s | voice=%s | has_gps=%s",
        current_user.id,
        patient_name,
        current_user.plan,
        sms_enabled,
        voice_enabled,
        payload.latitude is not None,
    )

    # ── 4. Subscription gate ──────────────────────────────────────────────────
    # TODO: also check _is_family_member(current_user, db) once family_groups exists
    is_premium = _has_active_premium(current_user)

    if not is_premium:
        # Free user — log for internal MDQ+ dispatch, DO NOT fire Termii
        logger.info(
            "[EMERGENCY] ℹ️  Free user %s — emergency logged for MDQ+ dispatch. "
            "Termii NOK alerts skipped (premium feature).",
            current_user.id,
        )
        return {
            "status": "logged",
            "message": (
                "Your emergency has been logged and flagged for MDQ+ dispatch. "
                "Automated Next of Kin SMS and voice alerts require a Premium subscription. "
                "Upgrade your plan to enable instant NOK notifications."
            ),
            "nok_alerts_sent": False,
            "upgrade_required": True,
        }

    # ── 5. Premium path: queue Termii background tasks ────────────────────────
    channels_queued = []

    if sms_enabled:
        background_tasks.add_task(_dispatch_sms, kin_phone.strip(), message)
        channels_queued.append("SMS")

    if voice_enabled:
        background_tasks.add_task(_dispatch_voice, kin_phone.strip(), message)
        channels_queued.append("voice call")

    logger.info(
        "[EMERGENCY] ✅ Premium NOK alerts queued for user_id=%s — channels: %s",
        current_user.id,
        channels_queued,
    )

    return {
        "status": "accepted",
        "message": f"Emergency alert queued via: {', '.join(channels_queued)}.",
        "recipient": kin_phone.strip(),
        "nok_alerts_sent": True,
        "upgrade_required": False,
    }
