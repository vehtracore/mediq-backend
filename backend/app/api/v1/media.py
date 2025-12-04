from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from app.services import media_service
# Removed: from app.api import deps
# Removed: from app.models.user import User

router = APIRouter()

@router.post("/upload")
async def upload_file(
    file: UploadFile = File(...),
    folder: str = Form("mdq_plus/general"), 
    # REMOVED: current_user: User = Depends(deps.get_current_user)
):
    """
    Uploads a file. 
    OPEN ACCESS: Used for registration uploads (Licenses) and Profile pics.
    Returns: { "url": "https://..." }
    """
    # 1. Security Check: Validate file type
    if file.content_type not in ["image/jpeg", "image/png", "application/pdf"]:
        raise HTTPException(400, detail="Invalid file type. Only JPG, PNG, and PDF allowed.")

    # 2. Upload
    url = await media_service.upload_image(file, folder)
    
    return {"url": url}