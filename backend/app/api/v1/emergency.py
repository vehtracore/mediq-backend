"""
Emergency Endpoints
===================
Routes
------
POST /api/v1/emergency/trigger
    Dispatches an emergency alert to the patient's Next of Kin (NoK) via Termii SMS.

GET  /api/v1/emergency/local-services
    Secure proxy for the Google Places API.  Accepts ?lat=&lon= and returns a
    clean list of nearby hospitals / police stations with name + phone number.
    The Google Maps API key never leaves the server.

Subscription gating (POST /trigger)
-------------------------------------
NOK automated alerts (Termii SMS) are a **paid feature**.

• FREE users  → Emergency is logged for MDQ+ internal dispatch.
               Termii calls are NOT fired (saves API cost).
               HTTP 202 is returned with a clear message.

• PREMIUM users → Termii SMS is fired via BackgroundTasks.
                  HTTP 202 returned immediately; calls run asynchronously.

• FAMILY tier  → Treated identically to PREMIUM once the family_groups table
                  is implemented.  A TODO stub is clearly marked below.

Design decisions
-----------------
• HTTP 202 Accepted is returned in ALL cases for /trigger — the client should
  never block waiting for a Termii result.
• try/except inside every background task ensures a Termii outage can never
  crash the main application thread.
• GPS coordinates are appended to the message when supplied.
• /local-services always returns HTTP 200 with [] on any error so the Flutter
  app can fall back to its hardcoded default numbers.
"""

