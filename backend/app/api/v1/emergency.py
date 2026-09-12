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

• PREMIUM/FAMILY users → Termii SMS is fired via BackgroundTasks, subject to:
                    – 5-minute cooldown between triggers (anti-spam).
                    – 5 accepted SMS requests per UTC calendar month.
                  HTTP 202 returned immediately; Termii calls run asynchronously.

Design decisions
-----------------
• HTTP 202 Accepted is returned in ALL cases for /trigger — the client should
  never block waiting for a Termii result.
• try/except inside every background task ensures a Termii outage can never
  crash the main application thread.
• GPS coordinates and reverse-geocoded address are appended to the message
  when supplied.
• The cooldown and quota checks happen BEFORE the background task is queued so
  the counter/timestamp update is committed synchronously in the same request.
• /local-services returns a typed success/empty/unavailable envelope so the
  Flutter app can explain why its hardcoded contacts are being shown.
"""

import asyncio
import hashlib
import logging
import os
from datetime import date, datetime, timedelta, timezone
from time import perf_counter
from typing import List, Literal, NamedTuple, Optional
from uuid import uuid4

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import case, func, or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import deps
from app.core.database import SessionLocal, get_db
from app.core.limiter import limiter
from app.models.emergency_sms_request import EmergencySmsRequest
from app.models.user import User
from app.services.subscription_entitlement import has_active_paid_entitlement
from app.services.termii_service import termii_service

logger = logging.getLogger("uvicorn.error")

router = APIRouter()

# ─── Rate-limit constants ──────────────────────────────────────────────────────
_COOLDOWN_MINUTES: int = 5    # minimum gap between two NOK SMS dispatches
_SMS_QUOTA: int = 5           # maximum accepted NOK SMS requests per UTC month


# ─── Subscription Gate ─────────────────────────────────────────────────────────

class _SmsReservation(NamedTuple):
    outcome: Literal["queued", "duplicate", "cooldown", "quota"]
    sms_count: int
    cooldown_remaining_seconds: int = 0
    reserved_at: Optional[datetime] = None
    month_start: Optional[date] = None
    request_status: Optional[str] = None


def _request_id_digest(request_id: str) -> str:
    return hashlib.sha256(request_id.encode("utf-8")).hexdigest()[:12]


def _normalise_datetime(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def _utc_month_start(now: datetime) -> date:
    utc_now = _normalise_datetime(now).astimezone(timezone.utc)
    return date(utc_now.year, utc_now.month, 1)


def _reserve_emergency_sms(
    db: Session,
    *,
    user_id: int,
    request_id: str,
    now: datetime,
) -> _SmsReservation:
    """Atomically claim an activation and reserve one cooldown/quota unit."""
    existing = (
        db.query(EmergencySmsRequest)
        .filter(
            EmergencySmsRequest.user_id == user_id,
            EmergencySmsRequest.request_id == request_id,
        )
        .first()
    )
    if existing is not None:
        return _SmsReservation("duplicate", 0, request_status=existing.status)

    db.add(
        EmergencySmsRequest(
            user_id=user_id,
            request_id=request_id,
            status="reserved",
        )
    )
    try:
        # The unique constraint serializes concurrent replays of one request ID.
        db.flush()
    except IntegrityError:
        db.rollback()
        duplicate = (
            db.query(EmergencySmsRequest)
            .filter(
                EmergencySmsRequest.user_id == user_id,
                EmergencySmsRequest.request_id == request_id,
            )
            .first()
        )
        if duplicate is not None:
            return _SmsReservation("duplicate", 0, request_status=duplicate.status)
        raise

    now = _normalise_datetime(now).astimezone(timezone.utc)
    month_start = _utc_month_start(now)
    cooldown_cutoff = now - timedelta(minutes=_COOLDOWN_MINUTES)
    is_new_month = or_(
        User.emergency_sms_month_reset.is_(None),
        User.emergency_sms_month_reset != month_start,
    )
    reservation = db.execute(
        update(User)
        .where(User.id == user_id)
        .where(
            or_(
                is_new_month,
                func.coalesce(User.emergency_sms_count, 0) < _SMS_QUOTA,
            )
        )
        .where(
            or_(
                is_new_month,
                User.last_emergency_trigger.is_(None),
                User.last_emergency_trigger <= cooldown_cutoff,
            )
        )
        .values(
            last_emergency_trigger=now,
            emergency_sms_count=case(
                (is_new_month, 1),
                else_=func.coalesce(User.emergency_sms_count, 0) + 1,
            ),
            emergency_sms_month_reset=month_start,
        )
        .execution_options(synchronize_session=False)
    )

    if reservation.rowcount == 1:
        db.commit()
        sms_count = (
            db.query(User.emergency_sms_count).filter(User.id == user_id).scalar()
            or 0
        )
        return _SmsReservation(
            "queued",
            sms_count,
            reserved_at=now,
            month_start=month_start,
        )

    # Do not retain an idempotency claim when no SMS slot was reserved.
    db.rollback()
    state = (
        db.query(
            User.last_emergency_trigger,
            User.emergency_sms_count,
            User.emergency_sms_month_reset,
        )
        .filter(User.id == user_id)
        .one()
    )
    sms_count = state.emergency_sms_count or 0
    if state.emergency_sms_month_reset == month_start and sms_count >= _SMS_QUOTA:
        return _SmsReservation("quota", sms_count)

    if state.last_emergency_trigger is not None:
        elapsed = now - _normalise_datetime(state.last_emergency_trigger)
        remaining = max(
            1,
            int((_COOLDOWN_MINUTES * 60) - elapsed.total_seconds()),
        )
        return _SmsReservation("cooldown", sms_count, remaining)

    raise RuntimeError("Emergency SMS reservation failed without cooldown or quota")


def _finalize_emergency_sms(
    db: Session,
    *,
    user_id: int,
    request_id: str,
    reserved_at: datetime,
    month_start: date,
    provider_accepted: bool,
) -> bool:
    """Finalize exactly one reservation and release failed provider attempts."""
    final_status = "accepted" if provider_accepted else "failed"
    ledger_update = db.execute(
        update(EmergencySmsRequest)
        .where(EmergencySmsRequest.user_id == user_id)
        .where(EmergencySmsRequest.request_id == request_id)
        .where(EmergencySmsRequest.status == "reserved")
        .values(status=final_status)
        .execution_options(synchronize_session=False)
    )
    if ledger_update.rowcount != 1:
        db.rollback()
        return False

    if not provider_accepted:
        # Release this month's reserved unit. Clear cooldown only when it still
        # belongs to this reservation; a later reservation must remain intact.
        db.execute(
            update(User)
            .where(User.id == user_id)
            .where(User.emergency_sms_month_reset == month_start)
            .values(
                emergency_sms_count=case(
                    (
                        func.coalesce(User.emergency_sms_count, 0) > 0,
                        func.coalesce(User.emergency_sms_count, 0) - 1,
                    ),
                    else_=0,
                ),
                last_emergency_trigger=case(
                    (User.last_emergency_trigger == reserved_at, None),
                    else_=User.last_emergency_trigger,
                ),
            )
            .execution_options(synchronize_session=False)
        )

    db.commit()
    return True


# ─── Background Tasks ──────────────────────────────────────────────────────────

async def _dispatch_sms(
    kin_phone: str,
    message: str,
    *,
    user_id: int,
    request_id: str,
    reserved_at: datetime,
    month_start: date,
    session_factory=SessionLocal,
) -> None:
    """
    Background task: send emergency SMS via Termii.

    The phone number is passed as stored on the user record (any format).
    termii_service.send_sms() internally sanitizes it to the correct format
    (e.g. 2348012345678) before hitting the Termii API.

    All exceptions are caught and logged; they must NOT propagate.
    """
    provider_accepted = False
    try:
        logger.info("[EMERGENCY] NOK provider task started")
        provider_accepted = await termii_service.send_sms(to=kin_phone, message=message)
        if not provider_accepted:
            logger.error("[EMERGENCY] NOK provider task failed")
        else:
            logger.info("[EMERGENCY] NOK provider accepted alert request")
    except Exception as exc:
        logger.error(
            "[EMERGENCY] Unhandled SMS background failure | error_type=%s",
            type(exc).__name__,
        )

    try:
        with session_factory() as db:
            finalized = _finalize_emergency_sms(
                db,
                user_id=user_id,
                request_id=request_id,
                reserved_at=reserved_at,
                month_start=month_start,
                provider_accepted=provider_accepted,
            )
        if not finalized:
            logger.warning(
                "[EMERGENCY] NOK reservation already finalized | user_id=%s "
                "| request=%s",
                user_id,
                _request_id_digest(request_id),
            )
    except Exception as exc:
        logger.error(
            "[EMERGENCY] NOK accounting finalization failed | user_id=%s "
            "| request=%s | error_type=%s",
            user_id,
            _request_id_digest(request_id),
            type(exc).__name__,
        )


# ─── Endpoint ─────────────────────────────────────────────────────────────────

class EmergencyTriggerRequest(BaseModel):
    """
    Payload for POST /trigger.

    latitude and longitude are optional — they are appended to the alert
    message when provided so the Next of Kin can locate the patient.

    address is an optional human-readable string (e.g. "Akobo, Ibadan")
    reverse-geocoded by the Flutter client. When present it is injected into
    the SMS body so the Next of Kin gets a recognisable location name in
    addition to the raw coordinates.
    """
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    address: Optional[str] = None
    request_id: Optional[str] = Field(
        default=None,
        min_length=16,
        max_length=128,
        pattern=r"^[A-Za-z0-9._:-]+$",
        description="Stable identifier for one logical Emergency activation",
    )


@router.post(
    "/trigger",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger an emergency alert",
    description=(
        "Logs an emergency for MDQ+ dispatch. For active premium or family subscribers, also "
        "dispatches an SMS to the patient's Next of Kin via "
        "Termii. Returns 202 immediately; Termii calls run asynchronously. "
        "A 5-minute cooldown and 5-SMS UTC calendar-month quota are enforced for paid users."
    ),
)
@limiter.limit("10/hour")
async def trigger_emergency(
    request: Request,
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
      3. Build the alert message, appending GPS coordinates / address when available.
      4. [SUBSCRIPTION GATE] Check if user is premium/family.
           • Free  → log emergency, skip Termii, return 202 with upgrade prompt.
           • Premium → apply cooldown + quota checks, queue Termii SMS, return 202.
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
    has_coords = payload.latitude is not None and payload.longitude is not None
    address = (payload.address or "").strip() or None

    if has_coords and address:
        # Rich template: human-readable area name + raw coordinates + map link
        message = (
            f"EMERGENCY ALERT: {patient_name} requires immediate medical assistance "
            f"near {address}. "
            f"Last known GPS: "
            f"Lat {payload.latitude:.6f}, Lon {payload.longitude:.6f}. "
            f"https://maps.google.com/?q={payload.latitude:.6f},{payload.longitude:.6f}"
        )
    elif has_coords:
        # Coordinates-only fallback (address not provided)
        message = (
            f"EMERGENCY ALERT: {patient_name} requires immediate medical assistance. "
            f"Last known GPS location: "
            f"Lat {payload.latitude:.6f}, Lon {payload.longitude:.6f}. "
            f"https://maps.google.com/?q={payload.latitude:.6f},{payload.longitude:.6f}"
        )
    else:
        # No location data at all
        message = (
            f"EMERGENCY ALERT: {patient_name} requires immediate medical assistance. "
            f"GPS location unavailable — please contact them immediately."
        )

    request_id = payload.request_id or f"legacy-{uuid4()}"
    request_digest = _request_id_digest(request_id)
    logger.info(
        "[EMERGENCY] Alert request received | user_id=%s | plan=%s "
        "| request=%s | has_location=%s",
        current_user.id,
        current_user.plan,
        request_digest,
        has_coords,
    )

    # ── 4. Subscription gate ──────────────────────────────────────────────────
    is_premium = has_active_paid_entitlement(current_user)

    if not is_premium:
        # Free user — log for internal MDQ+ dispatch, DO NOT fire Termii
        logger.info(
            "[EMERGENCY] NOK ineligible | user_id=%s | request=%s | reason=plan",
            current_user.id,
            request_digest,
        )
        return {
            "status": "logged",
            "message": (
                "Your emergency has been logged and flagged for MDQ+ dispatch. "
                "Automated Next of Kin SMS alerts require an active paid subscription. "
                "Upgrade your plan to enable instant NOK notifications."
            ),
            "nok_alert_queued": False,
            "upgrade_required": True,
        }

    # ── 5. Rate-limit checks (premium path only) ──────────────────────────────

    reservation = _reserve_emergency_sms(
        db,
        user_id=current_user.id,
        request_id=request_id,
        now=datetime.now(timezone.utc),
    )

    if reservation.outcome == "duplicate":
        logger.info(
            "[EMERGENCY] Duplicate alert request ignored | user_id=%s | request=%s",
            current_user.id,
            request_digest,
        )
        failed = reservation.request_status == "failed"
        return {
            "status": "failed" if failed else "duplicate",
            "message": (
                "Emergency alert request previously failed before provider acceptance."
                if failed
                else "Emergency alert request is already reserved or provider-accepted."
            ),
            "nok_alert_queued": False,
            "upgrade_required": False,
            "duplicate": True,
        }

    if reservation.outcome == "cooldown":
        logger.info(
            "[EMERGENCY] NOK blocked | user_id=%s | request=%s | reason=cooldown",
            current_user.id,
            request_digest,
        )
        return {
            "status": "logged",
            "message": (
                "Your emergency has been logged for MDQ+ dispatch. "
                "NOK alert is currently on cooldown."
            ),
            "nok_alert_queued": False,
            "upgrade_required": False,
            "cooldown_remaining_seconds": reservation.cooldown_remaining_seconds,
        }

    if reservation.outcome == "quota":
        logger.info(
            "[EMERGENCY] NOK blocked | user_id=%s | request=%s | reason=quota",
            current_user.id,
            request_digest,
        )
        return {
            "status": "logged",
            "message": (
                "Your emergency has been logged for MDQ+ dispatch. "
                "Your monthly NOK SMS quota has been reached — please contact MDQ+ support."
            ),
            "nok_alert_queued": False,
            "upgrade_required": False,
            "quota_exhausted": True,
        }

    logger.info(
        "[EMERGENCY] NOK slot reserved | user_id=%s | request=%s | count=%d",
        current_user.id,
        request_digest,
        reservation.sms_count,
    )

    # ── 7. Queue Termii SMS background task ───────────────────────────────────
    # Pass the raw stored value — termii_service.send_sms() sanitizes it
    background_tasks.add_task(
        _dispatch_sms,
        kin_phone.strip(),
        message,
        user_id=current_user.id,
        request_id=request_id,
        reserved_at=reservation.reserved_at,
        month_start=reservation.month_start,
    )

    logger.info(
        "[EMERGENCY] NOK alert queued | user_id=%s | request=%s",
        current_user.id,
        request_digest,
    )

    return {
        "status": "queued",
        "message": "Emergency alert requested for your Next of Kin.",
        "nok_alert_queued": True,
        "upgrade_required": False,
        "sms_remaining": _SMS_QUOTA - reservation.sms_count,
    }


# ─── Local Emergency Services Proxy ───────────────────────────────────────────

class LocalServiceResult(BaseModel):
    """A single nearby emergency service with a verified phone number."""

    name: str = Field(..., description="Display name of the facility")
    phone_number: str = Field(..., description="National phone number of the facility")
    category: Literal["hospital", "police"]


class LocalServicesResponse(BaseModel):
    status: Literal["success", "empty", "unavailable"]
    services: List[LocalServiceResult]


class _CategorySearchResult(NamedTuple):
    category: Literal["hospital", "police"]
    succeeded: bool
    services: List[LocalServiceResult]
    raw_count: int
    missing_phone_count: int


# Google New Places API constants
_PLACES_NEARBY_URL = "https://places.googleapis.com/v1/places:searchNearby"
_PLACES_FIELD_MASK = "places.displayName,places.nationalPhoneNumber"
_SEARCH_RADIUS_METERS = 5000.0
_TARGET_TYPES: tuple[Literal["hospital", "police"], ...] = ("hospital", "police")
_LOCAL_SERVICES_CACHE_TTL = timedelta(minutes=10)
_LOCAL_SERVICES_CACHE_MAX = 512
_LOCAL_SERVICES_CACHE: dict[tuple[float, float], tuple[datetime, List[LocalServiceResult]]] = {}
_PLACES_TIMEOUT_SECONDS = 10.0


def _local_services_cache_key(lat: float, lon: float) -> tuple[float, float]:
    return round(lat, 3), round(lon, 3)


async def _fetch_places_category(
    client: httpx.AsyncClient,
    *,
    category: Literal["hospital", "police"],
    lat: float,
    lon: float,
    api_key: str,
) -> _CategorySearchResult:
    started_at = perf_counter()
    try:
        response = await client.post(
            _PLACES_NEARBY_URL,
            json={
                "includedTypes": [category],
                "maxResultCount": 10,
                "locationRestriction": {
                    "circle": {
                        "center": {"latitude": lat, "longitude": lon},
                        "radius": _SEARCH_RADIUS_METERS,
                    }
                },
            },
            headers={
                "Content-Type": "application/json",
                "X-Goog-Api-Key": api_key,
                "X-Goog-FieldMask": _PLACES_FIELD_MASK,
            },
        )
        duration_ms = int((perf_counter() - started_at) * 1000)
        if response.status_code != status.HTTP_200_OK:
            logger.warning(
                "[LOCAL-SERVICES] Provider category failed | category=%s "
                "| http_class=%sxx | duration_ms=%d",
                category,
                response.status_code // 100,
                duration_ms,
            )
            return _CategorySearchResult(category, False, [], 0, 0)

        data = response.json()
        places = data.get("places", [])
        if not isinstance(places, list):
            raise ValueError("Places response field was not a list")

        services: List[LocalServiceResult] = []
        missing_phone_count = 0
        for place in places:
            if not isinstance(place, dict):
                continue
            display_name_obj = place.get("displayName", {})
            name = (
                display_name_obj.get("text", "").strip()
                if isinstance(display_name_obj, dict)
                else str(display_name_obj).strip()
            )
            raw_phone = place.get("nationalPhoneNumber", "")
            phone = raw_phone.strip() if isinstance(raw_phone, str) else ""
            if not phone:
                missing_phone_count += 1
                continue
            if not name:
                continue
            services.append(
                LocalServiceResult(
                    name=name,
                    phone_number=phone,
                    category=category,
                )
            )

        logger.info(
            "[LOCAL-SERVICES] Provider category complete | category=%s "
            "| duration_ms=%d | raw=%d | missing_phone=%d | usable=%d",
            category,
            duration_ms,
            len(places),
            missing_phone_count,
            len(services),
        )
        return _CategorySearchResult(
            category,
            True,
            services,
            len(places),
            missing_phone_count,
        )
    except httpx.TimeoutException:
        logger.warning(
            "[LOCAL-SERVICES] Provider category timed out | category=%s",
            category,
        )
    except httpx.RequestError as exc:
        logger.warning(
            "[LOCAL-SERVICES] Provider category network failure | category=%s "
            "| error_type=%s",
            category,
            type(exc).__name__,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[LOCAL-SERVICES] Provider category parse failure | category=%s "
            "| error_type=%s",
            category,
            type(exc).__name__,
        )
    return _CategorySearchResult(category, False, [], 0, 0)


async def _search_places(
    *,
    lat: float,
    lon: float,
    api_key: str,
) -> list[_CategorySearchResult]:
    timeout = httpx.Timeout(_PLACES_TIMEOUT_SECONDS)
    async with httpx.AsyncClient(timeout=timeout) as client:
        return list(
            await asyncio.gather(
                *(
                    _fetch_places_category(
                        client,
                        category=category,
                        lat=lat,
                        lon=lon,
                        api_key=api_key,
                    )
                    for category in _TARGET_TYPES
                )
            )
        )


@router.get(
    "/local-services",
    response_model=LocalServicesResponse,
    status_code=status.HTTP_200_OK,
    summary="Nearby emergency services",
    description=(
        "Secure proxy for the Google Places API. Returns hospitals and police "
        "stations within 5 km of the supplied coordinates. Only places that "
        "have a registered phone number are included."
    ),
)
@limiter.limit("30/hour")
async def get_local_services(
    request: Request,
    lat: float = Query(..., ge=-90, le=90, description="Latitude of the user's position"),
    lon: float = Query(..., ge=-180, le=180, description="Longitude of the user's position"),
    current_user: User = Depends(deps.get_current_user),
) -> LocalServicesResponse:
    """
    GET /api/v1/emergency/local-services?lat=<float>&lon=<float>

    Proxies Places API (New), searches hospital and police concurrently, and
    distinguishes provider failure from a genuine zero-usable-result outcome.
    """
    cache_key = _local_services_cache_key(lat, lon)
    now_utc = datetime.now(timezone.utc)
    cached = _LOCAL_SERVICES_CACHE.get(cache_key)
    if cached and now_utc - cached[0] < _LOCAL_SERVICES_CACHE_TTL:
        logger.info("[LOCAL-SERVICES] Successful cache hit | user_id=%s", current_user.id)
        return LocalServicesResponse(status="success", services=cached[1])

    api_key: Optional[str] = os.getenv("Maps_API_KEY")
    if not api_key:
        logger.warning(
            "[LOCAL-SERVICES] Search unavailable | reason=provider_not_configured"
        )
        return LocalServicesResponse(status="unavailable", services=[])

    logger.info("[LOCAL-SERVICES] Search started | user_id=%s", current_user.id)
    category_results = await _search_places(lat=lat, lon=lon, api_key=api_key)
    successful_categories = sum(result.succeeded for result in category_results)

    merged: List[LocalServiceResult] = []
    seen: set[tuple[str, str]] = set()
    for category_result in category_results:
        for service in category_result.services:
            dedup_key = (service.name.lower(), service.phone_number)
            if dedup_key not in seen:
                seen.add(dedup_key)
                merged.append(service)

    if merged:
        if len(_LOCAL_SERVICES_CACHE) >= _LOCAL_SERVICES_CACHE_MAX:
            _LOCAL_SERVICES_CACHE.clear()
        _LOCAL_SERVICES_CACHE[cache_key] = (now_utc, merged)
        logger.info(
            "[LOCAL-SERVICES] Search complete | outcome=%s | usable=%d",
            "success" if successful_categories == len(_TARGET_TYPES) else "partial_success",
            len(merged),
        )
        return LocalServicesResponse(status="success", services=merged)

    if successful_categories == len(_TARGET_TYPES):
        logger.info("[LOCAL-SERVICES] Search complete | outcome=zero_usable")
        return LocalServicesResponse(status="empty", services=[])

    logger.warning("[LOCAL-SERVICES] Search complete | outcome=unavailable")
    return LocalServicesResponse(status="unavailable", services=[])
