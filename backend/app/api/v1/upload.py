import cloudinary
import cloudinary.uploader
import shutil
import os
from fastapi import APIRouter, UploadFile, File, HTTPException
from dotenv import load_dotenv

load_dotenv()

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
        print(f"Cloudinary Error: {e}")
        raise HTTPException(status_code=500, detail="Image upload failed")