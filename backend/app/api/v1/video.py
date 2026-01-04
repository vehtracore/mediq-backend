from fastapi import APIRouter, Depends, HTTPException
from app.core.security import get_current_user
# Use raw os to get env vars (safest method)
import os 
import time
import random
import traceback
from agora_token_builder import RtcTokenBuilder, Role_Publisher 

router = APIRouter()

@router.get("/token/{appointment_id}")
def get_agora_token(appointment_id: int, current_user = Depends(get_current_user)):
    try:
        # 1. Fetch Keys directly from Environment (Bypasses config.py issues)
        app_id = os.getenv("AGORA_APP_ID")
        app_certificate = os.getenv("AGORA_APP_CERTIFICATE")
        
        channel_name = f"appt_{appointment_id}"
        
        # 2. Strict Check with Logging
        if not app_id or not app_certificate:
            print(f"❌ CRITICAL ERROR: Agora Keys missing. ID: {app_id}, Cert: {app_certificate}")
            raise Exception("Agora Credentials are missing in Render Environment Variables!")

        # 3. Generate Token
        uid = random.randint(1, 230) 
        expiration_time_in_seconds = 3600
        current_timestamp = int(time.time())
        privilege_expired_ts = current_timestamp + expiration_time_in_seconds
        role = Role_Publisher

        token = RtcTokenBuilder.buildTokenWithUid(
            app_id, app_certificate, channel_name, uid, role, privilege_expired_ts
        )
        
        # 4. Success Log
        print(f"✅ Token generated for channel: {channel_name}")

        return {
            "token": token,
            "channel": channel_name,
            "uid": uid,
            "app_id": app_id
        }
    
    except Exception as e:
        # 5. Capture the real error log
        print(f"❌ VIDEO CRASH: {traceback.format_exc()}")
        # Send error to phone screen
        raise HTTPException(status_code=500, detail=f"Crash: {str(e)}")