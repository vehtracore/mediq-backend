"""
Emergency Trigger Endpoint
===========================
POST /api/v1/emergency/trigger

Allows an authenticated patient to dispatch an emergency alert to their
registered Next of Kin (NoK) via SMS and/or voice call, using Termii.

Design decisions:
  • The endpoint returns HTTP 202 Accepted *immediately* — the actual
    Termii API calls run in FastAPI BackgroundTasks so the client is never
    blocked by a third-party network call.
  • try/except inside every background task ensures a Termii outage
    can never crash the main application thread.
  • GPS coordinates are appended to the message when supplied, giving
    the NoK actionable location data.
"""

import logging
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


# ─── Request Schema ────────────────────────────────────────────────────────────

class EmergencyTriggerRequest(BaseModel):
    """
    Payload for POST /trigger.

    latitude and longitude are optional — they are appended to the alert
    message when provided so the Next of Kin can locate the patient.
    """
    latitude: Optional[float] = None
    longitude: Optional[float] = None


# ─── Background Tasks ──────────────────────────────────────────────────────────

async def _dispatch_sms(kin_phone: str, message: str) -> None:
    """
    Background task: send emergency SMS via Termii.
    All exceptions are caught and logged; they must NOT propagate.
    """
    try:
        logger.info(f"[EMERGENCY] 🚨 Dispatching SMS to {kin_phone}")
        success = await termii_service.send_sms(to=kin_phone, message=message)
        if not success:
            logger.error(
                f"[EMERGENCY] ❌ SMS to {kin_phone} was not delivered. "
                "Check Termii credentials and recipient number."
            )
        else:
            logger.info(f"[EMERGENCY] ✅ Emergency SMS delivered to {kin_phone}")
    except Exception as exc:
        # Absolute safety net — the background thread must never die silently
        logger.error(
            f"[EMERGENCY] 💥 Unhandled error in SMS background task: "
            f"{type(exc).__name__}: {exc}"
        )


async def _dispatch_voice(kin_phone: str, message: str) -> None:
    """
    Background task: trigger Termii voice call.
    All exceptions are caught and logged; they must NOT propagate.
    """
    try:
        logger.info(f"[EMERGENCY] 🚨 Triggering voice call to {kin_phone}")
        success = await termii_service.send_voice_call(to=kin_phone, message=message)
        if not success:
            logger.error(
                f"[EMERGENCY] ❌ Voice call to {kin_phone} was not completed. "
                "Check Termii credentials and recipient number."
            )
        else:
            logger.info(f"[EMERGENCY] ✅ Emergency voice call initiated to {kin_phone}")
    except Exception as exc:
        logger.error(
            f"[EMERGENCY] 💥 Unhandled error in voice call background task: "
            f"{type(exc).__name__}: {exc}"
        )


# ─── Endpoint ─────────────────────────────────────────────────────────────────

@router.post(
    "/trigger",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger an emergency alert",
    description=(
        "Dispatches an SMS and/or voice call to the patient's Next of Kin "
        "based on their emergency settings. Returns 202 immediately; Termii "
        "calls run asynchronously in the background."
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
      4. Queue the enabled Termii calls as background tasks.
      5. Return HTTP 202 immediately.
    """

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
    sms_enabled: bool = bool(getattr(current_user, "emergency_sms_enabled", False))
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
    patient_name = f"{current_user.first_name} {current_user.last_name}".strip()

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
        f"[EMERGENCY] 🚨 Alert triggered by user_id={current_user.id} "
        f"({patient_name}) | sms={sms_enabled} | voice={voice_enabled} "
        f"| has_gps={payload.latitude is not None}"
    )

    # ── 4. Queue background tasks ─────────────────────────────────────────────
    if sms_enabled:
        background_tasks.add_task(_dispatch_sms, kin_phone.strip(), message)

    if voice_enabled:
        background_tasks.add_task(_dispatch_voice, kin_phone.strip(), message)

    # ── 5. Return 202 immediately ─────────────────────────────────────────────
    channels_queued = []
    if sms_enabled:
        channels_queued.append("SMS")
    if voice_enabled:
        channels_queued.append("voice call")

    return {
        "status": "accepted",
        "message": f"Emergency alert queued via: {', '.join(channels_queued)}.",
        "recipient": kin_phone.strip(),
    }
