import cloudinary
import cloudinary.uploader
import logging
import os
import shutil

from fastapi import APIRouter, UploadFile, File, HTTPException
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

router = APIRouter()

# 1. Configure Cloudinary
# (It reads these from your Render Environment Variables)
cloudinary.config( 
  cloud_name = os.getenv("CLOUDINARY_CLOUD_NAME"), 
  api_key = os.getenv("CLOUDINARY_API_KEY"), 
  api_secret = os.getenv("CLOUDINARY_API_SECRET"),
  secure = True
)

@router.post("/")
async def upload_image(file: UploadFile = File(...)):
    try:
        # 2. Upload directly to Cloudinary
        # "file.file" gives us the actual file object to send
        result = cloudinary.uploader.upload(file.file, folder="mediq_profile_pics")
        
        # 3. Get the Secure URL (starts with https://)
        image_url = result.get("secure_url")
        
        return {"url": image_url}

    except Exception as e:
        logger.error("Failed to upload image to Cloudinary: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail="Image upload failed")