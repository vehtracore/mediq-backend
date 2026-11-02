"""Backfill MDQ+ subscription identities to the Vehtr router.

Default is dry-run. No payment, entitlement, refund, or user data is modified.
Run from backend/ with its existing database environment.
"""
import argparse
import asyncio

from app.services.vehtr_router_bindings import (
    publish_router_bindings, router_settings, stored_payment_bindings,
)


async def run(mode: str, apply: bool) -> int:
    from app.core.database import SessionLocal
    from app.models.user import User

    if apply and not router_settings():
        print("Router is not configured; no registrations performed.")
        return 2
    db = SessionLocal()
    try:
        values = set()
        for owner in db.query(User).filter(User.paystack_environment == mode).yield_per(200):
            values.update(stored_payment_bindings(owner, mode))
    finally:
        db.close()
    print("Mode=%s, subscriptions=%s, invoices=%s, apply=%s" % (
        mode, sum(k == "subscription" for k, _ in values),
        sum(k == "invoice" for k, _ in values), apply,
    ))
    if not apply:
        return 0
    success, failed = await publish_router_bindings(mode, sorted(values))
    print("Registered=%s, failed=%s" % (success, failed))
    return int(failed > 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["test", "live"], default="test")
    parser.add_argument("--apply", action="store_true")
    settings = parser.parse_args()
    return asyncio.run(run(settings.mode, settings.apply))


if __name__ == "__main__":
    raise SystemExit(main())
