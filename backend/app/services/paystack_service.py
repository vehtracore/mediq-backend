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
If Paystack returns a non-2xx response or a known error body, the service
raises HTTPException(400) carrying Paystack's own human-readable message so
the calling endpoint can surface it directly to the client.
"""

import logging
import os
from typing import Optional

import httpx
from fastapi import HTTPException

logger = logging.getLogger("uvicorn.error")

# ── Paystack API base URL ──────────────────────────────────────────────────────
PAYSTACK_BASE_URL = "https://api.paystack.co"


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
        percentage_charge: float = 30.0,
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
            percentage_charge: Platform's commission cut (default 30 %).
                               Paystack stores this as the *platform's* share.

        Returns:
            The ``subaccount_code`` string from Paystack (e.g. "SUB_abc123").

        Raises:
            HTTPException(400): If Paystack rejects the request. The detail
                                field contains Paystack's own error message.
            HTTPException(503): If a network-level failure prevents the call.
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
            business_name,
            bank_code,
            account_number,
        )

        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(endpoint, json=body, headers=self._headers)
        except httpx.RequestError as exc:
            # Network-level failure (DNS, timeout, connection refused)
            logger.error(
                "[PAYSTACK] ❌ Network error creating subaccount: %s: %s",
                type(exc).__name__,
                exc,
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    "Could not reach Paystack. Please check your connection "
                    "and try again."
                ),
            ) from exc

        # ── Parse and validate Paystack's response ─────────────────────────────
        try:
            resp_json: dict = response.json()
        except Exception:
            resp_json = {}

        paystack_status: bool = resp_json.get("status", False)
        paystack_message: str = resp_json.get("message", "Unknown error from Paystack")

        if not response.is_success or not paystack_status:
            logger.error(
                "[PAYSTACK] ❌ Subaccount creation failed | HTTP %s | message='%s'",
                response.status_code,
                paystack_message,
            )
            # Surface Paystack's own message — it's always user-readable
            # (e.g. "Account number is invalid", "Bank code is invalid")
            raise HTTPException(status_code=400, detail=paystack_message)

        subaccount_code: Optional[str] = (
            resp_json.get("data", {}).get("subaccount_code")
        )
        if not subaccount_code:
            logger.error(
                "[PAYSTACK] ❌ Response OK but 'subaccount_code' missing: %s",
                resp_json,
            )
            raise HTTPException(
                status_code=400,
                detail="Paystack did not return a subaccount code. Contact support.",
            )

        logger.info(
            "[PAYSTACK] ✅ Subaccount created — code=%s | business='%s'",
            subaccount_code,
            business_name,
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
            HTTPException(400): Account not found or bank/number invalid.
            HTTPException(503): Network-level failure.
        """
        endpoint = f"{PAYSTACK_BASE_URL}/bank/resolve"
        params = {"account_number": account_number, "bank_code": bank_code}

        logger.info(
            "[PAYSTACK] Resolving account | bank='%s' | account='%s'",
            bank_code,
            account_number,
        )

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(
                    endpoint, params=params, headers=self._headers
                )
        except httpx.RequestError as exc:
            logger.error(
                "[PAYSTACK] ❌ Network error resolving account: %s: %s",
                type(exc).__name__,
                exc,
            )
            raise HTTPException(
                status_code=503,
                detail="Could not reach Paystack to verify your account. Please try again.",
            ) from exc

        try:
            resp_json: dict = response.json()
        except Exception:
            resp_json = {}

        paystack_status: bool = resp_json.get("status", False)
        paystack_message: str = resp_json.get("message", "Unknown error from Paystack")

        if not response.is_success or not paystack_status:
            logger.warning(
                "[PAYSTACK] ❌ Account resolution failed | HTTP %s | message='%s'",
                response.status_code,
                paystack_message,
            )
            raise HTTPException(
                status_code=400,
                detail=paystack_message,  # e.g. "Could not resolve account name"
            )

        account_name: Optional[str] = resp_json.get("data", {}).get("account_name")
        if not account_name:
            raise HTTPException(
                status_code=400,
                detail="Paystack returned no account name. Check your account details.",
            )

        logger.info(
            "[PAYSTACK] ✅ Account resolved — bank='%s' | account='%s' | name='%s'",
            bank_code,
            account_number,
            account_name,
        )
        return account_name

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
            HTTPException(400): Paystack rejected the cancellation request.
            HTTPException(503): Network-level failure reaching Paystack.
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
                "[PAYSTACK] ❌ Network error disabling subscription: %s: %s",
                type(exc).__name__,
                exc,
            )
            raise HTTPException(
                status_code=503,
                detail=(
                    "Could not reach Paystack to cancel your subscription. "
                    "Please try again later."
                ),
            ) from exc

        try:
            resp_json: dict = response.json()
        except Exception:
            resp_json = {}

        paystack_status: bool = resp_json.get("status", False)
        paystack_message: str = resp_json.get("message", "Unknown error from Paystack")

        if not response.is_success or not paystack_status:
            logger.error(
                "[PAYSTACK] ❌ Subscription cancellation failed | HTTP %s | message='%s' | code='%s'",
                response.status_code,
                paystack_message,
                subscription_code,
            )
            raise HTTPException(status_code=400, detail=paystack_message)

        logger.info(
            "[PAYSTACK] ✅ Subscription disabled — code='%s'",
            subscription_code,
        )
        return resp_json


# ── Module-level singleton ─────────────────────────────────────────────────────
# Import this instance wherever you need Paystack interactions:
#   from app.services.paystack_service import paystack_service
paystack_service = PaystackService()
