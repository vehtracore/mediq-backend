"""Durable, privacy-safe product notification creation and push delivery."""

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Mapping

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core import notification_transport
from app.models.notification import Notification
from app.models.notification_device_token import NotificationDeviceToken
from app.models.user import User

logger = logging.getLogger("uvicorn.error")


class NotificationType:
    CONSULTATION_REQUEST = "consultation_request"
    CONSULTATION_PAYMENT_CONFIRMED = "consultation_payment_confirmed"
    CONSULTATION_ASSIGNED = "consultation_assigned"
    CONSULTATION_CONFIRMED = "consultation_confirmed"
    CONSULTATION_CANCELLED = "consultation_cancelled"
    CONSULTATION_ROOM_READY = "consultation_room_ready"
    CONSULTATION_COMPLETED = "consultation_completed"
    PRESCRIPTION_ADDED = "prescription_added"
    REFERRAL_CREATED = "referral_created"
    CONSULTATION_MISSED = "consultation_missed"
    SUBSCRIPTION_ACTIVATED = "subscription_activated"
    SUBSCRIPTION_PAYMENT_FAILED = "subscription_payment_failed"
    SUBSCRIPTION_CANCELLED = "subscription_cancelled"
    SUBSCRIPTION_EXPIRED = "subscription_expired"
    PAYOUT_SENT = "payout_sent"
    FAMILY_MEMBER_JOINED = "family_member_joined"
    FAMILY_JOINED = "family_joined"


@dataclass(frozen=True)
class NotificationTemplate:
    title: str
    body: str
    channel_id: str = notification_transport.GENERAL_CHANNEL_ID


_CONSULTATION_CHANNEL = notification_transport.CONSULTATIONS_CHANNEL_ID
_TEMPLATES: dict[str, NotificationTemplate] = {
    NotificationType.CONSULTATION_REQUEST: NotificationTemplate(
        "New consultation request",
        "A new consultation request is waiting for your review.",
        _CONSULTATION_CHANNEL,
    ),
    NotificationType.CONSULTATION_PAYMENT_CONFIRMED: NotificationTemplate(
        "Payment confirmed",
        "Your consultation payment has been confirmed.",
        _CONSULTATION_CHANNEL,
    ),
    NotificationType.CONSULTATION_ASSIGNED: NotificationTemplate(
        "Doctor assigned",
        "A doctor has accepted your consultation request.",
        _CONSULTATION_CHANNEL,
    ),
    NotificationType.CONSULTATION_CONFIRMED: NotificationTemplate(
        "Consultation confirmed",
        "Your consultation has been confirmed.",
        _CONSULTATION_CHANNEL,
    ),
    NotificationType.CONSULTATION_CANCELLED: NotificationTemplate(
        "Consultation cancelled",
        "Your consultation has been cancelled or declined.",
        _CONSULTATION_CHANNEL,
    ),
    NotificationType.CONSULTATION_ROOM_READY: NotificationTemplate(
        "Consultation room ready",
        "Your consultation room is ready.",
        _CONSULTATION_CHANNEL,
    ),
    NotificationType.CONSULTATION_COMPLETED: NotificationTemplate(
        "Consultation complete",
        "Your consultation record is now available in MDQ+.",
    ),
    NotificationType.PRESCRIPTION_ADDED: NotificationTemplate(
        "Prescription added",
        "A prescription has been added to your consultation.",
    ),
    NotificationType.REFERRAL_CREATED: NotificationTemplate(
        "Referral available",
        "A referral has been added to your consultation record.",
    ),
    NotificationType.CONSULTATION_MISSED: NotificationTemplate(
        "Consultation update",
        "A scheduled consultation was marked as missed.",
        _CONSULTATION_CHANNEL,
    ),
    NotificationType.SUBSCRIPTION_ACTIVATED: NotificationTemplate(
        "Subscription activated",
        "Your MDQ+ subscription is active.",
    ),
    NotificationType.SUBSCRIPTION_PAYMENT_FAILED: NotificationTemplate(
        "Subscription payment failed",
        "We could not process your subscription payment. Review your plan in MDQ+.",
    ),
    NotificationType.SUBSCRIPTION_CANCELLED: NotificationTemplate(
        "Subscription cancelled",
        "Automatic renewal has been cancelled. Review your access in MDQ+.",
    ),
    NotificationType.SUBSCRIPTION_EXPIRED: NotificationTemplate(
        "Subscription expired",
        "Your subscription access has expired.",
    ),
    NotificationType.PAYOUT_SENT: NotificationTemplate(
        "Payout sent",
        "A consultation payout has been processed.",
    ),
    NotificationType.FAMILY_MEMBER_JOINED: NotificationTemplate(
        "Family member joined",
        "A member has successfully joined your family plan.",
    ),
    NotificationType.FAMILY_JOINED: NotificationTemplate(
        "Family plan joined",
        "You have successfully joined a family plan.",
    ),
}

