import logging
from datetime import datetime
from fastapi import (
    APIRouter,
    UploadFile,
    File,
    Header,
    HTTPException,
    Depends,
    Request,
)
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.api_errors import ApiError
from app.api.deps import get_current_user
from app.api.v1.ai_consent import require_active_ai_consent
from app.models.user import User
from app.models.lab_result import LabResult
from app.services.ai_service import AIInputLimitError, analyze_lab_strip
from app.services.lab_image_quality import assess_lab_image_quality
from app.services.lab_scan_guard import (
    add_scan_failure_guidance,
    enforce_lab_scan_guard,
    record_lab_scan_failure,
    record_lab_scan_success,
)
from app.services.ai_usage import (
    PAID_MONTHLY_HEAVY_AI_LIMIT,
    monthly_heavy_ai_usage,
    reset_monthly_ai_usage,
)
from app.services.ai_request_guard import (
    AIRequestLease,
    acquire_ai_request_lease,
    release_ai_request_lease,
)
from app.services.media_service import (
    delete_sensitive_media,
    detect_upload_media_type,
    upload_sensitive_media,
)
from app.schemas.lab import LabAnalysisResponse

logger = logging.getLogger(__name__)

from app.core.limiter import limiter

router = APIRouter()

# Allowed image types
ALLOWED_CONTENT_TYPES = {"image/jpeg", "image/png", "image/webp", "image/jpg"}
_MAX_LAB_IMAGE_BYTES = 5 * 1024 * 1024

# Plans that have access to AI lab analysis
_LAB_ELIGIBLE_PLANS = {"premium", "family"}


def require_lab_ai_request_slot(
    x_ai_request_id: str | None = Header(
        default=None,
        alias="X-AI-Request-ID",
        min_length=8,
        max_length=128,
    ),
    current_user: User = Depends(get_current_user),
):
    lease = acquire_ai_request_lease(current_user.id, x_ai_request_id)
    try:
        yield lease
    finally:
        release_ai_request_lease(lease)


@router.post("/analyze", response_model=LabAnalysisResponse)
@limiter.limit("10/minute")
async def analyze_lab_image(
    request: Request,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
    request_lease: AIRequestLease = Depends(require_lab_ai_request_slot),
):
    """
    Analyze a urinalysis test strip image.

    - Validates the uploaded file is an image
    - Enforces the combined monthly AI photo/lab allowance
    - Sends the image to Gemini Vision for analysis
    - On SUCCESS, uploads to Cloudinary, saves a draft LabResult record,
      and increments the user's monthly quota counter
    - Returns the analysis results
    """

    # ── 0. Subscription gate ─────────────────────────────────────────────────
    # Both "premium" and "family" plan holders have access to AI Urinalysis.
    require_active_ai_consent(current_user)

    if current_user.plan not in _LAB_ELIGIBLE_PLANS:
        raise ApiError(
            403,
            "subscription_required",
            "Upgrade to MDQ+ Premium to access AI Urinalysis.",
        )

    # ── 1. Inline monthly reset ──────────────────────────────────────────────
    # Compare the stored reset date against the current year+month. If the
    # date is absent or belongs to a prior month/year, the counter is zeroed.
    # This is lazy: the reset happens on the first request of the new month,
    # so no background cron job is required.
    today = datetime.utcnow().date()

    reset_monthly_ai_usage(current_user, today)

    # ── 2. Enforce monthly quota ─────────────────────────────────────────────
    if monthly_heavy_ai_usage(current_user) >= PAID_MONTHLY_HEAVY_AI_LIMIT:
        raise ApiError(
            429,
            "quota_exceeded",
            (
                "You've used this month's 10 AI photo and lab "
                "interpretations. Your allowance resets next month."
            ),
        )

    enforce_lab_scan_guard(db, current_user)

    # ── 3. Validate file type ────────────────────────────────────────────────
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise ApiError(
            400,
            "unsupported_file",
            "We couldn't use this image. Choose a JPEG, PNG, or WebP image.",
        )

    try:
        # ── 4. Read image bytes ──────────────────────────────────────────────
        image_bytes = await file.read(_MAX_LAB_IMAGE_BYTES + 1)

        if len(image_bytes) == 0:
            raise ApiError(
                400,
                "invalid_file",
                "We couldn't use this image. Try taking another clear photo.",
            )
        if len(image_bytes) > _MAX_LAB_IMAGE_BYTES:
            raise ApiError(
                413,
                "file_too_large",
                "This image is too large. Choose an image under 5 MB.",
            )
        if detect_upload_media_type(image_bytes) not in {
            "image/jpeg",
            "image/png",
            "image/webp",
        }:
            raise ApiError(
                400,
                "unsupported_file",
                "We couldn't use this image. Choose a JPEG, PNG, or WebP image.",
            )

        quality_result = assess_lab_image_quality(image_bytes)
        if not quality_result.passed:
            failure_action = record_lab_scan_failure(db, current_user)
            request_lease.completed = True
            return {
                "status": "REJECTED",
                "reason": add_scan_failure_guidance(
                    quality_result.reason,
                    failure_action,
                ),
                "lighting_score": quality_result.lighting_score,
            }

        # ── 5. Analyze with Gemini Vision ────────────────────────────────────
        try:
            analysis_result = await analyze_lab_strip(image_bytes)
        except AIInputLimitError:
            raise ApiError(
                413,
                "file_too_large",
                "We couldn't use this image. Try taking another clear photo.",
            )

        # ── 6. Handle analysis result ────────────────────────────────────────
        status = analysis_result.get("status", "ERROR")

        if status == "SUCCESS":
            record_lab_scan_success(current_user)

            # Persist the successful scan with authenticated delivery. The
            # analysis response exposes only the logical record ID.
            await file.seek(0)
            image_asset = await upload_sensitive_media(
                file,
                media_class="lab_image",
            )

            # Save draft record to database
            lab_result = LabResult(
                user_id=current_user.id,
                image_url=None,
                image_public_id=image_asset.public_id,
                image_resource_type=image_asset.resource_type,
                image_format=image_asset.format,
                image_delivery_type=image_asset.delivery_type,
                raw_data=analysis_result,
                lighting_score=analysis_result.get("lighting_score"),
                is_verified=False,
            )
            db.add(lab_result)

            # ── 7. Increment quota counter ───────────────────────────────────
            # Successful scans always consume one monthly photo/lab unit.
            # Repeated unreadable scans are handled separately by lab_scan_guard.
            current_user.monthly_lab_count += 1
            db.add(current_user)

            try:
                db.commit()
                db.refresh(lab_result)
            except Exception:
                db.rollback()
                delete_sensitive_media(image_asset)
                raise

            # Add record ID to response
            analysis_result["record_id"] = lab_result.id

        elif status == "REJECTED":
            failure_action = record_lab_scan_failure(db, current_user)
            analysis_result["reason"] = add_scan_failure_guidance(
                analysis_result.get("reason"),
                failure_action,
            )

        request_lease.completed = True
        return analysis_result

    except HTTPException:
        raise
    except Exception as exc:
        logger.error(
            "[LAB] analysis failed failure_category=%s",
            type(exc).__name__,
            exc_info=True,
        )
        raise ApiError(
            503,
            "analysis_unavailable",
            "Analysis is temporarily unavailable. Please try again shortly.",
        )
