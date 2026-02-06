from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime


class ReadingDetail(BaseModel):
    """Individual reading from urinalysis strip"""
    value: str
    color: str


class LabReadings(BaseModel):
    """All urinalysis parameters"""
    leukocytes: Optional[ReadingDetail] = None
    nitrites: Optional[ReadingDetail] = None
    urobilinogen: Optional[ReadingDetail] = None
    protein: Optional[ReadingDetail] = None
    ph: Optional[ReadingDetail] = None
    blood: Optional[ReadingDetail] = None
    specific_gravity: Optional[ReadingDetail] = None
    ketones: Optional[ReadingDetail] = None
    bilirubin: Optional[ReadingDetail] = None
    glucose: Optional[ReadingDetail] = None


class LabAnalysisResponse(BaseModel):
    """Response from lab strip analysis"""
    status: str  # SUCCESS, REJECTED, ERROR
    lighting_score: Optional[str] = None
    readings: Optional[LabReadings] = None
    reason: Optional[str] = None  # For REJECTED/ERROR status
    notes: Optional[str] = None
    record_id: Optional[int] = None  # ID of saved LabResult if created


class LabResultOut(BaseModel):
    """Output schema for LabResult database record"""
    id: int
    user_id: int
    image_url: Optional[str] = None
    raw_data: Optional[Dict[str, Any]] = None
    is_verified: bool
    lighting_score: Optional[str] = None
    created_at: datetime
    
    class Config:
        from_attributes = True
