from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.core.database import get_db
from app.models.content import HealthTip
from app.models.user import User
from app.schemas.content import HealthTipCreate, HealthTipUpdate, HealthTipResponse
from app.api.v1.admin import get_current_admin # Reuse admin dependency

router = APIRouter()

# --- PUBLIC ENDPOINTS ---

@router.get("/tips", response_model=List[HealthTipResponse])
def get_health_tips(
    skip: int = 0, 
    limit: int = 100, 
    db: Session = Depends(get_db)
):
    """
    Public endpoint to fetch health tips.
    """
    return db.query(HealthTip).order_by(HealthTip.created_at.desc()).offset(skip).limit(limit).all()

# --- ADMIN ENDPOINTS ---

@router.post("/admin/tips", response_model=HealthTipResponse, status_code=status.HTTP_201_CREATED)
def create_health_tip(
    tip_in: HealthTipCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    new_tip = HealthTip(**tip_in.model_dump())
    db.add(new_tip)
    db.commit()
    db.refresh(new_tip)
    return new_tip

@router.put("/admin/tips/{tip_id}", response_model=HealthTipResponse)
def update_health_tip(
    tip_id: int,
    tip_in: HealthTipUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    tip = db.query(HealthTip).filter(HealthTip.id == tip_id).first()
    if not tip:
        raise HTTPException(status_code=404, detail="Health Tip not found")
    
    update_data = tip_in.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(tip, field, value)
        
    db.commit()
    db.refresh(tip)
    return tip

@router.delete("/admin/tips/{tip_id}")
def delete_health_tip(
    tip_id: int,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    tip = db.query(HealthTip).filter(HealthTip.id == tip_id).first()
    if not tip:
        raise HTTPException(status_code=404, detail="Health Tip not found")
        
    db.delete(tip)
    db.commit()
    return {"message": "Health Tip deleted successfully"}