_ALLOWED_NAVIGATION_KEYS = {
    "appointment_id",
    "referral_id",
    "family_context",
    "subscription_destination",
}


def _safe_navigation_data(data: Mapping[str, object] | None) -> dict[str, str]:
    if not data:
        return {}
    safe: dict[str, str] = {}
    for key, value in data.items():
        if key not in _ALLOWED_NAVIGATION_KEYS or value is None:
            continue
        rendered = str(value)
        if len(rendered) <= 100:
            safe[key] = rendered
    return safe


def _existing_for_event(db: Session, event_key: str | None) -> Notification | None:
    if not event_key:
        return None
    return db.query(Notification).filter(Notification.event_key == event_key).first()


def notify_user(
    db: Session,
    *,
    user_id: int,
    notification_type: str,
    navigation_data: Mapping[str, object] | None = None,
    event_key: str | None = None,
) -> Notification | None:
    """Create one durable user event, then make one best-effort multicast attempt.

    Callers must invoke this only after the originating business transaction has
    committed. Every failure is contained here so product state cannot be rolled
    back by notification infrastructure.
    """
    template = _TEMPLATES.get(notification_type)
    if template is None:
        logger.error("[NOTIFICATION] Unknown notification type=%s", notification_type)
        return None
    if event_key and len(event_key) > 255:
        logger.error("[NOTIFICATION] Event key is too long type=%s", notification_type)
        return None

    try:
        existing = _existing_for_event(db, event_key)
        if existing is not None:
            return existing

        user = db.query(User).filter(User.id == user_id).first()
        if user is None:
            logger.warning("[NOTIFICATION] Recipient user_id=%s was not found", user_id)
            return None

        safe_data = _safe_navigation_data(navigation_data)
        record = Notification(
            user_id=user_id,
            type=notification_type,
            title=template.title,
            body=template.body,
            navigation_data=safe_data,
            event_key=event_key,
        )
        db.add(record)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            return _existing_for_event(db, event_key)
        db.refresh(record)

        if user.settings_notifications is False:
            return record

        registrations = (
            db.query(NotificationDeviceToken)
            .filter(NotificationDeviceToken.user_id == user_id)
            .all()
        )
        if not registrations:
            return record

        payload = {"type": notification_type, **safe_data}
        result = notification_transport.send_multicast_notification(
            tokens=[registration.token for registration in registrations],
            title=template.title,
            body=template.body,
            data=payload,
            channel_id=template.channel_id,
        )
        if result.permanent_failure_tokens:
            (
                db.query(NotificationDeviceToken)
                .filter(
                    NotificationDeviceToken.token.in_(
                        result.permanent_failure_tokens
                    )
                )
                .delete(synchronize_session=False)
            )
            db.commit()
        logger.info(
            "[NOTIFICATION] type=%s user_id=%s devices=%d delivered=%d "
            "permanent_failures=%d transient_failures=%d",
            notification_type,
            user_id,
            len(registrations),
            result.successful_count,
            len(result.permanent_failure_tokens),
            result.transient_failure_count,
        )
        return record
    except Exception as exc:
        db.rollback()
        logger.error(
            "[NOTIFICATION] type=%s user_id=%s failed=%s",
            notification_type,
            user_id,
            type(exc).__name__,
            exc_info=True,
        )
        return None


def room_ready_event_key(*, appointment_id: int, user_id: int) -> str:
    """Return a database-deduped two-minute delivery window key."""
    window = int(datetime.now(timezone.utc).timestamp()) // 120
    return f"appointment:{appointment_id}:room-ready:{user_id}:window:{window}"
