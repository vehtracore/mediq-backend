"""
Payments Router
================
Owns all Paystack-facing HTTP surface area for the MDQ+ platform.

Exposes:
  POST /api/v1/payments/initialize     â€” Server-side Paystack transaction init.
                                         Accepts (email, amount_kobo, reference)
                                         and returns an authorization_url so the
                                         Secret Key never touches the client.
  POST /api/v1/payments/webhook        â€” HMAC-verified Paystack webhook with
                                         reference-based routing and a Dead
                                         Letter Queue (DLQ) fallback.
  GET  /api/v1/payments/verify/{ref}   â€” Manual transaction verification for
                                         when the app loses connection before
                                         the webhook fires.

Security model
--------------
Paystack signs every outbound webhook payload with the account's secret key
using HMAC-SHA512. We recompute that digest from the raw request body (before
any JSON decoding) and compare with a timing-safe equality check. Any request
that fails this check is rejected with HTTP 400 before it touches the database.

Reference format
----------------
New format embedded by the Flutter client:
    MDQ-{transaction_type}-{appointment_id}-{user_id}-{epoch_ms}
    e.g.  MDQ-gp_consult-123-456-1777195558454

Old underscore-delimited references are handled gracefully (no IDs extracted).
"""

import hashlib
import hmac
import json
import logging
import os
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api import deps
from app.core.database import get_db
from app.core.limiter import limiter
from app.models.appointment import (
    APPOINTMENT_TYPE_GENERAL_QUEUE,
    APPOINTMENT_TYPE_SPECIALIST_SCHEDULED,
    APPOINTMENT_TYPE_VIP_REQUEST,
    Appointment,
    resolve_appointment_type,
)
from app.models.failed_webhook import FailedWebhook
from app.models.payment_event import PaymentEvent
from app.models.user import User
from app.models.doctor import Doctor
from app.models.consultation_payout import ConsultationPayout
from app.services.consultation_pricing import naira_to_kobo
from app.services.consultation_refund_service import REFUND_STATUS_AWAITING_ADMIN
from app.services.email_service import send_transactional_email
from app.services.paystack_amounts import paystack_requested_amount_kobo
from app.services.paystack_service import paystack_service  # noqa: F401 (used in future endpoints)
from app.services.notification_service import NotificationType, notify_user

logger = logging.getLogger(__name__)


# â”€â”€ Paystack credentials â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
PAYSTACK_SECRET_KEY: str = os.environ.get("PAYSTACK_SECRET_KEY", "")
if not PAYSTACK_SECRET_KEY:
    logger.warning(
        "[PAYMENTS] âš ï¸  PAYSTACK_SECRET_KEY is not set. "
        "The /webhook endpoint will reject every incoming request."
    )

PAYSTACK_VERIFY_URL = "https://api.paystack.co/transaction/verify"
PAYSTACK_INITIALIZE_URL = "https://api.paystack.co/transaction/initialize"
INDIVIDUAL_SUBSCRIPTION_AMOUNT_KOBO = 350_000
FAMILY_SUBSCRIPTION_AMOUNT_KOBO = 1_000_000
PAYSTACK_CURRENCY = 'NGN'
_PAYSTACK_INDIVIDUAL_PLAN_CODE_ENV = os.environ.get(
    'PAYSTACK_INDIVIDUAL_PLAN_CODE',
    '',
).strip()
_PAYSTACK_FAMILY_PLAN_CODE_ENV = os.environ.get(
    'PAYSTACK_FAMILY_PLAN_CODE',
    '',
).strip()
PAYSTACK_INDIVIDUAL_PLAN_CODE = (
    _PAYSTACK_INDIVIDUAL_PLAN_CODE_ENV
    or 'PLN_92o23tulrohyve4'
)
PAYSTACK_FAMILY_PLAN_CODE = (
    _PAYSTACK_FAMILY_PLAN_CODE_ENV
    or 'PLN_jb2m1yq93cun6x3'
)
PAYSTACK_WEBHOOK_MAX_BYTES = 256 * 1024

SUBSCRIPTION_CONFIG = {
    'subscription': {
        'plan': 'premium',
        'amount_kobo': INDIVIDUAL_SUBSCRIPTION_AMOUNT_KOBO,
        'plan_code': PAYSTACK_INDIVIDUAL_PLAN_CODE,
    },
    'family_subscription': {
        'plan': 'family',
        'amount_kobo': FAMILY_SUBSCRIPTION_AMOUNT_KOBO,
        'plan_code': PAYSTACK_FAMILY_PLAN_CODE,
    },
}


def _configured_paystack_environment() -> str | None:
    configured = os.environ.get('PAYSTACK_ENVIRONMENT', '').strip().lower()
    if configured in {'test', 'live'}:
        return configured
    if PAYSTACK_SECRET_KEY.startswith('sk_test_'):
        return 'test'
    if PAYSTACK_SECRET_KEY.startswith('sk_live_'):
        return 'live'
    return None


def _live_plan_configuration_is_complete() -> bool:
    return bool(
        _PAYSTACK_INDIVIDUAL_PLAN_CODE_ENV
        and _PAYSTACK_FAMILY_PLAN_CODE_ENV
    )

router = APIRouter()


# â”€â”€â”€ Schemas â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

class PaymentInitializeRequest(BaseModel):
    """
    Request body for POST /api/v1/payments/initialize.

    Fields
    ------
    email      : The customer's email address forwarded to Paystack.
    amount     : Transaction amount in **Kobo** (Naira Ã— 100). Must be > 0.
                 Required by Paystack even when a plan code is supplied.
    reference  : The pre-generated MDQ reference string. The backend stores this
                 on the Appointment row before calling /initialize so the watchdog
                 and webhook can locate the record immediately upon receipt.
    plan       : Optional Paystack Plan Code (e.g. ``PLN_xxxx``) for recurring
                 subscriptions. When present, Paystack will create a subscription
                 against this plan instead of a one-time charge. Omit entirely
                 (or pass null) for one-time consultation payments.
    """

    email: EmailStr
    amount: int = Field(..., gt=0, description="Amount in Kobo (Naira Ã— 100)")
    reference: str = Field(..., min_length=8, max_length=128, description="MDQ-prefixed transaction reference")
    plan: Optional[str] = Field(
        default=None,
        description="Paystack Plan Code for recurring subscriptions (e.g. PLN_xxxx). "
                    "Omit for one-time payments.",
    )


