from datetime import datetime, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models.notification_device_token import NotificationDeviceToken


def claim_device_token(
    db: Session,
    *,
    user_id: int,
    installation_id: str,
    token: str,
    platform: str,
) -> NotificationDeviceToken:
    """Claim both unique identities in one database transaction."""
    now = datetime.now(timezone.utc)
    matches = (
        db.query(NotificationDeviceToken)
        .filter(
            or_(
                NotificationDeviceToken.installation_id == installation_id,
                NotificationDeviceToken.token == token,
            )
        )
        .with_for_update()
        .all()
    )
    installation = next(
        (row for row in matches if row.installation_id == installation_id),
        None,
    )
    token_owner = next((row for row in matches if row.token == token), None)

    if token_owner is not None and token_owner is not installation:
        db.delete(token_owner)
        db.flush()

    if installation is None:
        installation = NotificationDeviceToken(
            user_id=user_id,
            installation_id=installation_id,
            token=token,
            platform=platform,
            created_at=now,
            updated_at=now,
            last_seen_at=now,
        )
        db.add(installation)
    else:
        installation.user_id = user_id
        installation.token = token
        installation.platform = platform
        installation.updated_at = now
        installation.last_seen_at = now

    db.commit()
    db.refresh(installation)
    return installation


def unregister_device_token(
    db: Session,
    *,
    user_id: int,
    installation_id: str,
) -> bool:
    deleted = (
        db.query(NotificationDeviceToken)
        .filter(
            NotificationDeviceToken.user_id == user_id,
            NotificationDeviceToken.installation_id == installation_id,
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return bool(deleted)
