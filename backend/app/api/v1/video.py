import logging
import os
import time
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Request, status
from agora_token_builder import RtcTokenBuilder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.limiter import limiter
from app.models.user import User
from app.models.appointment import consultation_started_utc
from app.api import deps
from app.services.appointment_access import require_consultation_access
from app.services.notification_service import (
    NotificationType,
    notify_user,
    room_ready_event_key,
)
from app.services.consultation_pricing import (
    DEFAULT_CONSULTATION_DURATION_MINUTES,
    CONSULTATION_END_WARNING_MINUTES,
    CONSULTATION_MESSAGE_GRACE_MINUTES,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Manually define the role (1 = Publisher, 2 = Subscriber)
Role_Publisher = 1


def agora_uid_for_participant(appointment, current_user: User) -> int:
    """Derive the channel-local Agora identity from authorized membership."""
    if appointment.patient_id == current_user.id:
        return 1
    if (
        appointment.doctor is not None
        and appointment.doctor.user_id == current_user.id
    ):
        return 2
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="You do not have permission to access this consultation.",
    )


@router.get("/token/{appointment_id}")
@limiter.limit("30/hour")
@limiter.limit("10/minute")
def get_agora_token(
    request: Request,
    appointment_id: int,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db),
):
    appt = require_consultation_access(
        db,
        appointment_id,
        current_user,
        allow_completed=False,
    )

    try:
        # 1. Fetch Keys directly from Environment
        app_id = os.getenv("AGORA_APP_ID")
        app_certificate = os.getenv("AGORA_APP_CERTIFICATE")

        channel_name = f"appt_{appointment_id}"

        # 2. Strict Check with Logging
        if not app_id or not app_certificate:
            logger.error(
                "Agora credentials missing — AGORA_APP_ID=%s, AGORA_APP_CERTIFICATE=%s",
                bool(app_id),
                bool(app_certificate),
            )
            raise Exception("Agora Credentials are missing in Render Environment Variables!")

        # 3. Generate Token
        # Appointment membership owns Agora identity. The same participant gets
        # the same channel-local UID for both initial join and every renewal.
        token_uid = agora_uid_for_participant(appt, current_user)
        current_timestamp = int(time.time())
        consultation_start = consultation_started_utc(appt)
        if consultation_start is None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Both participants must join the consultation chat before starting a call.",
            )
        consultation_end = consultation_start + timedelta(
            minutes=DEFAULT_CONSULTATION_DURATION_MINUTES
        )
        warning_at = consultation_end - timedelta(
            minutes=CONSULTATION_END_WARNING_MINUTES
        )
        messages_end_at = consultation_end + timedelta(
            minutes=CONSULTATION_MESSAGE_GRACE_MINUTES
        )
        privilege_expired_ts = int(consultation_end.timestamp())
        if privilege_expired_ts <= current_timestamp:
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail="This consultation has ended.",
            )

        # Use our manual integer here
        role = Role_Publisher

        token = RtcTokenBuilder.buildTokenWithUid(
            app_id,
            app_certificate,
            channel_name,
            token_uid,
            role,
            privilege_expired_ts,
        )

        # 4. Success Log
        logger.info("Agora token generated for channel: %s", channel_name)

        # Only a doctor opening the room emits this durable, DB-deduped event.
        try:
            from app.models.doctor import Doctor
            doctor_row = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
            if doctor_row and appt.patient_id:
                notify_user(
                    db,
                    user_id=appt.patient_id,
                    notification_type=NotificationType.CONSULTATION_ROOM_READY,
                    navigation_data={"appointment_id": appointment_id},
                    event_key=room_ready_event_key(
                        appointment_id=appointment_id,
                        user_id=appt.patient_id,
                    ),
                )
        except Exception as notif_exc:
            # Never crash token generation because of a notification failure.
            logger.error(
                "[VIDEO] FCM room-open notification failed for appointment_id=%s: %s",
                appointment_id,
                notif_exc,
                exc_info=True,
            )

        return {
            "token": token,
            "channel": channel_name,
            "uid": token_uid,
            "app_id": app_id,
            "warning_at": warning_at.isoformat(),
            "video_ends_at": consultation_end.isoformat(),
            "messages_end_at": messages_end_at.isoformat(),
        }

    except HTTPException:
        raise
    except Exception as e:
        # 6. Capture the real error log
        logger.error("Failed to generate Agora video token: %s", e, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Video service is temporarily unavailable. Please try again.",
        )
