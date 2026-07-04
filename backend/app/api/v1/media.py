from fastapi import APIRouter, Depends, File, Form, Request, UploadFile

from app.api import deps
from app.core.limiter import limiter
from app.models.user import User
from app.services import media_service

router = APIRouter()


@router.post("/upload")
@limiter.limit("20/hour")
async def upload_file(
    request: Request,
    file: UploadFile = File(...),
    folder: str = Form("mdq_plus/general"),
    current_user: User = Depends(deps.get_current_user),
):
    """
    Authenticated media upload.

    The shared media service enforces allowed folders, file types, and size
    limits before any Cloudinary API call is made.
    """
    url = await media_service.upload_image(file, folder)
    return {"url": url}
