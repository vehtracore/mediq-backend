from fastapi import APIRouter, Depends, HTTPException
from app.api import deps
from app.models.user import User
from app.models.appointment import Appointment
from app.core.database import get_db
from sqlalchemy.orm import Session
import os
import time
from agora_token_builder import RtcTokenBuilder

router = APIRouter()

APP_ID = os.getenv("AGORA_APP_ID")
APP_CERTIFICATE = os.getenv("AGORA_APP_CERTIFICATE")

@router.get("/token/{appointment_id}")
def get_video_token(
    appointment_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user)
):
    """
    Generates a temporary token for the video room.
    Only the Patient or Doctor of this specific appointment can enter.
    """
    # 1. Verify Appointment Ownership
    appt = db.query(Appointment).filter(Appointment.id == appointment_id).first()
    if not appt:
        raise HTTPException(404, "Appointment not found")
        
    if appt.patient_id != current_user.id and appt.doctor_id != (current_user.doctor.id if current_user.doctor else None):
         # Note: current_user.doctor is a relationship check we might need to adjust based on your exact User model, 
         # but for now we assume simple ID checks.
         # Simpler check:
         doctor_user_id = appt.doctor.user_id if appt.doctor else -1
         if current_user.id != appt.patient_id and current_user.id != doctor_user_id:
            raise HTTPException(403, "Not authorized to join this call")

    # 2. Generate Token
    channel_name = f"appt_{appointment_id}"
    uid = current_user.id
    expiration_time_in_seconds = 3600 # 1 hour
    current_timestamp = int(time.time())
    privilege_expired_ts = current_timestamp + expiration_time_in_seconds
    role = 1 # 1 = Host/Publisher

    token = RtcTokenBuilder.buildTokenWithUid(
        APP_ID, APP_CERTIFICATE, channel_name, uid, role, privilege_expired_ts
    )

    return {
        "token": token, 
        "channel": channel_name, 
        "app_id": APP_ID, 
        "uid": uid
    }