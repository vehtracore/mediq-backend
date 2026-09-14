"""
Paystack Service
================
Async wrapper around the Paystack REST API for server-initiated operations.

Currently supports:
  • create_doctor_subaccount() — creates a split-payment subaccount on
    Paystack for a newly onboarded doctor so commission splits happen
    automatically at the payment gateway level.

Authentication
--------------
All requests use Bearer token authentication with PAYSTACK_SECRET_KEY pulled
from the environment. The key is never hard-coded.

Error handling
--------------
Provider responses are translated into stable MDQ-owned API errors. Raw
provider messages remain outside the client contract.
"""

import logging
import os
from typing import Optional
from app.services.consultation_pricing import (
    PAYSTACK_PLATFORM_PERCENTAGE_CHARGE,
)

import httpx

from app.core.api_errors import ApiError

logger = logging.getLogger("uvicorn.error")

# ── Paystack API base URL ──────────────────────────────────────────────────────
PAYSTACK_BASE_URL = "https://api.paystack.co"


def _masked_account_number(account_number: str) -> str:
    suffix = account_number[-4:] if account_number else ''
    return f'******{suffix}' if suffix else '(missing)'


class PaystackService:
    """
    Async client for server-initiated Paystack API calls.

    Instantiated once at module level (``paystack_service``). Import that
    singleton instead of constructing new instances.
    """

    def __init__(self) -> None:
        self._secret_key: str = os.environ.get("PAYSTACK_SECRET_KEY", "")
        if not self._secret_key:
            logger.warning(
                "[PAYSTACK] ⚠️  PAYSTACK_SECRET_KEY is not set. "
                "API calls will fail until the key is configured."
            )

    # ── Internal helpers ───────────────────────────────────────────────────────

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._secret_key}",
            "Content-Type": "application/json",
        }

    # ── Public API methods ────────────────────────────────────────────────────

    async def create_doctor_subaccount(
        self,
        business_name: str,
        bank_code: str,
        account_number: str,
        percentage_charge: float = PAYSTACK_PLATFORM_PERCENTAGE_CHARGE,
    ) -> str:
        """
        Create a Paystack split-payment subaccount for a doctor.

        Paystack will automatically route ``percentage_charge`` percent of
        every transaction to the platform and the remainder to the doctor's
        bank account.

        Args:
            business_name:     Display name for the subaccount (typically the
                               doctor's full name or practice name).
            bank_code:         Paystack bank code, e.g. "058" for GTBank.
                               Full list: GET https://api.paystack.co/bank
            account_number:    10-digit NUBAN account number.
            percentage_charge: Platform's configured commission percentage.
                               Paystack stores this as the *platform's* share.

        Returns:
            The ``subaccount_code`` string from Paystack (e.g. "SUB_abc123").

        Raises:
            ApiError(400): If the provider rejects the payout details.
            ApiError(503): If a network-level failure prevents the call.
        """
        endpoint = f"{PAYSTACK_BASE_URL}/subaccount"
        body = {
            "business_name": business_name,
            "bank_code": bank_code,
            "account_number": account_number,
            "percentage_charge": percentage_charge,
        }

        logger.info(
            "[PAYSTACK] Creating subaccount | business='%s' | bank='%s' | account='%s'",
            '(redacted)',
            bank_code,
            _masked_account_number(account_number),
        )

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(endpoint, json=body, headers=self._headers)
        except httpx.RequestError as exc:
            # Network-level failure (DNS, timeout, connection refused)
            logger.error(
                "[PAYSTACK] subaccount network failure_category=%s",
                type(exc).__name__,
                exc_info=True,
            )
            raise ApiError(
                status_code=503,
                code="payment_service_unavailable",
                message="Payout setup is temporarily unavailable. Please try again shortly.",
            ) from exc

        # ── Parse and validate Paystack's response ─────────────────────────────
        try:
            resp_json: dict = response.json()
        except Exception:
            resp_json = {}

        paystack_status: bool = resp_json.get("status", False)
        if not response.is_success or not paystack_status:
            logger.error(
                "[PAYSTACK] subaccount rejected http_status=%s",
                response.status_code,
            )
            raise ApiError(
                status_code=400,
                code="invalid_payout_details",
                message="We couldn't verify these payout details. Check them and try again.",
            )

        subaccount_code: Optional[str] = (
            resp_json.get("data", {}).get("subaccount_code")
        )
        if not subaccount_code:
            logger.error(
                "[PAYSTACK] response omitted subaccount_code | HTTP %s",
                response.status_code,
            )
            raise ApiError(
                status_code=502,
                code="payment_service_unavailable",
                message="Payout setup is temporarily unavailable. Please try again shortly.",
            )

        logger.info(
            "[PAYSTACK] ✅ Subaccount created — code=%s | business='%s'",
            subaccount_code,
            '(redacted)',
        )
        return subaccount_code

    async def resolve_account(self, bank_code: str, account_number: str) -> str:
        """
        Resolve a Nigerian bank account number to the registered account name.

        Uses Paystack's GET /bank/resolve endpoint (requires the secret key).
        This is the correct way to verify that an account number belongs to
        the person trying to link it before creating a subaccount.

        Args:
            bank_code:      Paystack bank code, e.g. "058" for GTBank.
            account_number: 10-digit NUBAN account number.

        Returns:
            The ``account_name`` string exactly as Paystack returns it
            (e.g. "ADEBAYO JOHN OLAWALE").

        Raises:
            ApiError(400): Account not found or bank/number invalid.
            ApiError(503): Network-level failure.
        """
        endpoint = f"{PAYSTACK_BASE_URL}/bank/resolve"
        params = {"account_number": account_number, "bank_code": bank_code}

        logger.info(
            "[PAYSTACK] Resolving account | bank='%s' | account='%s'",
            bank_code,
            _masked_account_number(account_number),
        )

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    endpoint, params=params, headers=self._headers
                )
        except httpx.RequestError as exc:
            logger.error(
                "[PAYSTACK] account-resolution network failure_category=%s",
                type(exc).__name__,
                exc_info=True,
            )
            raise ApiError(
                status_code=503,
                code="payment_service_unavailable",
                message="Account verification is temporarily unavailable. Please try again shortly.",
            ) from exc

        try:
            resp_json: dict = response.json()
        except Exception:
            resp_json = {}

        paystack_status: bool = resp_json.get("status", False)
        if not response.is_success or not paystack_status:
            logger.warning(
                "[PAYSTACK] account-resolution rejected http_status=%s",
                response.status_code,
            )
            raise ApiError(
                status_code=400,
                code="invalid_payout_details",
                message="We couldn't verify that account. Check the bank and account number.",
            )

        account_name: Optional[str] = resp_json.get("data", {}).get("account_name")
        if not account_name:
            raise ApiError(
                status_code=502,
                code="payment_service_unavailable",
                message="Account verification is temporarily unavailable. Please try again shortly.",
            )

        logger.info(
            "[PAYSTACK] ✅ Account resolved — bank='%s' | account='%s' | name='%s'",
            bank_code,
            _masked_account_number(account_number),
            '(redacted)',
        )
        return account_name

    async def create_transfer_recipient(
        self,
        *,
        doctor_id: int,
        name: str,
        bank_code: str,
        account_number: str,
    ) -> str:
        """Create or retrieve a Nigerian NUBAN transfer recipient."""
        endpoint = f"{PAYSTACK_BASE_URL}/transferrecipient"
        body = {
            "type": "nuban",
            "name": name,
            "bank_code": bank_code,
            "account_number": account_number,
            "currency": "NGN",
            "metadata": {"doctor_id": doctor_id},
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    endpoint,
                    json=body,
                    headers=self._headers,
                )
        except httpx.RequestError as exc:
            logger.error(
                "[PAYSTACK] transfer-recipient network failure_category=%s",
                type(exc).__name__,
                exc_info=True,
            )
            raise ApiError(
                status_code=503,
                code="payment_service_unavailable",
                message="Payout service is temporarily unavailable. Please try again shortly.",
            ) from exc

        payload = response.json()
        if not response.is_success or not payload.get("status"):
            raise ApiError(
                status_code=400,
                code="invalid_payout_details",
                message="We couldn't verify these payout details. Check them and try again.",
            )
        recipient_code = (payload.get("data") or {}).get("recipient_code")
        if not recipient_code:
            raise ApiError(
                status_code=502,
                code="payment_service_unavailable",
                message="Payout service is temporarily unavailable. Please try again shortly.",
            )
        return str(recipient_code)

    async def initiate_transfer(
        self,
        *,
        amount_kobo: int,
        recipient_code: str,
        reference: str,
        reason: str,
    ) -> dict:
        """Initiate a transfer from the Paystack balance."""
        endpoint = f"{PAYSTACK_BASE_URL}/transfer"
        body = {
            "source": "balance",
            "amount": amount_kobo,
            "recipient": recipient_code,
            "reference": reference,
            "reason": reason,
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    endpoint,
                    json=body,
                    headers=self._headers,
                )
        except httpx.RequestError as exc:
            logger.error(
                "[PAYSTACK] transfer network failure_category=%s",
                type(exc).__name__,
                exc_info=True,
            )
            raise ApiError(
                status_code=503,
                code="payment_service_unavailable",
                message="Payout service is temporarily unavailable. Please try again shortly.",
            ) from exc

        payload = response.json()
        if not response.is_success or not payload.get("status"):
            raise ApiError(
                status_code=400,
                code="payout_request_rejected",
                message="The payout could not be submitted. Check its current status before trying again.",
            )
        return payload.get("data") or {}

    async def create_refund(
        self,
        *,
        transaction_reference: str,
        amount_kobo: int,
        customer_note: str,
        merchant_note: str,
    ) -> dict:
        """Initiate a Paystack refund for a verified consultation payment."""
        endpoint = f"{PAYSTACK_BASE_URL}/refund"
        body = {
            "transaction": transaction_reference,
            "amount": amount_kobo,
            "currency": "NGN",
            "customer_note": customer_note,
            "merchant_note": merchant_note,
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    endpoint,
                    json=body,
                    headers=self._headers,
                )
        except httpx.RequestError as exc:
            logger.error(
                "[PAYSTACK] refund network failure_category=%s",
                type(exc).__name__,
                exc_info=True,
            )
            raise ApiError(
                status_code=503,
                code="payment_service_unavailable",
                message="Refund service is temporarily unavailable. Please try again shortly.",
            ) from exc

        try:
            payload = response.json()
        except Exception:
            payload = {}
        if not response.is_success or not payload.get("status"):
            raise ApiError(
                status_code=400,
                code="refund_request_rejected",
                message="The refund could not be submitted. Check its current status before trying again.",
            )
        return payload.get("data") or {}

    async def disable_subscription(
        self,
        subscription_code: str,
        email_token: str,
    ) -> dict:
        """
        Disable (cancel) a Paystack recurring subscription.

        Paystack requires both the ``subscription_code`` and the
        ``email_token`` as a two-factor guard before it will deactivate a
        subscription. Both values are captured from the
        ``subscription.create`` webhook event and stored on the User row.

        Args:
            subscription_code: The Paystack subscription identifier,
                               e.g. ``"SUB_vsyqdmlzble3uii"``.
            email_token:       The short-lived token sent alongside the
                               subscription code, e.g. ``"d7gofp6yppn3qz7"``.

        Returns:
            The parsed Paystack response body as a dict.

        Raises:
            ApiError(400): The provider rejected the cancellation request.
            ApiError(503): Network-level failure reaching the provider.
        """
        endpoint = f"{PAYSTACK_BASE_URL}/subscription/disable"
        body = {
            "code": subscription_code,
            "token": email_token,
        }

        logger.info(
            "[PAYSTACK] Disabling subscription | code='%s'",
            subscription_code,
        )

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    endpoint, json=body, headers=self._headers
                )
        except httpx.RequestError as exc:
            logger.error(
                "[PAYSTACK] subscription-disable network failure_category=%s",
                type(exc).__name__,
                exc_info=True,
            )
            raise ApiError(
                status_code=503,
                code="payment_service_unavailable",
                message="Subscription changes are temporarily unavailable. Please try again shortly.",
            ) from exc

        try:
            resp_json: dict = response.json()
        except Exception:
            resp_json = {}

        paystack_status: bool = resp_json.get("status", False)
        if not response.is_success or not paystack_status:
            logger.error(
                "[PAYSTACK] subscription-disable rejected http_status=%s",
                response.status_code,
            )
            raise ApiError(
                status_code=400,
                code="subscription_change_rejected",
                message="The subscription could not be cancelled. Check its current status before trying again.",
            )

        logger.info(
            "[PAYSTACK] ✅ Subscription disabled — code='%s'",
            subscription_code,
        )
        return resp_json

    async def enable_subscription(
        self,
        subscription_code: str,
        email_token: str,
    ) -> dict:
        """
        Re-enable a previously disabled Paystack recurring subscription.

        Paystack uses the same subscription ``code`` and email ``token`` pair
        for subscription enable/disable operations.
        """
        endpoint = f"{PAYSTACK_BASE_URL}/subscription/enable"
        body = {
            "code": subscription_code,
            "token": email_token,
        }

        logger.info(
            "[PAYSTACK] Enabling subscription | code='%s'",
            subscription_code,
        )

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(
                    endpoint, json=body, headers=self._headers
                )
        except httpx.RequestError as exc:
            logger.error(
                "[PAYSTACK] subscription-enable network failure_category=%s",
                type(exc).__name__,
                exc_info=True,
            )
            raise ApiError(
                status_code=503,
                code="payment_service_unavailable",
                message="Subscription changes are temporarily unavailable. Please try again shortly.",
            ) from exc

        try:
            resp_json: dict = response.json()
        except Exception:
            resp_json = {}

        paystack_status: bool = resp_json.get("status", False)
        if not response.is_success or not paystack_status:
            logger.error(
                "[PAYSTACK] subscription-enable rejected http_status=%s",
                response.status_code,
            )
            raise ApiError(
                status_code=400,
                code="subscription_change_rejected",
                message="The subscription could not be restored. Check its current status before trying again.",
            )

        logger.info(
            "[PAYSTACK] ✅ Subscription enabled — code='%s'",
            subscription_code,
        )
        return resp_json


# ── Module-level singleton ─────────────────────────────────────────────────────
# Import this instance wherever you need Paystack interactions:
#   from app.services.paystack_service import paystack_service
paystack_service = PaystackService()
