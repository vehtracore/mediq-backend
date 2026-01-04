from fastapi import APIRouter, Depends, HTTPException
from app.core.config import settings
from app.core.security import get_current_user
# Make sure you added 'agora-token-builder' to requirements.txt
from agora_token_builder import RtcTokenBuilder, Role_Publisher 
import time
import random
import traceback # <--- Added for debugging

router = APIRouter()

@router.get("/token/{appointment_id}")
def get_agora_token(appointment_id: int, current_user = Depends(get_current_user)):
    try:
        app_id = settings.AGORA_APP_ID
        app_certificate = settings.AGORA_APP_CERTIFICATE
        channel_name = f"appt_{appointment_id}"
        
        # Ensure credentials exist
        if not app_id or not app_certificate:
            raise Exception("Agora Credentials are missing in Render Environment!")

        # Generate a random UID for the user (Agora needs an Int)
        uid = random.randint(1, 4000000) # Increased range to avoid collisions
        expiration_time_in_seconds = 3600
        current_timestamp = int(time.time())
        privilege_expired_ts = current_timestamp + expiration_time_in_seconds
        role = Role_Publisher

        token = RtcTokenBuilder.buildTokenWithUid(
            app_id, app_certificate, channel_name, uid, role, privilege_expired_ts
        )
        
        return {
            "token": token,
            "channel": channel_name,
            "uid": uid,
            "app_id": app_id
        }
    
    except Exception as e:
        # This will print the error to Render Logs
        print(f"❌ VIDEO CRASH: {traceback.format_exc()}")
        # This will send the error to your Phone Screen
        raise HTTPException(status_code=500, detail=f"Crash: {str(e)}")