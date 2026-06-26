from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from urllib.parse import urlparse

from app.core.database import get_db
from app.models.content import HealthTip
from app.models.user import User
from app.schemas.content import HealthTipCreate, HealthTipUpdate, HealthTipResponse
from app.api.v1.admin import get_current_admin # Reuse admin dependency

router = APIRouter()


RANDOM_PLACEHOLDER_IMAGE_HOSTS = {
    "source.unsplash.com",
    "images.unsplash.com",
    "unsplash.com",
    "picsum.photos",
    "loremflickr.com",
    "placehold.co",
    "placeholder.com",
    "via.placeholder.com",
    "dummyimage.com",
    "placekitten.com",
    "placebear.com",
    "fakeimg.pl",
}


def _normalize_optional_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return value


def _normalize_health_tip_image_url(value: object) -> str | None:
    value = _normalize_optional_url(value)
    if value is None:
        return None

    parsed = urlparse(value)
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    if (
        host in RANDOM_PLACEHOLDER_IMAGE_HOSTS
        or "placeholder" in host
        or "picsum" in host
        or "loremflickr" in host
    ):
        return None
    return value


def _normalize_url_fields(data: dict) -> dict:
    if "image_url" in data:
        data["image_url"] = _normalize_health_tip_image_url(data.get("image_url"))
    if "external_url" in data:
        data["external_url"] = _normalize_optional_url(data.get("external_url"))
    return data


def _strip_placeholder_images(tips: list[HealthTip]) -> list[HealthTip]:
    for tip in tips:
        tip.image_url = _normalize_health_tip_image_url(tip.image_url)
    return tips

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
    tips = (
        db.query(HealthTip)
        .order_by(HealthTip.created_at.desc())
        .offset(skip)
        .limit(limit)
        .all()
    )
    return _strip_placeholder_images(tips)

# --- ADMIN ENDPOINTS ---

@router.post("/admin/tips", response_model=HealthTipResponse, status_code=status.HTTP_201_CREATED)
def create_health_tip(
    tip_in: HealthTipCreate,
    db: Session = Depends(get_db),
    admin: User = Depends(get_current_admin)
):
    new_tip = HealthTip(**_normalize_url_fields(tip_in.model_dump()))
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
    
    update_data = _normalize_url_fields(tip_in.model_dump(exclude_unset=True))

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
