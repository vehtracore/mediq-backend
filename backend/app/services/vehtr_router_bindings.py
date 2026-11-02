"""Optional registration of MDQ+ Paystack ownership identities with Vehtr's router.

Paystack webhooks are still authenticated and reconciled by the existing MDQ+
receiver. This adapter only sends opaque, previously persisted subscription and
invoice identifiers to a shared, product-neutral routing registry.

The adapter is disabled unless every router environment setting is present;
registration failures never turn a verified payment into a failure. A separate
backfill command can recover registrations after transient outages.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
from dataclasses import dataclass
from urllib.parse import urlsplit

import httpx

logger = logging.getLogger(__name__)
_ID = re.compile(r"^[a-z][a-z0-9-]{1,62}$")
_KEY = re.compile(r"^[\x21-\x7e]{1,180}$")


@dataclass(frozen=True)
class RouterSettings:
    base_url: str
    product_id: str
    token: str


def router_settings(env: dict[str, str] | None = None) -> RouterSettings | None:
    """Fail closed without an approved HTTPS router URL and product token."""
    values = env if env is not None else os.environ
    raw = values.get("VEHTR_PAYSTACK_ROUTER_URL", "").strip()
    product_id = values.get("VEHTR_PAYSTACK_ROUTER_PRODUCT_ID", "").strip()
    token = values.get("VEHTR_PAYSTACK_ROUTER_PRODUCT_TOKEN", "")
    try:
        url = urlsplit(raw)
    except ValueError:
        return None
    if (
        url.scheme != "https" or not url.hostname or not url.netloc
        or url.username or url.password or url.port
        or url.path not in ("", "/") or url.query or url.fragment
        or url.hostname.lower() in ("localhost", "127.0.0.1")
        or url.hostname.endswith((".local", ".internal"))
        or "." not in url.hostname or not _ID.fullmatch(product_id)
        or len(token) < 32 or any(ch.isspace() for ch in token)
    ):
        return None
    return RouterSettings(raw.rstrip("/"), product_id, token)


def stored_payment_bindings(user: object, mode: str) -> list[tuple[str, str]]:
    """Only locally stored subscription identities in their original environment.

    Never register customer codes: the same Paystack customer can pay for
    different Vehtr products. Customer-only routing is not sufficiently precise.
    """
    if mode not in ("test", "live") or getattr(user, "paystack_environment", None) != mode:
        return []
    bindings = []
    for kind, attr, prefix in (
        ("subscription", "paystack_subscription_code", "SUB_"),
        ("invoice", "paystack_latest_invoice_code", "INV_"),
    ):
        code = getattr(user, attr, None)
        if isinstance(code, str) and code.startswith(prefix) and _KEY.fullmatch(code):
            bindings.append((kind, code))
    return bindings


async def publish_router_bindings(
    mode: str,
    bindings: list[tuple[str, str]],
    *,
    client: httpx.AsyncClient | None = None,
    settings: RouterSettings | None = None,
) -> tuple[int, int]:
    """Upsert verified owner identifiers; returns registered/failed counts.

    Non-success, timeout and 409 conflicts never leak identifiers or credentials
    into logs and never mutate the local entitlement. The router's registered
    product token authenticates this request (not the Paystack account key).
    """
    config = settings or router_settings()
    if not config or mode not in ("test", "live"):
        return 0, 0
    valid = list(dict.fromkeys(
        (kind, code) for kind, code in bindings
        if kind in ("subscription", "invoice")
        and isinstance(code, str) and _KEY.fullmatch(code)
        and code.startswith("SUB_" if kind == "subscription" else "INV_")
    ))
    if not valid:
        return 0, 0
    own = client is None
    http = client or httpx.AsyncClient(timeout=6.0, follow_redirects=False)
    registered = failed = 0
    try:
        for kind, code in valid:
            for attempt in range(3):
                try:
                    result = await http.post(
                        config.base_url + "/v1/bindings",
                        headers={
                            "Authorization": "Bearer " + config.token,
                            "Content-Type": "application/json",
                        },
                        json={
                            "product_id": config.product_id,
                            "mode": mode,
                            "kind": kind,
                            "value": code,
                        },
                    )
                    if result.status_code == 200:
                        registered += 1
                        break
                    # A conflicting owner or invalid credentials must not be retried.
                    if result.status_code in (400, 401, 403, 409, 422):
                        failed += 1
                        logger.warning(
                            "vehtr_router.binding_rejected kind=%s mode=%s status=%d",
                            kind, mode, result.status_code,
                        )
                        break
                except httpx.RequestError:
                    pass
                if attempt == 2:
                    failed += 1
                    logger.warning("vehtr_router.binding_unavailable kind=%s mode=%s", kind, mode)
                else:
                    await asyncio.sleep(0.2 * (2 ** attempt))
    finally:
        if own:
            await http.aclose()
    return registered, failed


def schedule_router_bindings(
    *, db: object, background_tasks: object, user_id: int | None,
    mode: str | None,
) -> None:
    """After MDQ+'s own DB commit, register actual persisted subscription codes.

    Missing router configuration is a complete no-op. BackgroundTasks delivers
    after the HTTP response, so router unavailability cannot impact checkout.
    """
    if not router_settings() or mode not in ("test", "live"):
        return
    if type(user_id) is not int or user_id <= 0:
        return
    # Import here so isolated adapter tests never connect to MDQ+'s database.
    from app.models.user import User
    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        return
    bindings = stored_payment_bindings(user, mode)
    if bindings:
        background_tasks.add_task(publish_router_bindings, mode, bindings)
