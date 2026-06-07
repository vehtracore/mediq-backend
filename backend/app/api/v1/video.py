import logging
import os
import random
import time

from fastapi import APIRouter, Depends, HTTPException
from agora_token_builder import RtcTokenBuilder
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.notifications import dispatch_push
from app.models.appointment import Appointment
from app.models.user import User
from app.api import deps

logger = logging.getLogger(__name__)

router = APIRouter()

# Manually define the role (1 = Publisher, 2 = Subscriber)
Role_Publisher = 1


@router.get("/token/{appointment_id}")
def get_agora_token(
    appointment_id: int,
    current_user: User = Depends(deps.get_current_user),
    db: Session = Depends(get_db),
):
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
        uid = random.randint(1, 230)
        expiration_time_in_seconds = 3600
        current_timestamp = int(time.time())
        privilege_expired_ts = current_timestamp + expiration_time_in_seconds

        # Use our manual integer here
        role = Role_Publisher

        token = RtcTokenBuilder.buildTokenWithUid(
            app_id, app_certificate, channel_name, uid, role, privilege_expired_ts
        )

        # 4. Success Log
        logger.info("Agora token generated for channel: %s", channel_name)

        # 5. ── FCM: notify the patient that the consultation room is open ────────
        # Only fire when the caller is a doctor (has an associated Doctor row).
        # We look up the appointment to find the patient's FCM token.
        try:
            from app.models.doctor import Doctor
            doctor_row = db.query(Doctor).filter(Doctor.user_id == current_user.id).first()
            if doctor_row:
                appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
                if appt and appt.patient_id:
                    patient = db.query(User).filter(User.id == appt.patient_id).first()
                    if patient and patient.fcm_token:
                        doctor_name = doctor_row.full_name or "Your doctor"
                        dispatch_push(
                            token=patient.fcm_token,
                            title="🩺 Consultation Room Open",
                            body=f"Dr. {doctor_name} has opened your consultation room. Join now!",
                            data={
                                "type": "consultation_room_open",
                                "appointment_id": str(appointment_id),
                                "channel": channel_name,
                            },
                            event_label="VIDEO/ROOM_OPEN",
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
            "uid": uid,
            "app_id": app_id,
        }

    except Exception as e:
        # 6. Capture the real error log
        logger.error("Failed to generate Agora video token: %s", e, exc_info=True)
        # Send error to phone screen
        raise HTTPException(status_code=500, detail=f"Crash: {str(e)}")