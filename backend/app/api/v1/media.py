from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from app.services import media_service
from app.api import deps
from app.models.user import User

router = APIRouter()

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder: str = Form("mdq_plus/general"), # Default folder
    current_user: User = Depends(deps.get_current_user) # Require Login
):
    """
    Uploads a file. 
    Only logged-in users can upload.
    Returns: { "url": "https://..." }
    """
    # 1. Security Check: Validate file type (Optional but recommended)
    if file.content_type not in ["image/jpeg", "image/png", "application/pdf"]:
        raise HTTPException(400, detail="Invalid file type. Only JPG, PNG, and PDF allowed.")

    # 2. Upload
    url = await media_service.upload_image(file, folder)
    
    return {"url": url}