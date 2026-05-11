import cloudinary
import cloudinary.uploader
import os
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends, Request
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.lab_result import LabResult
from app.services.ai_service import analyze_lab_strip
from app.schemas.lab import LabAnalysisResponse

load_dotenv()

from app.core.limiter import limiter

router = APIRouter()

# Configure Cloudinary (same as upload.py)
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET"),
    secure=True
)

# Allowed image types
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/jpg"}

# Monthly cap for Premium lab scans (Gemini Vision calls)
MONTHLY_LAB_LIMIT: int = 10


@router.post("/analyze", response_model=LabAnalysisResponse)
@limiter.limit("10/minute")
async def analyze_lab_image(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Analyze a urinalysis test strip image.

    - Validates the uploaded file is an image
    - Enforces a monthly Gemini Vision quota (10 scans / month for Premium)
    - Sends the image to Gemini Vision for analysis
    - On SUCCESS, uploads to Cloudinary, saves a draft LabResult record,
      and increments the user's monthly quota counter
    - Returns the analysis results
    """

    # ── 0. Subscription gate ─────────────────────────────────────────────────
    if current_user.plan != "premium":
        raise HTTPException(
            status_code=403,
            detail="Upgrade to MDQ+ Premium to access AI Urinalysis.",
        )

    # ── 1. Inline monthly reset ──────────────────────────────────────────────
    # Compare the stored reset date against the current year+month. If the
    # date is absent or belongs to a prior month/year, the counter is zeroed.
    # This is lazy: the reset happens on the first request of the new month,
    # so no background cron job is required.
    today = datetime.utcnow().date()

    needs_reset = (
        current_user.last_lab_reset is None
        or current_user.last_lab_reset.year < today.year
        or (
            current_user.last_lab_reset.year == today.year
            and current_user.last_lab_reset.month < today.month
        )
    )
    if needs_reset:
        current_user.monthly_lab_count = 0
        current_user.last_lab_reset = today

    # ── 2. Enforce monthly quota ─────────────────────────────────────────────
    # Premium users are capped at MONTHLY_LAB_LIMIT Gemini Vision calls per
    # calendar month. The check runs before any file I/O so we fail fast.
    if current_user.monthly_lab_count >= MONTHLY_LAB_LIMIT:
        raise HTTPException(
            status_code=429,
            detail=(
                f"Monthly AI Lab Analysis limit ({MONTHLY_LAB_LIMIT}) reached. "
                "Your allowance resets at the start of next month."
            ),
        )

    # ── 3. Validate file type ────────────────────────────────────────────────
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_CONTENT_TYPES)}",
        )

    try:
        # ── 4. Read image bytes ──────────────────────────────────────────────
        image_bytes = await file.read()

        if len(image_bytes) == 0:
            raise HTTPException(status_code=400, detail="Empty file uploaded")

        # ── 5. Analyze with Gemini Vision ────────────────────────────────────
        analysis_result = await analyze_lab_strip(image_bytes)

        # ── 6. Handle analysis result ────────────────────────────────────────
        status = analysis_result.get("status", "ERROR")

        if status == "SUCCESS":
            # Upload image to Cloudinary for storage
            await file.seek(0)  # Reset file pointer
            upload_result = cloudinary.uploader.upload(
                file.file,
                folder="mediq_lab_scans",
            )
            image_url = upload_result.get("secure_url")

            # Save draft record to database
            lab_result = LabResult(
                user_id=current_user.id,
                image_url=image_url,
                raw_data=analysis_result,
                lighting_score=analysis_result.get("lighting_score"),
                is_verified=False,
            )
            db.add(lab_result)

            # ── 7. Increment quota counter ───────────────────────────────────
            # Quota is only charged on a confirmed SUCCESS response from Gemini.
            # A blurry or unrecognised image that Gemini rejects (status != SUCCESS)
            # does NOT count against the user's monthly allowance.
            current_user.monthly_lab_count += 1
            db.add(current_user)

            db.commit()
            db.refresh(lab_result)

            # Add record ID to response
            analysis_result["record_id"] = lab_result.id

        return analysis_result

    except HTTPException:
        raise
    except Exception as e:
        print(f"Lab Analysis Error: {e}")
        raise HTTPException(
            status_code=500,
            detail=f"Failed to analyze image: {str(e)}",
        )
