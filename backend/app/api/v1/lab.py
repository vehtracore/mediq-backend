import cloudinary
import cloudinary.uploader
import os
from fastapi import APIRouter, UploadFile, File, HTTPException, Depends
from sqlalchemy.orm import Session
from dotenv import load_dotenv

from app.core.database import get_db
from app.api.deps import get_current_user
from app.models.user import User
from app.models.lab_result import LabResult
from app.services.ai_service import analyze_lab_strip
from app.schemas.lab import LabAnalysisResponse

load_dotenv()

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


@router.post("/analyze", response_model=LabAnalysisResponse)
async def analyze_lab_image(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """
    Analyze a urinalysis test strip image.
    
    - Validates the uploaded file is an image
    - Sends to Gemini Vision for analysis
    - If quality is good, saves a draft LabResult record
    - Returns the analysis results
    """
    
    # 1. Validate File Type
    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid file type. Allowed: {', '.join(ALLOWED_CONTENT_TYPES)}"
        )
    
    try:
        # 2. Read Image Bytes
        image_bytes = await file.read()
        
        if len(image_bytes) == 0:
            raise HTTPException(status_code=400, detail="Empty file uploaded")
        
        # 3. Analyze with Gemini Vision
        analysis_result = await analyze_lab_strip(image_bytes)
        
        # 4. Handle Analysis Result
        status = analysis_result.get("status", "ERROR")
        
        if status == "SUCCESS":
            # Upload image to Cloudinary for storage
            await file.seek(0)  # Reset file pointer
            upload_result = cloudinary.uploader.upload(
                file.file,
                folder="mediq_lab_scans"
            )
            image_url = upload_result.get("secure_url")
            
            # Save draft record to database
            lab_result = LabResult(
                user_id=current_user.id,
                image_url=image_url,
                raw_data=analysis_result,
                lighting_score=analysis_result.get("lighting_score"),
                is_verified=False
            )
            db.add(lab_result)
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
            detail=f"Failed to analyze image: {str(e)}"
        )
