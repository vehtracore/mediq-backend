import logging
import os
import random
import time

from fastapi import APIRouter, HTTPException
from agora_token_builder import RtcTokenBuilder

logger = logging.getLogger(__name__)

router = APIRouter()

# Manually define the role (1 = Publisher, 2 = Subscriber)
Role_Publisher = 1 

@router.get("/token/{appointment_id}")
def get_agora_token(appointment_id: int):
    try:
        # 1. Fetch Keys directly from Environment
        app_id = os.getenv("AGORA_APP_ID")
        app_certificate = os.getenv("AGORA_APP_CERTIFICATE")
        
        channel_name = f"appt_{appointment_id}"
        
        # 2. Strict Check with Logging
        if not app_id or not app_certificate:
            logger.error("Agora credentials missing — AGORA_APP_ID=%s, AGORA_APP_CERTIFICATE=%s", bool(app_id), bool(app_certificate))
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

        return {
            "token": token,
            "channel": channel_name,
            "uid": uid,
            "app_id": app_id
        }
    
    except Exception as e:
        # 5. Capture the real error log
        logger.error("Failed to generate Agora video token: %s", e, exc_info=True)
        # Send error to phone screen
        raise HTTPException(status_code=500, detail=f"Crash: {str(e)}")