# â”€â”€â”€ Initialize Endpoint â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.post("/initialize", status_code=200)
@limiter.limit("20/hour")
@limiter.limit("5/minute")
async def initialize_transaction(
    request: Request,
    payload: PaymentInitializeRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    POST /api/v1/payments/initialize

    Exchanges the client-supplied (email, amount, reference) for a Paystack
    ``authorization_url`` and ``access_code``.  The Secret Key is used here on
    the server and is never forwarded to the Flutter client.

    Flow
    ----
    1. Flutter builds the MDQ reference and calls this endpoint.
    2. This endpoint calls Paystack /transaction/initialize with the Secret Key.
    3. Paystack returns an authorization_url + access_code.
    4. We return those two values to the Flutter app.
    5. Flutter opens the authorization_url in a WebView (flutter_paystack_plus
       can accept a checkout URL directly, no Secret Key required).
    6. After the user pays, Paystack fires a webhook to /webhook which confirms
       the DB record using the same reference.

    Error responses
    ---------------
    503  Payment service unavailable â€” PAYSTACK_SECRET_KEY not configured.
    502  Bad Gateway              â€” Could not reach Paystack.
    400  Bad Request              â€” Paystack rejected the initialization request.
    """

    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail="Payment service unavailable â€” secret key not configured.",
        )

    headers = {
        "Authorization": f"Bearer {PAYSTACK_SECRET_KEY}",
        "Content-Type": "application/json",
    }
    # Base payload â€” amount is always required by Paystack even for plan-based
    # recurring charges, so we never omit it regardless of whether plan is set.
    if not current_user.email:
        raise HTTPException(
            status_code=400,
            detail="Your account does not have a valid payment email.",
        )

    body: dict = {
        "email": current_user.email,
        "amount": payload.amount,
        "reference": payload.reference,
    }

    (
        transaction_type,
        ref_appointment_id,
        ref_user_id,
    ) = _validate_reference_owner_before_paystack(
        reference=payload.reference,
        db=db,
        current_user=current_user,
    )
    expected_subscription_amounts = {
        "subscription": INDIVIDUAL_SUBSCRIPTION_AMOUNT_KOBO,
        "family_subscription": FAMILY_SUBSCRIPTION_AMOUNT_KOBO,
    }
    expected_amount = expected_subscription_amounts.get(transaction_type)
    if expected_amount is not None and payload.amount != expected_amount:
        raise HTTPException(
            status_code=400,
            detail="Subscription amount does not match the configured plan price.",
        )
    if (
        expected_amount is not None
        and ref_user_id != str(current_user.id)
    ):
        raise HTTPException(
            status_code=403,
            detail="This payment reference does not belong to your account.",
        )

    try:
        appointment = _validate_consultation_payment(
            transaction_type=transaction_type,
            ref_appointment_id=ref_appointment_id,
            ref_user_id=ref_user_id,
            reference=payload.reference,
            amount_kobo=payload.amount,
            db=db,
            current_user=current_user,
            require_payable=True,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    # Consultation funds are collected by MDQ+ first. Doctor payout is handled
    # later through ConsultationPayout after the 24-hour complaint hold and
    # explicit admin approval. Do not attach a Paystack subaccount split here.

    metadata: dict = {
        "reference": payload.reference,
        "transaction_type": transaction_type,
    }
    if ref_user_id:
        metadata["user_id"] = ref_user_id
    if ref_appointment_id:
        metadata["appointment_id"] = ref_appointment_id
    body["metadata"] = metadata

    body['currency'] = PAYSTACK_CURRENCY

    # A plan changes the amount Paystack charges, so it must be selected from
    # the authenticated reference type on the server. The client value remains
    # accepted for API compatibility but cannot select a different plan.
    if transaction_type in SUBSCRIPTION_TRANSACTION_TYPES:
        if (
            _configured_paystack_environment() == 'live'
            and not _live_plan_configuration_is_complete()
        ):
            raise HTTPException(
                status_code=503,
                detail='Live subscription plans are not configured.',
            )
        expected_plan_code = SUBSCRIPTION_CONFIG[transaction_type]['plan_code']
        if payload.plan and payload.plan != expected_plan_code:
            raise HTTPException(
                status_code=400,
                detail='Subscription plan does not match the payment reference.',
            )
        payload.plan = expected_plan_code
    elif payload.plan:
        raise HTTPException(
            status_code=400,
            detail='A recurring plan cannot be attached to this payment type.',
        )

    # Conditionally attach the Plan Code for recurring subscriptions.
    if payload.plan:
        body["plan"] = payload.plan

    logger.info(
        "[PAYMENTS] initializing reference=%s user_id=%s amount_kobo=%d plan=%s",
        payload.reference,
        current_user.id,
        payload.amount,
        payload.plan or "(one-time)",
    )

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post(
                PAYSTACK_INITIALIZE_URL,
                headers=headers,
                json=body,
            )
    except httpx.RequestError as exc:
        logger.error(
            "[PAYMENTS] initialize_network_error reference=%s error_type=%s",
            payload.reference,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="Could not reach Paystack. Please try again.",
        )

    try:
        resp_data: dict = resp.json()
    except ValueError:
        resp_data = {}

    if not resp.is_success or not resp_data.get("status"):
        logger.error(
            "[PAYMENTS] initialize_rejected http_status=%s reference=%s",
            resp.status_code,
            payload.reference,
        )
        raise HTTPException(
            status_code=400,
            detail="The payment provider rejected this transaction.",
        )

    tx: dict = resp_data.get("data", {})
    authorization_url: str = tx.get("authorization_url", "")
    access_code: str = tx.get("access_code", "")

    logger.info(
        "[PAYMENTS] initialized reference=%s",
        payload.reference,
    )

    return {
        "authorization_url": authorization_url,
        "access_code": access_code,
        "reference": payload.reference,
    }


# â”€â”€â”€ Shared helpers â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

def _parse_reference(reference: str) -> tuple[str, str | None, str | None]:
    """
    Parse an MDQ reference string and return:
        (transaction_type, appointment_id_str, user_id_str)

    New dash-delimited format:
        MDQ-{type}-{appointment_id}-{user_id}-{timestamp}
    Old underscore format (no embedded IDs):
        MDQ_{type}_{timestamp}

    Returns empty strings / None for fields that cannot be extracted.
    """
    ref_parts = reference.split("-")
    # Expect at least 5 segments: MDQ | type | appt_id | user_id | timestamp
    ref_appointment_id: str | None = ref_parts[2] if len(ref_parts) >= 5 else None
    ref_user_id: str | None = ref_parts[3] if len(ref_parts) >= 5 else None

    transaction_type = ""
    if "gp_consult" in reference:
        transaction_type = "gp_consult"
    elif "specialist" in reference:
        transaction_type = "specialist_consult"
    elif "vip_request" in reference:           # VIP propose-and-pay flow
        transaction_type = "vip_request"
    elif "family_subscription" in reference:   # must precede plain "sub" check
        transaction_type = "family_subscription"
    elif "sub" in reference:
        transaction_type = "subscription"

    return transaction_type, ref_appointment_id, ref_user_id


CONSULTATION_TRANSACTION_TYPES = {
    "gp_consult",
    "specialist_consult",
    "vip_request",
}

EXPECTED_TRANSACTION_TYPE_BY_APPOINTMENT_TYPE = {
    APPOINTMENT_TYPE_GENERAL_QUEUE: "gp_consult",
    APPOINTMENT_TYPE_SPECIALIST_SCHEDULED: "specialist_consult",
    APPOINTMENT_TYPE_VIP_REQUEST: "vip_request",
}


SUBSCRIPTION_TRANSACTION_TYPES = {"subscription", "family_subscription"}
_REFERENCE_MAX_LENGTH = 128
_REFERENCE_ALLOWED_CHARS = set(
    "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
)


def _validate_reference_shape(reference: str) -> None:
    if not reference or len(reference) > _REFERENCE_MAX_LENGTH:
        raise HTTPException(status_code=400, detail="Invalid payment reference.")
    if reference.strip() != reference:
        raise HTTPException(status_code=400, detail="Invalid payment reference.")
    if not reference.startswith("MDQ-"):
        raise HTTPException(status_code=400, detail="Invalid payment reference.")
    if any(ch not in _REFERENCE_ALLOWED_CHARS for ch in reference):
        raise HTTPException(status_code=400, detail="Invalid payment reference.")


def _validate_reference_owner_before_paystack(
    *,
    reference: str,
    db: Session,
    current_user: User,
) -> tuple[str, str | None, str | None]:
    """Reject unknown or unowned references before spending a Paystack API call."""
    _validate_reference_shape(reference)
    transaction_type, ref_appointment_id, ref_user_id = _parse_reference(reference)

    if transaction_type not in CONSULTATION_TRANSACTION_TYPES | SUBSCRIPTION_TRANSACTION_TYPES:
        raise HTTPException(status_code=400, detail="Unsupported payment reference type.")

    if not ref_user_id or not ref_user_id.isdigit():
        raise HTTPException(status_code=400, detail="Payment reference is missing an owner.")
    if int(ref_user_id) != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="This payment reference does not belong to your account.",
        )

    if transaction_type in SUBSCRIPTION_TRANSACTION_TYPES:
        return transaction_type, ref_appointment_id, ref_user_id

    if not ref_appointment_id or not ref_appointment_id.isdigit():
        raise HTTPException(status_code=400, detail="Payment reference is missing an appointment.")

    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == int(ref_appointment_id))
        .first()
    )
    if appointment is None:
        raise HTTPException(status_code=404, detail="Consultation appointment was not found.")
    if appointment.paystack_reference != reference:
        raise HTTPException(status_code=403, detail="Payment reference does not match this appointment.")
    if appointment.patient_id != current_user.id or appointment.patient_id != int(ref_user_id):
        raise HTTPException(status_code=403, detail="Payment reference does not belong to your account.")

    expected_transaction_type = EXPECTED_TRANSACTION_TYPE_BY_APPOINTMENT_TYPE.get(
        resolve_appointment_type(appointment)
    )
    if expected_transaction_type != transaction_type:
        raise HTTPException(status_code=400, detail="Payment reference type does not match the appointment.")

    return transaction_type, ref_appointment_id, ref_user_id


def _validate_consultation_payment(
    *,
    transaction_type: str,
    ref_appointment_id: str | None,
    ref_user_id: str | None,
    reference: str,
    amount_kobo: int,
    db: Session,
    current_user: User | None = None,
    require_payable: bool = False,
) -> Appointment | None:
    """Bind a consultation payment to its owner, amount, type and state."""
    if transaction_type not in CONSULTATION_TRANSACTION_TYPES:
        return None
    if not ref_appointment_id or not ref_user_id:
        raise ValueError("Consultation payment reference is missing required IDs.")

    appointment = (
        db.query(Appointment)
        .filter(Appointment.id == int(ref_appointment_id))
        .first()
    )
    if appointment is None:
        raise ValueError("Consultation appointment was not found.")
    if appointment.paystack_reference != reference:
        raise ValueError("Payment reference does not match the appointment.")
    if appointment.patient_id != int(ref_user_id):
        raise ValueError("Payment reference patient does not match the appointment.")
    if current_user is not None and appointment.patient_id != current_user.id:
        raise HTTPException(
            status_code=403,
            detail="You cannot pay for another patient's appointment.",
        )

    expected_transaction_type = EXPECTED_TRANSACTION_TYPE_BY_APPOINTMENT_TYPE.get(
        resolve_appointment_type(appointment)
    )
    if expected_transaction_type != transaction_type:
        raise ValueError("Payment reference type does not match the appointment.")

    expected_amount_kobo = naira_to_kobo(appointment.amount or 0.0)
    if amount_kobo != expected_amount_kobo:
        raise ValueError("Payment amount does not match the appointment amount.")

    if require_payable:
        if appointment.payment_status != "unpaid":
            raise HTTPException(
                status_code=409,
                detail="This appointment has already been paid.",
            )
        payable_statuses = {
            "gp_consult": {"pending"},
            "specialist_consult": {"pending"},
            "vip_request": {"awaiting_payment"},
        }
        if appointment.status not in payable_statuses[transaction_type]:
            raise HTTPException(
                status_code=409,
                detail="This appointment is not currently payable.",
            )

    return appointment


def _persist_subscription_identifiers(user: User, paystack_data: dict | None) -> bool:
    """
    Persist Paystack subscription identifiers when they are present on a
    transaction or webhook payload. Paystack may return `subscription` as a
    nested object or as a plain subscription code depending on the event.
    """
    if not paystack_data:
        return False

    subscription_obj = paystack_data.get("subscription") or {}
    subscription_code: str | None = None
    email_token: str | None = None

    if isinstance(subscription_obj, dict):
        subscription_code = (
            subscription_obj.get("subscription_code")
            or subscription_obj.get("code")
        )
        email_token = subscription_obj.get("email_token")
    elif isinstance(subscription_obj, str):
        subscription_code = subscription_obj

    subscription_code = (
        subscription_code
        or paystack_data.get("subscription_code")
    )
    email_token = email_token or paystack_data.get("email_token")

    changed = False
    if subscription_code and user.paystack_subscription_code != subscription_code:
        user.paystack_subscription_code = subscription_code
        changed = True
    if email_token and user.paystack_email_token != email_token:
        user.paystack_email_token = email_token
        changed = True

    return changed


def _parse_paystack_datetime(value: str | None) -> datetime | None:
    if not value or not isinstance(value, str):
        return None

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None

    if parsed.tzinfo:
        return parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _payment_timestamp(paystack_data: dict | None) -> datetime | None:
    if not paystack_data:
        return None

    for key in ("paid_at", "paidAt", "transaction_date", "created_at"):
        parsed = _parse_paystack_datetime(paystack_data.get(key))
        if parsed:
            return parsed
    return None


def _add_calendar_month(value: datetime) -> datetime:
    month_index = value.month
    year = value.year + month_index // 12
    month = month_index % 12 + 1
    day = min(value.day, monthrange(year, month)[1])
    return value.replace(year=year, month=month, day=day)


def _next_subscription_expiry(
    current_expiry: datetime | None,
    payment_time: datetime | None = None,
) -> datetime:
    """
    Use a calendar month rather than a fixed day count. A provider payment
    timestamp is the deterministic fallback anchor, and an existing later
    paid-through date is never shortened by a delayed or out-of-order event.
    """
    now = datetime.utcnow()
    if current_expiry and current_expiry.tzinfo:
        current_expiry = current_expiry.astimezone(timezone.utc).replace(
            tzinfo=None
        )

    if payment_time is not None:
        candidate = _add_calendar_month(payment_time)
        if current_expiry and current_expiry > candidate:
            return current_expiry
        return candidate

    if current_expiry is None:
        return _add_calendar_month(now)

    comparison_now = (
        datetime.now(current_expiry.tzinfo)
        if current_expiry.tzinfo
        else now
    )
    base = current_expiry if current_expiry > comparison_now else comparison_now
    return _add_calendar_month(base)


def _is_subscription_entitlement_expired(expiry: datetime | None) -> bool:
    if expiry is None:
        return True

    if expiry.tzinfo:
        expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
    now = datetime.utcnow()
    return expiry <= now


class PaymentProcessingError(ValueError):
    def __init__(self, error_code: str, message: str):
        super().__init__(message)
        self.error_code = error_code


def _payment_error(error_code: str, message: str) -> None:
    raise PaymentProcessingError(error_code, message)


def _dict_value(value) -> dict:
    return value if isinstance(value, dict) else {}


def _code_from_object(value, *keys: str) -> str | None:
    if isinstance(value, str):
        return value or None
    if isinstance(value, dict):
        for key in keys:
            candidate = value.get(key)
            if candidate:
                return str(candidate)
    return None


def _subscription_event_details(data: dict) -> dict:
    subscription = _dict_value(data.get('subscription'))
    transaction = _dict_value(data.get('transaction'))
    customer = _dict_value(data.get('customer'))

    subscription_code = (
        _code_from_object(
            data.get('subscription'),
            'subscription_code',
            'code',
        )
        or _code_from_object(
            data,
            'subscription_code',
            'code',
        )
    )
    customer_code = (
        _code_from_object(data.get('customer'), 'customer_code', 'code')
        or _code_from_object(
            subscription.get('customer'),
            'customer_code',
            'code',
        )
        or _code_from_object(data, 'customer_code')
    )
    transaction_reference = str(
        data.get('reference')
        or data.get('transaction_reference')
        or transaction.get('reference')
        or ''
    )
    plan_value = (
        data.get('plan')
        or subscription.get('plan')
        or transaction.get('plan')
    )
    plan_code = _code_from_object(plan_value, 'plan_code', 'code')
    currency = str(
        data.get('currency')
        or transaction.get('currency')
        or ''
    ).upper()
    amount_source = data if data.get('amount') is not None else transaction
    email = str(
        customer.get('email')
        or data.get('email')
        or ''
    ).strip().lower()

    return {
        'subscription': subscription,
        'transaction': transaction,
        'subscription_code': subscription_code,
        'customer_code': customer_code,
        'transaction_reference': transaction_reference,
        'invoice_code': str(data.get('invoice_code') or ''),
        'plan_code': plan_code,
        'amount_kobo': paystack_requested_amount_kobo(amount_source),
        'currency': currency,
        'environment': str(
            data.get('domain')
            or transaction.get('domain')
            or ''
        ).lower(),
        'email': email,
        'period_start': _parse_paystack_datetime(data.get('period_start')),
        'period_end': _parse_paystack_datetime(data.get('period_end')),
        'next_payment_date': _parse_paystack_datetime(
            subscription.get('next_payment_date')
            or data.get('next_payment_date')
        ),
        'paid_at': (
            _parse_paystack_datetime(data.get('paid_at'))
            or _payment_timestamp(transaction)
            or _payment_timestamp(data)
        ),
        'provider_status': str(
            subscription.get('status')
            or data.get('status')
            or ''
        ).lower(),
        'email_token': (
            subscription.get('email_token')
            or data.get('email_token')
        ),
    }


def _subscription_type_for_user(
    user: User,
    details: dict,
    explicit_type: str | None = None,
) -> str:
    if explicit_type in SUBSCRIPTION_TRANSACTION_TYPES:
        return explicit_type
    if user.paystack_plan_code == PAYSTACK_FAMILY_PLAN_CODE:
        return 'family_subscription'
    if user.paystack_plan_code == PAYSTACK_INDIVIDUAL_PLAN_CODE:
        return 'subscription'
    if details.get('plan_code') == PAYSTACK_FAMILY_PLAN_CODE:
        return 'family_subscription'
    if details.get('plan_code') == PAYSTACK_INDIVIDUAL_PLAN_CODE:
        return 'subscription'
    if user.plan == 'family':
        return 'family_subscription'
    if user.plan == 'premium':
        return 'subscription'
    _payment_error(
        'unknown_subscription_plan',
        'The local subscription plan could not be determined.',
    )


def _validate_paystack_environment(details: dict, user: User | None = None) -> None:
    event_environment = details.get('environment')
    configured = _configured_paystack_environment()
    if event_environment not in {'test', 'live'}:
        _payment_error(
            'missing_environment',
            'The Paystack event has no valid environment.',
        )
    if configured and event_environment != configured:
        _payment_error(
            'environment_mismatch',
            'The Paystack event environment is not accepted here.',
        )
    if (
        user
        and user.paystack_environment
        and user.paystack_environment != event_environment
    ):
        _payment_error(
            'subscription_environment_mismatch',
            'The event environment does not match the subscription.',
        )


def _validate_subscription_payment(
    user: User,
    details: dict,
    *,
    explicit_type: str | None = None,
) -> tuple[str, dict]:
    _validate_paystack_environment(details, user)
    if (
        details.get('environment') == 'live'
        and not _live_plan_configuration_is_complete()
    ):
        _payment_error(
            'live_plan_configuration_missing',
            'Live Paystack plan codes are not configured.',
        )
    transaction_type = _subscription_type_for_user(
        user,
        details,
        explicit_type,
    )
    config = SUBSCRIPTION_CONFIG[transaction_type]

    if details.get('amount_kobo') != config['amount_kobo']:
        _payment_error(
            'amount_mismatch',
            'The subscription payment amount does not match the plan.',
        )
    if details.get('currency') != PAYSTACK_CURRENCY:
        _payment_error(
            'currency_mismatch',
            'The subscription payment currency is not supported.',
        )
    event_plan_code = details.get('plan_code')
    if event_plan_code and event_plan_code != config['plan_code']:
        _payment_error(
            'plan_mismatch',
            'The Paystack plan does not match the local subscription.',
        )
    if (
        user.paystack_plan_code
        and user.paystack_plan_code != config['plan_code']
    ):
        _payment_error(
            'stored_plan_mismatch',
            'The stored Paystack plan does not match the local subscription.',
        )
    return transaction_type, config


def _single_subscription_user(query) -> User | None:
    matches = query.with_for_update().limit(2).all()
    if len(matches) > 1:
        _payment_error(
            'ambiguous_subscription_identifier',
            'A Paystack identifier matches more than one local account.',
        )
    return matches[0] if matches else None


def _resolve_subscription_user(
    details: dict,
    db: Session,
    *,
    initial_user_id: int | None = None,
    allow_email_fallback: bool = True,
) -> User:
    user = None
    subscription_code = details.get('subscription_code')
    customer_code = details.get('customer_code')
    reference = details.get('transaction_reference')

    if subscription_code:
        user = _single_subscription_user(
            db.query(User)
            .filter(User.paystack_subscription_code == subscription_code)
        )
    if user is None and customer_code:
        user = _single_subscription_user(
            db.query(User)
            .filter(User.paystack_customer_code == customer_code)
        )
    if user is None and reference:
        user = _single_subscription_user(
            db.query(User)
            .filter(User.paystack_last_payment_reference == reference)
        )
        if user is None:
            prior_user_id = (
                db.query(PaymentEvent.user_id)
                .filter(
                    PaymentEvent.provider == 'paystack',
                    PaymentEvent.transaction_reference == reference,
                    PaymentEvent.user_id.isnot(None),
                )
                .order_by(PaymentEvent.id.desc())
                .scalar()
            )
            if prior_user_id:
                user = (
                    db.query(User)
                    .filter(User.id == prior_user_id)
                    .with_for_update()
                    .first()
                )
    if user is None and initial_user_id:
        user = (
            db.query(User)
            .filter(User.id == initial_user_id)
            .with_for_update()
            .first()
        )
    if user is None and allow_email_fallback and details.get('email'):
        candidate = (
            db.query(User)
            .filter(User.email == details['email'])
            .with_for_update()
            .first()
        )
        if candidate and (
            candidate.paystack_subscription_code
            or candidate.paystack_customer_code
            or (
                candidate.plan in {'premium', 'family'}
                and candidate.subscription_expiry is not None
            )
        ):
            user = candidate

    if user is None:
        _payment_error(
            'subscription_not_found',
            'No local subscription matched the Paystack identifiers.',
        )
    if (
        subscription_code
        and user.paystack_subscription_code
        and user.paystack_subscription_code != subscription_code
    ):
        _payment_error(
            'subscription_code_mismatch',
            'The subscription code does not match the local account.',
        )
    if (
        customer_code
        and user.paystack_customer_code
        and user.paystack_customer_code != customer_code
    ):
        _payment_error(
            'customer_code_mismatch',
            'The customer code does not match the local subscription.',
        )
    if details.get('email') and (
        not user.email
        or user.email.strip().lower() != details['email']
    ):
        _payment_error(
            'customer_email_mismatch',
            'The Paystack customer does not match the local account.',
        )
    return user


def _persist_subscription_identity(
    user: User,
    details: dict,
    *,
    plan_code: str | None = None,
) -> None:
    subscription_code = details.get('subscription_code')
    customer_code = details.get('customer_code')
    if subscription_code and not user.paystack_subscription_code:
        user.paystack_subscription_code = subscription_code
    if customer_code and not user.paystack_customer_code:
        user.paystack_customer_code = customer_code
    if plan_code and not user.paystack_plan_code:
        user.paystack_plan_code = plan_code
    if details.get('environment') and not user.paystack_environment:
        user.paystack_environment = details['environment']

    email_token = details.get('email_token')
    if email_token and not user.paystack_email_token:
        user.paystack_email_token = str(email_token)


def _renewal_expiry(user: User, details: dict) -> datetime:
    payment_time = details.get('paid_at') or datetime.utcnow()
    candidates = (
        details.get('next_payment_date'),
        details.get('period_end'),
    )
    for candidate in candidates:
        if candidate and candidate > payment_time:
            if user.subscription_expiry and user.subscription_expiry > candidate:
                return user.subscription_expiry
            return candidate
    return _next_subscription_expiry(
        user.subscription_expiry,
        payment_time,
    )


def _apply_subscription_payment(
    *,
    data: dict,
    db: Session,
    explicit_type: str | None = None,
    initial_user_id: int | None = None,
) -> dict:
    details = _subscription_event_details(data)
    user = _resolve_subscription_user(
        details,
        db,
        initial_user_id=initial_user_id,
    )
    transaction_type, config = _validate_subscription_payment(
        user,
        details,
        explicit_type=explicit_type,
    )
    reference = details.get('transaction_reference')
    paid_at = details.get('paid_at') or datetime.utcnow()

    if (
        user.paystack_last_successful_payment_at
        and paid_at < user.paystack_last_successful_payment_at
    ):
        return {
            'action': 'stale_subscription_payment_ignored',
            'user_id': user.id,
            'plan': transaction_type,
        }

    expiry = _renewal_expiry(user, details)
    user.plan = config['plan']
    user.subscription_expiry = expiry
    user.auto_renew = True
    user.paystack_subscription_status = (
        details.get('provider_status') or 'active'
    )
    user.paystack_last_payment_reference = reference or (
        user.paystack_last_payment_reference
    )
    user.paystack_last_successful_payment_at = paid_at
    user.paystack_current_period_start = (
        details.get('period_start')
        or user.paystack_current_period_start
        or paid_at
    )
    user.paystack_current_period_end = expiry
    user.paystack_next_payment_date = (
        details.get('next_payment_date')
        or user.paystack_next_payment_date
    )
    if details.get('invoice_code'):
        user.paystack_latest_invoice_code = details['invoice_code']
    _persist_subscription_identity(
        user,
        details,
        plan_code=config['plan_code'],
    )

    upgraded_dependents = []
    if transaction_type == 'family_subscription':
        dependents = (
            db.query(User)
            .filter(User.primary_account_id == user.id)
            .all()
        )
        for dependent in dependents:
            dependent.plan = 'family'
            dependent.subscription_expiry = expiry
        upgraded_dependents = [dependent.id for dependent in dependents]

    db.flush()
    return {
        'action': 'subscription_payment_applied',
        'user_id': user.id,
        'plan': transaction_type,
        'expiry': str(expiry),
        'dependents_upgraded': upgraded_dependents,
    }


def _apply_db_update(
    transaction_type: str,
    ref_appointment_id: str | None,
    ref_user_id: str | None,
    reference: str,
    db: Session,
    background_tasks: BackgroundTasks | None = None,
    paystack_data: dict | None = None,
) -> dict:
    # Subscription fulfilment is centralised here so webhook, manual verify,
    # and the watchdog use the same ownership and integrity checks.
    if transaction_type in SUBSCRIPTION_TRANSACTION_TYPES:
        if not paystack_data or paystack_data.get('status') != 'success':
            _payment_error(
                'transaction_not_successful',
                'Paystack did not report a successful subscription charge.',
            )
        if not ref_user_id or not ref_user_id.isdigit():
            _payment_error(
                'missing_payment_owner',
                'The subscription reference has no valid owner.',
            )
        result = _apply_subscription_payment(
            data=paystack_data,
            db=db,
            explicit_type=transaction_type,
            initial_user_id=int(ref_user_id),
        )
        db.commit()
        return result
    """
    Execute the database update for a confirmed Paystack transaction.

    Returns a dict describing what was done (used for both the webhook
    response and the verify endpoint response).

    Raises ValueError with a descriptive message if the required IDs are
    missing or the target record is not found â€” callers must handle this.
    """
    # â”€â”€ Flow A: Individual subscription upgrade â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # â”€â”€ Flow A2: Family Plan upgrade (payer + all dependents) â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if transaction_type in ("subscription", "family_subscription"):
        if not ref_user_id:
            raise ValueError(
                f"{transaction_type}: reference missing user_id segment (ref='{reference}')"
            )

        user: User | None = db.query(User).filter(User.id == int(ref_user_id)).first()
        if not user:
            raise ValueError(
                f"{transaction_type}: user id={ref_user_id} not found"
            )

        # â”€â”€ Upgrade the primary payer â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        expiry = _next_subscription_expiry(
            user.subscription_expiry,
            _payment_timestamp(paystack_data),
        )
        user.plan = "family" if transaction_type == "family_subscription" else "premium"
        user.subscription_expiry = expiry
        user.auto_renew = True
        identifiers_saved = _persist_subscription_identifiers(user, paystack_data)
        db.commit()
        db.refresh(user)

        logger.info(
            "[PAYMENTS] âœ… Subscription upgraded â€” user_id=%s (%s) | type=%s | expiry=%s",
            user.id,
            user.email,
            transaction_type,
            user.subscription_expiry,
        )
        if identifiers_saved:
            logger.info(
                "[PAYMENTS] âœ… Stored Paystack subscription identifiers for user_id=%s",
                user.id,
            )

        # â”€â”€ Flow A2 only: Bulk-upgrade all linked dependents â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        upgraded_dependents: list[int] = []
        if transaction_type == "family_subscription":
            dependents: list[User] = (
                db.query(User)
                .filter(User.primary_account_id == user.id)
                .all()
            )
            for dep in dependents:
                dep.plan = "family"
                dep.subscription_expiry = expiry

            if dependents:
                db.commit()
                upgraded_dependents = [d.id for d in dependents]
                logger.info(
                    "[PAYMENTS] âœ… Family Plan â€” upgraded %d dependent(s) | ids=%s | expiry=%s",
                    len(dependents),
                    upgraded_dependents,
                    expiry,
                )
            else:
                logger.info(
                    "[PAYMENTS] â„¹ï¸  Family Plan â€” primary user_id=%s has no linked dependents.",
                    user.id,
                )

        plan_label = "MDQ+ Family Plan" if transaction_type == "family_subscription" else "MDQ+ Premium"

        # â”€â”€ Queue confirmation email â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        if background_tasks and user.email:
            expiry_str = user.subscription_expiry.strftime('%d %B %Y')
            family_note = (
                f"<p>This plan also covers <strong>{len(upgraded_dependents)} linked member(s)</strong> "
                f"on your family account.</p>"
                if transaction_type == "family_subscription"
                else ""
            )
            html_body = f"""
            <div style="font-family:sans-serif;max-width:520px;margin:auto;">
              <h2 style="color:#4A90E2;">{plan_label} Activated ðŸŽ‰</h2>
              <p>Hi {user.first_name or 'there'},</p>
              <p>Your <strong>{plan_label}</strong> subscription is now active!</p>
              <p>Your plan has been upgraded and will remain active until
              <strong>{expiry_str}</strong>.</p>
              {family_note}
              <p>You now have access to:</p>
              <ul>
                <li>Unlimited AI health chats</li>
                <li>Priority doctor access</li>
                <li>Urinalysis AI &amp; advanced analytics</li>
                <li>Consultation summaries</li>
              </ul>
              <p style="color:#888;font-size:13px;">â€” The MDQ+ Team</p>
            </div>
            """
            background_tasks.add_task(
                send_transactional_email,
                to_email=user.email,
                subject=f"{plan_label} Activated ðŸŽ‰",
                html_body=html_body,
            )

        return {
            "action": "subscription_upgraded",
            "plan": transaction_type,
            "user_id": user.id,
            "expiry": str(user.subscription_expiry),
            "dependents_upgraded": upgraded_dependents,
        }

    # â”€â”€ Flow B: Appointment payment confirmation â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Covers: gp_consult, specialist_consult, and vip_request (propose-and-pay).
    elif transaction_type in ("gp_consult", "specialist_consult", "vip_request"):
        from app.models.appointment import Appointment  # local import â†’ no circular dep

        if not ref_appointment_id:
            raise ValueError(
                f"{transaction_type}: reference missing appointment_id segment "
                f"(ref='{reference}')"
            )

        appt: Appointment | None = (
            db.query(Appointment)
            .filter(Appointment.id == int(ref_appointment_id))
            .first()
        )
        if not appt:
            raise ValueError(
                f"{transaction_type}: appointment id={ref_appointment_id} not found"
            )

        was_schedule_confirmed = (
            appt.doctor_id is not None
            and appt.payment_status == "paid"
            and appt.status == "confirmed"
        )

        appt.payment_status = "paid"

        # Dual-pipeline confirmation:
        # â”Œâ”€ doctor_id IS set: direct booking OR VIP (propose-and-pay) â†’ confirm immediately.
        #    This covers both 'pending' (specialist direct) and 'awaiting_payment' (VIP after
        #    doctor proposed a time), so no status guard is needed here.
        # â””â”€ doctor_id IS NULL: General Queue â†’ stays 'pending' for manual doctor claiming.
        if appt.doctor_id is not None:
            appt.status = "confirmed"
        else:
            appt.status = "pending"

        db.commit()
        db.refresh(appt)

        logger.info(
            "[PAYMENTS] âœ… Appointment confirmed â€” appt_id=%s | type=%s | patient_id=%s",
            appt.id,
            transaction_type,
            appt.patient_id,
        )

        patient: User | None = (
            db.query(User).filter(User.id == appt.patient_id).first()
            if appt.patient_id
            else None
        )

        # â”€â”€ Queue appointment confirmation email â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
        # Look up the patient's email from the User table using patient_id.
        if background_tasks and patient:
            if patient and patient.email:
                type_label = (
                    "GP Consultation"
                    if transaction_type == "gp_consult"
                    else "Specialist Consultation"
                )
                html_body = f"""
                <div style="font-family:sans-serif;max-width:520px;margin:auto;">
                  <h2 style="color:#4A90E2;">Appointment Confirmed âœ…</h2>
                  <p>Hi {patient.first_name or 'there'},</p>
                  <p>Your <strong>{type_label}</strong> payment has been
                  confirmed and your appointment is now booked.</p>
                  <table style="border-collapse:collapse;width:100%;margin:16px 0;">
                    <tr style="background:#f5f5f5;">
                      <td style="padding:8px 12px;font-weight:bold;">Appointment ID</td>
                      <td style="padding:8px 12px;">#{appt.id}</td>
                    </tr>
                    <tr>
                      <td style="padding:8px 12px;font-weight:bold;">Reference</td>
                      <td style="padding:8px 12px;font-size:12px;color:#555;">{reference}</td>
                    </tr>
                    <tr style="background:#f5f5f5;">
                      <td style="padding:8px 12px;font-weight:bold;">Type</td>
                      <td style="padding:8px 12px;">{type_label}</td>
                    </tr>
                  </table>
                  <p>Your doctor will be in touch shortly. Open the
                  <strong>MDQ+ app</strong> to join your session at the
                  scheduled time.</p>
                  <p>Questions? Reply to this email or contact support in
                  the app.</p>
                  <p style="color:#888;font-size:13px;">â€” The MDQ+ Team</p>
                </div>
                """
                background_tasks.add_task(
                    send_transactional_email,
                    to_email=patient.email,
                    subject="MDQ+ Appointment Confirmed âœ…",
                    html_body=html_body,
                )

        doctor_user_id = None
        if appt.doctor_id is not None and not was_schedule_confirmed:
            doctor = db.query(Doctor).filter(Doctor.id == appt.doctor_id).first()
            doctor_user_id = doctor.user_id if doctor else None

        return {
            "action": "appointment_confirmed",
            "appointment_id": appt.id,
            "transaction_type": transaction_type,
            "patient_user_id": patient.id if patient else None,
            "doctor_user_id": doctor_user_id,
        }

    # â”€â”€ Unrecognised type â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    else:
        logger.warning(
            "[PAYMENTS] result=ignored_unrecognised_reference type='%s'",
            transaction_type,
        )
        return {"action": "ignored", "reason": f"unrecognised type '{transaction_type}'"}


def _write_dlq(
    reference: str,
    event_type: str,
    payload: dict,
    error_message: str,
    db: Session,
) -> None:
    """Persist safe identifiers and a bounded error classification only."""
    safe_keys = {
        'reference',
        'subscription_code',
        'invoice_code',
        'customer_code',
    }
    safe_payload = {
        key: value
        for key, value in payload.items()
        if key in safe_keys and value
    }
    safe_error_code = str(error_message)[:80]
    try:
        dlq_entry = FailedWebhook(
            reference=reference,
            event_type=event_type,
            payload=json.dumps(safe_payload),
            error_message=safe_error_code,
        )
        db.add(dlq_entry)
        db.commit()
        logger.error(
            '[PAYMENTS] result=dlq reference=%s error_code=%s',
            reference,
            safe_error_code,
        )
    except Exception as dlq_exc:
        db.rollback()
        logger.critical(
            '[PAYMENTS] result=dlq_write_failed reference=%s error_type=%s',
            reference,
            type(dlq_exc).__name__,
        )


def _metadata_user_id(data: dict) -> int | None:
    customer = _dict_value(data.get('customer'))
    metadata_values = (
        _dict_value(customer.get('metadata')),
        _dict_value(data.get('metadata')),
    )
    for metadata in metadata_values:
        raw_user_id = metadata.get('user_id')
        if raw_user_id is not None and str(raw_user_id).isdigit():
            return int(raw_user_id)
    return None


def _handle_recurring_charge_observed(data: dict, db: Session) -> dict:
    if data.get('status') != 'success':
        _payment_error(
            'transaction_not_successful',
            'The recurring charge was not successful.',
        )
    details = _subscription_event_details(data)
    if not details.get('subscription_code'):
        _payment_error(
            'missing_subscription_code',
            'The recurring charge has no subscription code.',
        )
    user = _resolve_subscription_user(details, db)
    transaction_type, config = _validate_subscription_payment(user, details)
    _persist_subscription_identity(
        user,
        details,
        plan_code=config['plan_code'],
    )
    db.flush()
    return {
        'action': 'recurring_charge_observed',
        'user_id': user.id,
        'plan': transaction_type,
    }


def _handle_invoice_update(data: dict, db: Session) -> dict:
    transaction = _dict_value(data.get('transaction'))
    if (
        data.get('paid') not in {True, 1}
        or str(data.get('status') or '').lower() != 'success'
        or str(transaction.get('status') or '').lower() != 'success'
    ):
        _payment_error(
            'invoice_not_paid',
            'The subscription invoice is not a successful paid invoice.',
        )
    return _apply_subscription_payment(data=data, db=db)


def _handle_invoice_payment_failed(data: dict, db: Session) -> dict:
    details = _subscription_event_details(data)
    user = _resolve_subscription_user(details, db)
    transaction_type, config = _validate_subscription_payment(user, details)
    _persist_subscription_identity(
        user,
        details,
        plan_code=config['plan_code'],
    )
    user.paystack_subscription_status = 'attention'
    if details.get('invoice_code'):
        user.paystack_latest_invoice_code = details['invoice_code']
    if details.get('next_payment_date'):
        user.paystack_next_payment_date = details['next_payment_date']
    db.flush()
    return {
        'action': 'subscription_payment_failed',
        'user_id': user.id,
        'plan': transaction_type,
        'access_preserved_until': str(user.subscription_expiry),
    }


def _handle_subscription_created(data: dict, db: Session) -> dict:
    details = _subscription_event_details(data)
    if not details.get('subscription_code'):
        _payment_error(
            'missing_subscription_code',
            'The subscription event has no subscription code.',
        )
    _validate_paystack_environment(details)
    user = _resolve_subscription_user(
        details,
        db,
        initial_user_id=_metadata_user_id(data),
        allow_email_fallback=False,
    )

    plan_code = details.get('plan_code')
    if plan_code not in {
        PAYSTACK_INDIVIDUAL_PLAN_CODE,
        PAYSTACK_FAMILY_PLAN_CODE,
    }:
        _payment_error(
            'plan_mismatch',
            'The subscription was created for an unknown Paystack plan.',
        )
    _validate_paystack_environment(details, user)
    _persist_subscription_identity(user, details, plan_code=plan_code)
    user.auto_renew = True
    user.paystack_subscription_status = (
        details.get('provider_status') or 'active'
    )
    user.paystack_next_payment_date = (
        details.get('next_payment_date')
        or user.paystack_next_payment_date
    )
    db.flush()
    return {
        'action': 'subscription_identifiers_persisted',
        'user_id': user.id,
    }


def _handle_subscription_lifecycle(
    data: dict,
    db: Session,
    *,
    event_type: str,
) -> dict:
    details = _subscription_event_details(data)
    user = _resolve_subscription_user(details, db)
    _validate_paystack_environment(details, user)
    _persist_subscription_identity(user, details)
    user.auto_renew = False
    if event_type == 'subscription.not_renew':
        user.paystack_subscription_status = 'non-renewing'
    else:
        user.paystack_subscription_status = (
            details.get('provider_status') or 'cancelled'
        )

    downgraded = _is_subscription_entitlement_expired(
        user.subscription_expiry
    )
    dependent_count = 0
    if downgraded:
        user.plan = 'free'
        user.subscription_expiry = None
        dependent_count = (
            db.query(User)
            .filter(User.primary_account_id == user.id)
            .update(
                {
                    User.plan: 'free',
                    User.subscription_expiry: None,
                    User.auto_renew: False,
                },
                synchronize_session=False,
            )
        )
    db.flush()
    return {
        'action': 'subscription_lifecycle_updated',
        'user_id': user.id,
        'subscription_code': details.get('subscription_code'),
        'provider_status': user.paystack_subscription_status,
        'downgraded': downgraded,
        'dependents_downgraded': dependent_count,
    }


def _handle_transfer_success(data: dict, db: Session) -> dict:
    """
    Handle transfer.success events to credit a doctor's earnings.

    Paystack sends the amount in kobo; we divide by 100 before storing.
    doctor_id is read from data.recipient.metadata.doctor_id first, then
    falls back to data.metadata.doctor_id.

    Raises ValueError when required fields are missing or the doctor is not found.
    """
    reference = str(data.get("reference") or "")
    ledger = (
        db.query(ConsultationPayout)
        .filter(ConsultationPayout.reference == reference)
        .with_for_update()
        .first()
        if reference
        else None
    )
    if ledger is not None:
        if ledger.status == "paid":
            return {
                "action": "payout_already_confirmed",
                "payout_id": ledger.id,
                "appointment_id": ledger.appointment_id,
            }
        if ledger.status == "reversed":
            return {
                "action": "payout_already_reversed",
                "payout_id": ledger.id,
                "appointment_id": ledger.appointment_id,
            }

        amount_kobo = int(data.get("amount") or 0)
        expected_amount_kobo = naira_to_kobo(float(ledger.amount))
        if amount_kobo != expected_amount_kobo:
            raise ValueError(
                "transfer.success amount does not match the payout ledger."
            )

        doctor = (
            db.query(Doctor)
            .filter(Doctor.id == ledger.doctor_id)
            .first()
        )
        if doctor is None:
            raise ValueError(
                f"transfer.success: doctor id={ledger.doctor_id} not found."
            )

        ledger.status = "paid"
        ledger.transfer_code = (
            data.get("transfer_code") or ledger.transfer_code
        )
        ledger.last_error = None
        ledger.paid_at = datetime.utcnow()
        current_earnings = Decimal(
            str(getattr(doctor, "total_earnings", None) or 0)
        )
        doctor.total_earnings = current_earnings + Decimal(str(ledger.amount))
        db.commit()
        db.refresh(ledger)
        db.refresh(doctor)

        return {
            "action": "consultation_payout_confirmed",
            "payout_id": ledger.id,
            "appointment_id": ledger.appointment_id,
            "doctor_id": doctor.id,
            "user_id": doctor.user_id,
            "amount_credited": float(ledger.amount),
        }

    # Legacy transfer events without a consultation payout reference.
    recipient: dict = data.get("recipient") or {}
    recipient_meta: dict = recipient.get("metadata") or {}
    top_meta: dict = data.get("metadata") or {}

    doctor_id_raw = recipient_meta.get("doctor_id") or top_meta.get("doctor_id")
    if not doctor_id_raw:
        raise ValueError(
            "transfer.success: doctor_id not found in data.recipient.metadata "
            "or data.metadata."
        )

    amount_kobo: int = int(data.get("amount") or 0)
    amount_naira: float = amount_kobo / 100.0

    doctor: Doctor | None = (
        db.query(Doctor).filter(Doctor.id == int(doctor_id_raw)).first()
    )
    if not doctor:
        raise ValueError(f"transfer.success: doctor id={doctor_id_raw} not found.")

    current_earnings: float = float(getattr(doctor, "total_earnings", None) or 0.0)
    doctor.total_earnings = current_earnings + amount_naira  # type: ignore[attr-defined]
    db.commit()
    db.refresh(doctor)

    logger.info(
        "[WEBHOOK] transfer.success â€” credited doctor_id=%s | amount=%.2f NGN "
        "| new total_earnings=%.2f",
        doctor.id,
        amount_naira,
        doctor.total_earnings,
    )

    return {
        "action": "doctor_earnings_credited",
        "doctor_id": doctor.id,
        "user_id": doctor.user_id,
        "amount_credited": amount_naira,
        "total_earnings": doctor.total_earnings,
    }


def _handle_transfer_status(
    data: dict,
    db: Session,
    *,
    status_value: str,
) -> dict:
    """Update a consultation payout for pending, failed or reversed transfers."""
    reference = str(data.get("reference") or "")
    if not reference:
        return {"action": "ignored_transfer_status_without_reference"}

    payout = (
        db.query(ConsultationPayout)
        .filter(ConsultationPayout.reference == reference)
        .with_for_update()
        .first()
    )
    if payout is None:
        return {"action": "ignored_non_consultation_transfer"}

    if status_value == "pending" and payout.status != "paid":
        payout.status = "processing"
    elif status_value == "failed" and payout.status != "paid":
        payout.status = "failed"
        payout.last_error = str(
            data.get("reason")
            or data.get("failures")
            or "Paystack transfer failed."
        )[:1000]
    elif status_value == "reversed":
        was_paid = payout.status == "paid"
        payout.status = "reversed"
        payout.last_error = "Paystack reversed the transfer."
        if was_paid:
            doctor = (
                db.query(Doctor)
                .filter(Doctor.id == payout.doctor_id)
                .first()
            )
            if doctor is not None:
                current = Decimal(
                    str(getattr(doctor, "total_earnings", None) or 0)
                )
                doctor.total_earnings = max(
                    Decimal("0.00"),
                    current - Decimal(str(payout.amount)),
                )

    payout.transfer_code = data.get("transfer_code") or payout.transfer_code
    db.commit()
    return {
        "action": f"consultation_payout_{status_value}",
        "payout_id": payout.id,
        "appointment_id": payout.appointment_id,
    }


def _handle_paystack_dispute(data: dict, db: Session, *, event: str) -> dict:
    """Freeze consultation payout when Paystack reports a customer dispute."""
    transaction = data.get("transaction") or {}
    reference = str(
        data.get("transaction_reference")
        or data.get("reference")
        or transaction.get("reference")
        or ""
    )
    if not reference:
        return {"action": "ignored_dispute_without_reference"}

    appointment = (
        db.query(Appointment)
        .filter(Appointment.paystack_reference == reference)
        .with_for_update()
        .first()
    )
    if appointment is None:
        transaction_type, ref_appointment_id, _ = _parse_reference(reference)
        if transaction_type in CONSULTATION_TRANSACTION_TYPES and ref_appointment_id:
            appointment = (
                db.query(Appointment)
                .filter(Appointment.id == int(ref_appointment_id))
                .with_for_update()
                .first()
            )

    if appointment is None:
        return {"action": "ignored_dispute_without_consultation"}

    appointment.refund_status = REFUND_STATUS_AWAITING_ADMIN
    appointment.refund_amount = appointment.amount
    appointment.refund_last_error = f"Paystack dispute received: {event}"
    db.commit()
    return {
        "action": "consultation_payout_frozen_for_dispute",
        "appointment_id": appointment.id,
        "refund_status": appointment.refund_status,
    }


RECOGNISED_PAYSTACK_EVENTS = {
    'charge.success',
    'invoice.update',
    'invoice.payment_failed',
    'subscription.create',
    'subscription.disable',
    'subscription.not_renew',
    'transfer.success',
    'transfer.pending',
    'transfer.failed',
    'transfer.reversed',
    'charge.dispute.create',
    'charge.dispute.remind',
    'refund.pending',
    'refund.processing',
    'refund.needs-attention',
    'refund.failed',
    'refund.processed',
}


def _provider_event_key(
    event_type: str,
    data: dict,
    raw_body: bytes,
) -> str:
    details = _subscription_event_details(data)
    environment = details.get('environment') or 'unknown'
    identifier = ''
    if event_type.startswith('invoice.'):
        identifier = details.get('invoice_code') or ''
    elif event_type.startswith('subscription.'):
        identifier = details.get('subscription_code') or ''
        if event_type in {'subscription.disable', 'subscription.not_renew'}:
            provider_status = details.get('provider_status') or 'unknown'
            identifier = f'{identifier}:{provider_status}'
    else:
        identifier = (
            details.get('transaction_reference')
            or str(data.get('transfer_code') or data.get('id') or '')
        )
    if not identifier:
        identifier = hashlib.sha256(raw_body).hexdigest()
    return f'{environment}:{event_type}:{identifier}'[:255]


def _payment_identity_key(
    event_type: str,
    data: dict,
    transaction_type: str,
) -> str | None:
    details = _subscription_event_details(data)
    reference = details.get('transaction_reference')
    environment = details.get('environment') or 'unknown'
    if not reference:
        return None
    if event_type == 'invoice.update':
        return f'{environment}:transaction:{reference}'[:255]
    if (
        event_type in {'charge.success', 'manual.verify'}
        and transaction_type
    ):
        return f'{environment}:transaction:{reference}'[:255]
    return None


def _find_payment_event(
    db: Session,
    *,
    provider_event_key: str,
    payment_key: str | None,
) -> PaymentEvent | None:
    conditions = [
        PaymentEvent.provider_event_key == provider_event_key,
    ]
    if payment_key:
        conditions.append(PaymentEvent.payment_key == payment_key)
    return (
        db.query(PaymentEvent)
        .filter(
            PaymentEvent.provider == 'paystack',
            or_(*conditions),
        )
        .with_for_update()
        .first()
    )


def _claim_payment_event(
    db: Session,
    *,
    event_type: str,
    provider_event_key: str,
    payment_key: str | None,
    reference: str,
    subscription_code: str | None,
    invoice_code: str | None,
) -> tuple[PaymentEvent, bool]:
    existing = _find_payment_event(
        db,
        provider_event_key=provider_event_key,
        payment_key=payment_key,
    )
    if existing:
        if existing.processing_status == 'failed':
            existing.processing_status = 'processing'
            existing.error_code = None
            existing.processing_note = None
            return existing, False
        return existing, True

    event = PaymentEvent(
        provider='paystack',
        event_type=event_type,
        provider_event_key=provider_event_key,
        payment_key=payment_key,
        transaction_reference=reference or None,
        subscription_code=subscription_code,
        invoice_code=invoice_code,
        processing_status='processing',
    )
    db.add(event)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        existing = _find_payment_event(
            db,
            provider_event_key=provider_event_key,
            payment_key=payment_key,
        )
        if existing is None:
            raise
        return existing, True
    return event, False


def _mark_payment_event_processed(
    event: PaymentEvent,
    *,
    user_id: int | None,
    action: str,
) -> None:
    event.user_id = user_id
    event.processing_status = 'processed'
    event.processed_at = datetime.now(timezone.utc)
    event.processing_note = action[:200]
    event.error_code = None


def _record_payment_event_failure(
    db: Session,
    *,
    event_type: str,
    provider_event_key: str,
    payment_key: str | None,
    reference: str,
    subscription_code: str | None,
    invoice_code: str | None,
    error_code: str,
) -> None:
    try:
        event = _find_payment_event(
            db,
            provider_event_key=provider_event_key,
            payment_key=payment_key,
        )
        if event is None:
            event = PaymentEvent(
                provider='paystack',
                event_type=event_type,
                provider_event_key=provider_event_key,
                payment_key=payment_key,
                transaction_reference=reference or None,
                subscription_code=subscription_code,
                invoice_code=invoice_code,
            )
            db.add(event)
        event.processing_status = 'failed'
        event.error_code = error_code[:80]
        event.processing_note = None
        db.commit()
    except Exception:
        db.rollback()
        logger.exception(
            '[PAYMENTS] payment_event_failure_record_failed event=%s reference=%s',
            event_type,
            reference,
        )


async def _verified_paystack_payload(request: Request) -> tuple[bytes, dict]:
    if not PAYSTACK_SECRET_KEY:
        logger.error('[WEBHOOK] rejected reason=secret_not_configured')
        raise HTTPException(
            status_code=503,
            detail='Webhook processing is unavailable.',
        )

    raw_content_length = request.headers.get('content-length')
    if raw_content_length:
        try:
            if int(raw_content_length) > PAYSTACK_WEBHOOK_MAX_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail='Webhook payload is too large.',
                )
        except ValueError:
            raise HTTPException(
                status_code=400,
                detail='Invalid webhook request.',
            )

    body = await request.body()
    if len(body) > PAYSTACK_WEBHOOK_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail='Webhook payload is too large.',
        )

    signature = request.headers.get('x-paystack-signature', '')
    if not signature:
        logger.warning('[WEBHOOK] rejected reason=missing_signature')
        raise HTTPException(
            status_code=400,
            detail='Invalid webhook signature.',
        )
    expected = hmac.new(
        PAYSTACK_SECRET_KEY.encode('utf-8'),
        msg=body,
        digestmod=hashlib.sha512,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        logger.warning('[WEBHOOK] rejected reason=invalid_signature')
        raise HTTPException(
            status_code=400,
            detail='Invalid webhook signature.',
        )

    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise HTTPException(
            status_code=400,
            detail='Malformed JSON payload.',
        )
    if not isinstance(payload, dict):
        raise HTTPException(
            status_code=400,
            detail='Malformed JSON payload.',
        )
    return body, payload


def _validate_successful_consultation_charge(data: dict) -> None:
    details = _subscription_event_details(data)
    if data.get('status') != 'success':
        _payment_error(
            'transaction_not_successful',
            'The consultation transaction was not successful.',
        )
    _validate_paystack_environment(details)
    if details.get('currency') != PAYSTACK_CURRENCY:
        _payment_error(
            'currency_mismatch',
            'The consultation payment currency is not supported.',
        )
    if details.get('plan_code'):
        _payment_error(
            'unexpected_plan',
            'A consultation charge cannot contain a subscription plan.',
        )


def _dispatch_paystack_event(
    *,
    event_type: str,
    data: dict,
    transaction_type: str,
    ref_appointment_id: str | None,
    ref_user_id: str | None,
    reference: str,
    db: Session,
    background_tasks: BackgroundTasks,
) -> dict:
    if event_type == 'charge.success':
        if transaction_type in SUBSCRIPTION_TRANSACTION_TYPES:
            return _apply_db_update(
                transaction_type=transaction_type,
                ref_appointment_id=ref_appointment_id,
                ref_user_id=ref_user_id,
                reference=reference,
                db=db,
                background_tasks=background_tasks,
                paystack_data=data,
            )
        if transaction_type in CONSULTATION_TRANSACTION_TYPES:
            _validate_successful_consultation_charge(data)
            _validate_consultation_payment(
                transaction_type=transaction_type,
                ref_appointment_id=ref_appointment_id,
                ref_user_id=ref_user_id,
                reference=reference,
                amount_kobo=paystack_requested_amount_kobo(data),
                db=db,
            )
            return _apply_db_update(
                transaction_type=transaction_type,
                ref_appointment_id=ref_appointment_id,
                ref_user_id=ref_user_id,
                reference=reference,
                db=db,
                background_tasks=background_tasks,
                paystack_data=data,
            )
        details = _subscription_event_details(data)
        if details.get('subscription_code'):
            return _handle_recurring_charge_observed(data, db)
        return {'action': 'unsupported_charge_ignored'}
    if event_type == 'invoice.update':
        return _handle_invoice_update(data, db)
    if event_type == 'invoice.payment_failed':
        return _handle_invoice_payment_failed(data, db)
    if event_type == 'subscription.create':
        return _handle_subscription_created(data, db)
    if event_type in {'subscription.disable', 'subscription.not_renew'}:
        return _handle_subscription_lifecycle(
            data,
            db,
            event_type=event_type,
        )
    if event_type == 'transfer.success':
        return _handle_transfer_success(data=data, db=db)
    if event_type in {'transfer.pending', 'transfer.failed', 'transfer.reversed'}:
        return _handle_transfer_status(
            data=data,
            db=db,
            status_value=event_type.removeprefix('transfer.'),
        )
    if event_type in {'charge.dispute.create', 'charge.dispute.remind'}:
        return _handle_paystack_dispute(
            data=data,
            db=db,
            event=event_type,
        )
    if event_type.startswith('refund.'):
        return _handle_refund_status(
            data=data,
            db=db,
            status_value=event_type.removeprefix('refund.'),
        )
    return {'action': 'event_ignored'}


def _emit_payment_notification(
    db: Session,
    *,
    result: dict,
    provider_event_key: str,
) -> None:
    action = result.get("action")

    def emit(
        user_id: int | None,
        notification_type: str,
        navigation_data: dict[str, object] | None = None,
        stable_event_key: str | None = None,
    ) -> None:
        if user_id is None:
            return
        notify_user(
            db,
            user_id=int(user_id),
            notification_type=notification_type,
            navigation_data=navigation_data,
            event_key=(stable_event_key or (
                f"paystack:{provider_event_key}:{notification_type}:{user_id}"
            ))[:255],
        )

    if action in {"subscription_payment_applied", "subscription_upgraded"}:
        emit(
            result.get("user_id"),
            NotificationType.SUBSCRIPTION_ACTIVATED,
            {"subscription_destination": "subscription"},
        )
    elif action == "subscription_payment_failed":
        emit(
            result.get("user_id"),
            NotificationType.SUBSCRIPTION_PAYMENT_FAILED,
            {"subscription_destination": "subscription"},
        )
    elif action == "subscription_lifecycle_updated":
        notification_type = (
            NotificationType.SUBSCRIPTION_EXPIRED
            if result.get("downgraded")
            else NotificationType.SUBSCRIPTION_CANCELLED
        )
        subscription_code = result.get("subscription_code") or "unknown"
        user_id = result.get("user_id")
        emit(
            user_id,
            notification_type,
            {"subscription_destination": "subscription"},
            f"subscription:{subscription_code}:{notification_type}:{user_id}",
        )
    elif action == "appointment_confirmed":
        appointment_id = result.get("appointment_id")
        navigation = {"appointment_id": appointment_id}
        emit(
            result.get("patient_user_id"),
            NotificationType.CONSULTATION_PAYMENT_CONFIRMED,
            navigation,
        )
        emit(
            result.get("doctor_user_id"),
            NotificationType.CONSULTATION_CONFIRMED,
            navigation,
        )
    elif action in {"consultation_payout_confirmed", "doctor_earnings_credited"}:
        emit(
            result.get("user_id"),
            NotificationType.PAYOUT_SENT,
            (
                {"appointment_id": result.get("appointment_id")}
                if result.get("appointment_id") is not None
                else None
            ),
        )


async def _process_paystack_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session,
) -> dict:
    raw_body, payload = await _verified_paystack_payload(request)
    event_type = str(payload.get('event') or 'unknown')
    raw_data = payload.get('data')
    data = raw_data if isinstance(raw_data, dict) else {}
    details = _subscription_event_details(data)
    reference = details.get('transaction_reference') or ''
    subscription_code = details.get('subscription_code')
    invoice_code = details.get('invoice_code') or None
    customer_code = details.get('customer_code')

    if event_type not in RECOGNISED_PAYSTACK_EVENTS:
        logger.info(
            '[WEBHOOK] event=%s reference=%s subscription_code=%s '
            'customer_code=%s result=ignored_unknown_event',
            event_type,
            reference,
            subscription_code,
            customer_code,
        )
        return {
            'status': 'success',
            'action': 'unknown_event_ignored',
        }
    if not isinstance(raw_data, dict):
        raise HTTPException(
            status_code=400,
            detail='Malformed webhook data.',
        )

    transaction_type, ref_appointment_id, ref_user_id = _parse_reference(
        reference
    )
    provider_event_key = _provider_event_key(
        event_type,
        data,
        raw_body,
    )
    payment_key = _payment_identity_key(
        event_type,
        data,
        transaction_type,
    )
    event_record, duplicate = _claim_payment_event(
        db,
        event_type=event_type,
        provider_event_key=provider_event_key,
        payment_key=payment_key,
        reference=reference,
        subscription_code=subscription_code,
        invoice_code=invoice_code,
    )
    if duplicate:
        db.rollback()
        logger.info(
            '[WEBHOOK] event=%s reference=%s subscription_code=%s '
            'customer_code=%s result=duplicate',
            event_type,
            reference,
            subscription_code,
            customer_code,
        )
        return {
            'status': 'success',
            'action': 'duplicate_event_ignored',
        }

    try:
        result = _dispatch_paystack_event(
            event_type=event_type,
            data=data,
            transaction_type=transaction_type,
            ref_appointment_id=ref_appointment_id,
            ref_user_id=ref_user_id,
            reference=reference,
            db=db,
            background_tasks=background_tasks,
        )
        _mark_payment_event_processed(
            event_record,
            user_id=result.get('user_id'),
            action=str(result.get('action') or 'processed'),
        )
        db.commit()
    except Exception as exc:
        db.rollback()
        error_code = (
            exc.error_code
            if isinstance(exc, PaymentProcessingError)
            else 'processing_failure'
        )
        _record_payment_event_failure(
            db,
            event_type=event_type,
            provider_event_key=provider_event_key,
            payment_key=payment_key,
            reference=reference,
            subscription_code=subscription_code,
            invoice_code=invoice_code,
            error_code=error_code,
        )
        _write_dlq(
            reference=reference,
            event_type=event_type,
            payload={
                'reference': reference,
                'subscription_code': subscription_code,
                'invoice_code': invoice_code,
                'customer_code': customer_code,
            },
            error_message=error_code,
            db=db,
        )
        if isinstance(exc, PaymentProcessingError):
            logger.warning(
                '[WEBHOOK] event=%s reference=%s subscription_code=%s '
                'customer_code=%s result=failed error_code=%s',
                event_type,
                reference,
                subscription_code,
                customer_code,
                error_code,
            )
        else:
            logger.exception(
                '[WEBHOOK] event=%s reference=%s subscription_code=%s '
                'result=failed error_code=%s',
                event_type,
                reference,
                subscription_code,
                error_code,
            )
        raise HTTPException(
            status_code=500,
            detail='Webhook processing failed.',
        ) from exc

    _emit_payment_notification(
        db,
        result=result,
        provider_event_key=provider_event_key,
    )

    logger.info(
        '[WEBHOOK] event=%s reference=%s subscription_code=%s '
        'customer_code=%s result=%s',
        event_type,
        reference,
        subscription_code,
        customer_code,
        result.get('action'),
    )
    return {'status': 'success', **result}


def _process_manual_verified_transaction(
    *,
    transaction_type: str,
    ref_appointment_id: str | None,
    ref_user_id: str | None,
    reference: str,
    tx_data: dict,
    db: Session,
    background_tasks: BackgroundTasks,
    current_user: User,
) -> dict:
    details = _subscription_event_details(tx_data)
    _validate_paystack_environment(details)
    environment = details.get('environment')
    provider_event_key = (
        f'{environment}:manual.verify:{reference}'
    )[:255]
    payment_key = _payment_identity_key(
        'manual.verify',
        tx_data,
        transaction_type,
    )
    event, duplicate = _claim_payment_event(
        db,
        event_type='manual.verify',
        provider_event_key=provider_event_key,
        payment_key=payment_key,
        reference=reference,
        subscription_code=details.get('subscription_code'),
        invoice_code=None,
    )
    if duplicate:
        db.rollback()
        return {
            'verified': True,
            'paystack_status': 'success',
            'action': 'payment_already_processed',
        }

    try:
        if transaction_type in CONSULTATION_TRANSACTION_TYPES:
            _validate_successful_consultation_charge(tx_data)
            _validate_consultation_payment(
                transaction_type=transaction_type,
                ref_appointment_id=ref_appointment_id,
                ref_user_id=ref_user_id,
                reference=reference,
                amount_kobo=paystack_requested_amount_kobo(tx_data),
                db=db,
                current_user=current_user,
            )
        result = _apply_db_update(
            transaction_type=transaction_type,
            ref_appointment_id=ref_appointment_id,
            ref_user_id=ref_user_id,
            reference=reference,
            db=db,
            background_tasks=background_tasks,
            paystack_data=tx_data,
        )
        _mark_payment_event_processed(
            event,
            user_id=(
                result.get('user_id')
                or (
                    int(ref_user_id)
                    if ref_user_id and ref_user_id.isdigit()
                    else None
                )
            ),
            action=str(result.get('action') or 'processed'),
        )
        db.commit()
    except Exception:
        db.rollback()
        raise
    _emit_payment_notification(
        db,
        result=result,
        provider_event_key=provider_event_key,
    )
    return {
        'verified': True,
        'paystack_status': 'success',
        **result,
    }


def _handle_refund_status(
    data: dict,
    db: Session,
    *,
    status_value: str,
) -> dict:
    """Apply a Paystack refund webhook to its consultation appointment."""
    transaction = data.get("transaction")
    transaction_reference = str(
        data.get("transaction_reference")
        or (
            transaction.get("reference")
            if isinstance(transaction, dict)
            else ""
        )
        or ""
    )
    if not transaction_reference:
        raise ValueError("Refund webhook has no transaction reference.")

    appointment = (
        db.query(Appointment)
        .filter(Appointment.paystack_reference == transaction_reference)
        .with_for_update()
        .first()
    )
    if appointment is None:
        raise ValueError("Refund appointment was not found.")
    if appointment.refund_status is None:
        raise ValueError("Appointment has no approved refund workflow.")

    normalized_status = status_value.replace("-", "_")
    appointment.refund_status = normalized_status
    appointment.refund_reference = str(
        data.get("refund_reference")
        or appointment.refund_reference
        or ""
    ) or None
    appointment.refund_id = str(
        data.get("id") or appointment.refund_id or ""
    ) or None
    if data.get("amount") is not None:
        appointment.refund_amount = int(data["amount"]) / 100

    if normalized_status == "processed":
        appointment.refund_processed_at = datetime.utcnow()
        appointment.refund_last_error = None
        appointment.payment_status = "refunded"
    elif normalized_status == "failed":
        appointment.refund_last_error = str(
            data.get("reason") or "Paystack refund failed."
        )[:1000]
    elif normalized_status == "needs_attention":
        appointment.refund_last_error = (
            "Paystack requires customer bank details to complete this refund."
        )
    else:
        appointment.refund_last_error = None

    db.commit()
    return {
        "action": f"consultation_refund_{normalized_status}",
        "appointment_id": appointment.id,
    }


@router.post("/webhook", status_code=200)
async def paystack_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    return await _process_paystack_webhook(
        request,
        background_tasks,
        db,
    )

# â”€â”€â”€ Manual Verification Endpoint â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€

@router.get("/verify/{reference}")
@limiter.limit("30/hour")
@limiter.limit("5/minute")
async def verify_transaction(
    reference: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    current_user: User = Depends(deps.get_current_user),
):
    """
    GET /api/v1/payments/verify/{reference}

    Called by the Flutter app when it suspects a successful payment was
    not reflected in the UI (e.g. the app was backgrounded before the
    webhook fired).

    Flow:
      1. Queries Paystack's /transaction/verify/{reference} endpoint.
      2. If Paystack reports status == "success", runs the exact same
         reference-parsing + DB-update logic as the webhook.
      3. Returns the final status so the app can refresh its UI.
    """

    if not PAYSTACK_SECRET_KEY:
        raise HTTPException(
            status_code=503,
            detail="Payment verification is unavailable â€” secret key not configured.",
        )


    (
        transaction_type,
        ref_appointment_id,
        ref_user_id,
    ) = _validate_reference_owner_before_paystack(
        reference=reference,
        db=db,
        current_user=current_user,
    )

    # â”€â”€ 1. Query Paystack â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(
                f"{PAYSTACK_VERIFY_URL}/{reference}",
                headers={"Authorization": f"Bearer {PAYSTACK_SECRET_KEY}"},
            )
        try:
            paystack_data: dict = resp.json()
        except ValueError:
            paystack_data = {}
    except httpx.RequestError as exc:
        logger.error(
            "[VERIFY] network_error reference=%s error_type=%s",
            reference,
            type(exc).__name__,
        )
        raise HTTPException(
            status_code=502,
            detail="Could not reach Paystack verification endpoint.",
        )

    # â”€â”€ 2. Inspect Paystack's verdict â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    if not paystack_data.get("status"):
        logger.warning(
            "[VERIFY] provider_rejected reference=%s http_status=%s",
            reference,
            resp.status_code,
        )
        raise HTTPException(
            status_code=402,
            detail="The transaction could not be verified.",
        )

    tx_data: dict = paystack_data.get("data") or {}
    paystack_status: str = tx_data.get("status", "")

    if paystack_status == 'success':
        return _process_manual_verified_transaction(
            transaction_type=transaction_type,
            ref_appointment_id=ref_appointment_id,
            ref_user_id=ref_user_id,
            reference=reference,
            tx_data=tx_data,
            db=db,
            background_tasks=background_tasks,
            current_user=current_user,
        )

    if paystack_status != "success":
        logger.info(
            "[VERIFY] Transaction reference='%s' is NOT successful (status='%s').",
            reference,
            paystack_status,
        )
        return {
            "verified": False,
            "paystack_status": paystack_status,
            "detail": "Transaction is not yet successful.",
        }
