from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api import deps
from app.core.database import get_db
from app.models.notification import Notification
from app.models.user import User
from app.schemas.notification import NotificationResponse


router = APIRouter()


def _cleanup_old_notifications(db: Session, user_id: int):
    cutoff = datetime.now(timezone.utc) - timedelta(days=90)
    db.query(Notification).filter(
        Notification.user_id == user_id,
        Notification.created_at < cutoff,
    ).delete(synchronize_session=False)
    db.commit()


@router.get("/", response_model=list[NotificationResponse])
def get_notifications(
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    _cleanup_old_notifications(db, current_user.id)
    return (
        db.query(Notification)
        .filter(Notification.user_id == current_user.id)
        .order_by(Notification.created_at.desc())
        .all()
    )
