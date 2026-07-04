import logging

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile

from app.api import deps
from app.core.limiter import limiter
from app.models.user import User
from app.services.media_service import upload_image as upload_media_file

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post("/")
@limiter.limit("20/hour")
async def upload_profile_image(
    request: Request,
    file: UploadFile = File(...),
    current_user: User = Depends(deps.get_current_user),
):
    """Authenticated profile image upload to Cloudinary."""
    try:
        image_url = await upload_media_file(file, folder="mediq_profile_pics")
        logger.info(
            "[UPLOAD] Profile image uploaded for user_id=%s",
            current_user.id,
        )
        return {"url": image_url}

    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to upload image to Cloudinary: %s", e, exc_info=True)
        raise HTTPException(status_code=502, detail="Image upload failed") from e
