from fastapi import APIRouter, UploadFile, File, HTTPException
import cloudinary
import cloudinary.uploader
import shutil
import os

router = APIRouter()

# --- CONFIGURATION ---
# I have plugged in your keys here so it works immediately.
cloudinary.config( 
  cloud_name = "dxx91qxdn", 
  api_key = "214721641666341", 
  api_secret = "bwpVumPh9JUxRuguJTZY09ByjMA",
  secure = True
)

@router.post("/", response_model=dict)
async def upload_image(file: UploadFile = File(...)):
    """
    Receives a file, uploads it to Cloudinary, and returns the public URL.
    """
    # 1. Validate File Type
    if not file.content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image")

    try:
        # 2. Upload to Cloudinary (Directly from the file stream)
        # 'folder="mediq_chat"' keeps your cloud organized
        result = cloudinary.uploader.upload(
            file.file, 
            folder="mediq_chat",
            resource_type="image"
        )

        # 3. Get the Secure URL (https://...)
        image_url = result.get("secure_url")

        # 4. Return in the format the Frontend expects
        return {"url": image_url}

    except Exception as e:
        print(f"❌ Cloudinary Upload Error: {e}")
        raise HTTPException(status_code=500, detail="Image upload failed")