import logging
import os
from datetime import datetime, timezone
from typing import List, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
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

    The phone number is passed as stored on the user record (any format).
    termii_service.send_sms() internally sanitizes it to the correct format
    (e.g. 2348012345678) before hitting the Termii API.

    All exceptions are caught and logged; they must NOT propagate.
    """
    try:
        logger.info(
            "[EMERGENCY] 🚨 Dispatching SMS | raw_number=%r",
            kin_phone,
        )
        success = await termii_service.send_sms(to=kin_phone, message=message)
        if not success:
            logger.error(
                "[EMERGENCY] ❌ SMS to %r was not delivered. "
                "Check the Termii response body in the logs above for the rejection reason.",
                kin_phone,
            )
        else:
            logger.info(
                "[EMERGENCY] ✅ Emergency SMS dispatch confirmed for %r",
                kin_phone,
            )
    except Exception as exc:
        logger.error(
            "[EMERGENCY] 💥 Unhandled error in SMS background task: %s: %s",
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
        "dispatches an SMS to the patient's Next of Kin via "
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
      2. Validate that the SMS alert channel is enabled.
      3. Build the alert message, appending GPS coordinates when available.
      4. [SUBSCRIPTION GATE] Check if user is premium/family.
           • Free  → log emergency, skip Termii, return 202 with upgrade prompt.
           • Premium → queue Termii SMS as background task, return 202.
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

    # ── 2. Guard: SMS channel must be enabled ─────────────────────────────────
    sms_enabled: bool = bool(getattr(current_user, "emergency_sms_enabled", False))

    if not sms_enabled:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "Emergency alert could not be sent: SMS alerts are disabled. "
                "Enable the SMS channel in your emergency settings."
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
        "| sms=%s | kin_phone_raw=%r | has_gps=%s",
        current_user.id,
        patient_name,
        current_user.plan,
        sms_enabled,
        kin_phone,
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
                "Automated Next of Kin SMS alerts require a Premium subscription. "
                "Upgrade your plan to enable instant NOK notifications."
            ),
            "nok_alerts_sent": False,
            "upgrade_required": True,
        }

    # ── 5. Premium path: queue Termii SMS background task ────────────────────
    # Pass the raw stored value — termii_service.send_sms() sanitizes it
    background_tasks.add_task(_dispatch_sms, kin_phone.strip(), message)

    logger.info(
        "[EMERGENCY] ✅ Premium SMS alert queued | user_id=%s | kin_phone_raw=%r",
        current_user.id,
        kin_phone,
    )

    return {
        "status": "accepted",
        "message": "Emergency SMS alert queued for your Next of Kin.",
        "recipient": kin_phone.strip(),
        "nok_alerts_sent": True,
        "upgrade_required": False,
    }


# ─── Local Emergency Services Proxy ───────────────────────────────────────────

class LocalServiceResult(BaseModel):
    """A single nearby emergency service with a verified phone number."""

    name: str = Field(..., description="Display name of the facility")
    phone_number: str = Field(..., description="National phone number of the facility")


# Google New Places API constants
_PLACES_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
_PLACES_FIELD_MASK = "places.displayName,places.nationalPhoneNumber"
_SEARCH_RADIUS_METERS = 5000.0
_TARGET_TYPES = ["hospital", "police"]


@router.get(
    "/local-services",
    response_model=List[LocalServiceResult],
    status_code=status.HTTP_200_OK,
    summary="Nearby emergency services",
    description=(
        "Secure proxy for the Google Places API. Returns hospitals and police "
        "stations within 5 km of the supplied coordinates. Only places that "
        "have a registered phone number are included. Returns [] on any error."
    ),
)
async def get_local_services(
    lat: float = Query(..., description="Latitude of the user's position"),
    lon: float = Query(..., description="Longitude of the user's position"),
) -> List[LocalServiceResult]:
    """
    GET /api/v1/emergency/local-services?lat=<float>&lon=<float>

    Proxies the Google Places New API (places:searchNearby) to keep the API
    key server-side.  Steps:
      1. Read Maps_API_KEY from environment — return [] immediately if absent.
      2. Fire one Places request per target type (hospital, police).
      3. Merge results, strip heavy fields, filter out entries with no phone.
      4. Deduplicate by name+phone and return the clean list.
      5. Catch every exception and return [] so the Flutter app can always
         fall back to its hardcoded default numbers.
    """
    api_key: Optional[str] = os.getenv("Maps_API_KEY")
    if not api_key:
        logger.warning(
            "[LOCAL-SERVICES] Maps_API_KEY is not set — returning empty list."
        )
        return []

    results: List[LocalServiceResult] = []
    seen: set = set()  # dedup key: (name, phone)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            for place_type in _TARGET_TYPES:
                request_payload = {
                    "includedTypes": [place_type],
                    "maxResultCount": 10,
                    "locationRestriction": {
                        "circle": {
                            "center": {
                                "latitude": lat,
                                "longitude": lon,
                            },
                            "radius": _SEARCH_RADIUS_METERS,
                        }
                    },
                }

                response = await client.post(
                    _PLACES_NEARBY_URL,
                    json=request_payload,
                    headers={
                        "Content-Type": "application/json",
                        "X-Goog-Api-Key": api_key,
                        "X-Goog-FieldMask": _PLACES_FIELD_MASK,
                    },
                )

                if response.status_code != 200:
                    logger.error(
                        "[LOCAL-SERVICES] Places API returned %s for type=%s: %s",
                        response.status_code,
                        place_type,
                        response.text[:200],
                    )
                    continue  # try next type; still return partial results

                data = response.json()
                places = data.get("places", [])

                for place in places:
                    # displayName is a localised object: {"text": "...", "languageCode": "..."}
                    display_name_obj = place.get("displayName", {})
                    name: str = (
                        display_name_obj.get("text", "").strip()
                        if isinstance(display_name_obj, dict)
                        else str(display_name_obj).strip()
                    )
                    phone: str = place.get("nationalPhoneNumber", "").strip()

                    # Exclude entries with no name or no phone number
                    if not name or not phone:
                        continue

                    dedup_key = (name.lower(), phone)
                    if dedup_key in seen:
                        continue

                    seen.add(dedup_key)
                    results.append(LocalServiceResult(name=name, phone_number=phone))

        logger.info(
            "[LOCAL-SERVICES] ✅ Returning %d places near (%.4f, %.4f)",
            len(results),
            lat,
            lon,
        )
        return results

    except httpx.TimeoutException:
        logger.error(
            "[LOCAL-SERVICES] ⏱ Google Places API timed out — returning empty list."
        )
        return []
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[LOCAL-SERVICES] 💥 Unexpected error fetching local services: %s: %s",
            type(exc).__name__,
            exc,
        )
        return []
