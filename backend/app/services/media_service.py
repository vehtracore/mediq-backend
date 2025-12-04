import cloudinary
import cloudinary.uploader
import os
from fastapi import UploadFile, HTTPException

# Configure Cloudinary using the keys from your .env file
# It automatically reads CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY, etc.
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

async def upload_image(file: UploadFile, folder: str = "mdq_plus/general") -> str:
    """
    Uploads a file to Cloudinary and returns the secure URL.
    
    Args:
        file: The file object from FastAPI
        folder: The sub-folder in Cloudinary (e.g., 'mdq_plus/doctors')
    
    Returns:
        str: The URL of the uploaded image
    """
    try:
        # 1. Read file content
        content = await file.read()
        
        # 2. Upload to Cloudinary
        # 'folder' ensures we keep MDQ+ files separate from your other projects
        response = cloudinary.uploader.upload(
            content, 
            folder=folder,
            resource_type="auto" # Auto-detects image vs pdf vs video
        )
        
        # 3. Return the HTTPS URL
        return response.get("secure_url")

    except Exception as e:
        print(f"❌ Upload Error: {e}")
        raise HTTPException(status_code=500, detail="Image upload failed")