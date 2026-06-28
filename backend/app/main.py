import logging
import os
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration
from sqlalchemy.exc import TimeoutError as SQLAlchemyTimeoutError

logger = logging.getLogger(__name__)


def _sample_rate_from_env(name: str, default: float) -> float:
    """Read a Sentry sample rate safely and keep it within the 0..1 range."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = float(raw_value)
    except ValueError:
        logger.warning(
            "[SENTRY] Invalid %s=%r; using default %.2f",
            name,
            raw_value,
            default,
        )
        return default

    if not 0.0 <= value <= 1.0:
        logger.warning(
            "[SENTRY] %s must be between 0 and 1; using default %.2f",
            name,
            default,
        )
        return default

    return value


# ---------------------------------------------------------------------------
# 🔭 Sentry — crash reporting & performance tracing
# Initialised before anything else so startup errors are also captured.
# Set SENTRY_DSN in your environment (Render/Railway secret). When the DSN is
# empty (local dev) Sentry's SDK is a silent no-op — no data is sent.
#
# LoggingIntegration ensures every logger.error() across the entire app is
# automatically forwarded to Sentry as an issue, giving full observability
# over third-party API failures (Termii, Paystack, Cloudinary, Gemini, etc.).
# ---------------------------------------------------------------------------
sentry_sdk.init(
    dsn=os.getenv("SENTRY_DSN", ""),
    traces_sample_rate=_sample_rate_from_env(
        "SENTRY_TRACES_SAMPLE_RATE",
        0.05,
    ),
    profiles_sample_rate=_sample_rate_from_env(
        "SENTRY_PROFILES_SAMPLE_RATE",
        0.0,
    ),
    integrations=[
        LoggingIntegration(
            level=logging.INFO,          # Breadcrumbs from INFO and above
            event_level=logging.ERROR,   # Sentry issues from ERROR and above
        ),
    ],
)

from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.core.limiter import limiter
from app.core.database import engine, Base, SessionLocal

# ✅ KEEP "app." prefix because your main.py is inside the app folder
from app.api.v1 import auth, chat, ai_consent, doctors, appointments, admin, content, subscription, reviews, media, video, chat_socket, upload, lab, vault, voice, notifications, ai_report

from app.api.v1 import emergency
from app.api.v1 import payments
from app.api.v1 import family
from app.api.v1 import support
from app.api.v1.auth import scrub_expired_accounts
from app.services.watchdog_service import sweep_pending_transactions
from app.core.scheduler import (
    complete_expired_consultations,
    cleanup_expired_slots,
    cleanup_old_notifications,
    mark_consultation_no_shows,
    process_approved_consultation_payouts,
    process_approved_consultation_refunds,
    sweep_stale_appointments,
)

Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# 🔧 Startup schema patch — safely adds any columns that create_all misses
#    (create_all only creates NEW tables; it never alters existing ones)
# ---------------------------------------------------------------------------
def _apply_schema_patches():
    """
    Idempotent DDL migrations. Each statement uses IF NOT EXISTS so running
    multiple times is always safe. Add new patches here instead of touching
    Alembic while the project is pre-migration-framework.
    """
    patches = [
        # NDPA 30-day legal hold column (added 2026-04-16)
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS deletion_requested_at TIMESTAMPTZ NULL;
        """,
        # Index for the daily scrubber query (created separately so the
        # patch block stays readable)
        """
        CREATE INDEX IF NOT EXISTS ix_users_deletion_requested_at
        ON users (deletion_requested_at);
        """,
        # Emergency Protocol columns (added 2026-04-22)
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS kin_phone VARCHAR NULL;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS emergency_sms_enabled BOOLEAN NOT NULL DEFAULT FALSE;
        """,
        # Emergency rate-limiting columns (added 2026-05-09)
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS last_emergency_trigger TIMESTAMPTZ NULL;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS emergency_sms_count INTEGER NOT NULL DEFAULT 0;
        """,
        # Doctor banking / subaccount columns (added 2026-04-22)
        """
        ALTER TABLE doctors
        ADD COLUMN IF NOT EXISTS bank_code VARCHAR NULL;
        """,
        """
        ALTER TABLE doctors
        ADD COLUMN IF NOT EXISTS account_number VARCHAR NULL;
        """,
        """
        ALTER TABLE doctors
        ADD COLUMN IF NOT EXISTS paystack_subaccount_code VARCHAR NULL;
        """,
        """
        ALTER TABLE doctors
        ADD COLUMN IF NOT EXISTS paystack_recipient_code VARCHAR NULL;
        """,
        # Doctor-set flat consultation pricing for specialist and VIP flows.
        """
        ALTER TABLE doctors
        ADD COLUMN IF NOT EXISTS consultation_fee DOUBLE PRECISION NULL;
        """,
        """
        ALTER TABLE doctors
        ADD COLUMN IF NOT EXISTS consultation_duration_minutes INTEGER NULL;
        """,
        """
        ALTER TABLE doctors
        DROP CONSTRAINT IF EXISTS ck_doctors_consultation_minimum_fee;
        """,
        """
        ALTER TABLE doctors
        DROP CONSTRAINT IF EXISTS ck_doctors_consultation_minimum_fee_30;
        """,
        """
        ALTER TABLE doctors
        DROP CONSTRAINT IF EXISTS ck_doctors_consultation_duration;
        """,
        """
        ALTER TABLE doctors
        DROP CONSTRAINT IF EXISTS ck_doctors_consultation_duration_30;
        """,
        """
        UPDATE doctors
        SET consultation_duration_minutes = 30;
        """,
        """
        UPDATE doctors
        SET consultation_fee = GREATEST(
            COALESCE(consultation_fee, hourly_rate, 0),
            4000
        );
        """,
        """
        UPDATE doctors
        SET hourly_rate = consultation_fee
        WHERE hourly_rate IS DISTINCT FROM consultation_fee;
        """,
        """
        ALTER TABLE doctors
        ALTER COLUMN consultation_fee SET DEFAULT 4000,
        ALTER COLUMN consultation_fee SET NOT NULL,
        ALTER COLUMN consultation_duration_minutes SET DEFAULT 30,
        ALTER COLUMN consultation_duration_minutes SET NOT NULL;
        """,
        """
        ALTER TABLE doctors
        ADD CONSTRAINT ck_doctors_consultation_duration
        CHECK (consultation_duration_minutes = 30);
        """,
        """
        ALTER TABLE doctors
        ADD CONSTRAINT ck_doctors_consultation_minimum_fee
        CHECK (consultation_fee >= 4000);
        """,
        # Dead Letter Queue — failed webhook events (added 2026-05-01)
        """
        CREATE TABLE IF NOT EXISTS failed_webhooks (
            id            SERIAL PRIMARY KEY,
            reference     TEXT        NOT NULL,
            event_type    TEXT        NOT NULL,
            payload       TEXT        NOT NULL,
            error_message TEXT        NOT NULL,
            created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_failed_webhooks_reference
        ON failed_webhooks (reference);
        """,
        # Paystack reference on appointments for watchdog sweeps (added 2026-05-02)
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS paystack_reference VARCHAR NULL;
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_appointments_paystack_reference
        ON appointments (paystack_reference)
        WHERE paystack_reference IS NOT NULL;
        """,
        # Durable appointment workflow type (added 2026-06-18).
        # This remains nullable during the legacy-classification phase. New
        # appointment writes always set it explicitly; only high-confidence
        # historical rows are backfilled here.
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS appointment_type VARCHAR(32) NULL;
        """,
        """
        UPDATE appointments
        SET appointment_type = 'specialist_scheduled'
        WHERE appointment_type IS NULL
          AND slot_id IS NOT NULL;
        """,
        """
        UPDATE appointments
        SET appointment_type = 'general_queue'
        WHERE appointment_type IS NULL
          AND paystack_reference ILIKE '%gp_consult%';
        """,
        """
        UPDATE appointments
        SET appointment_type = 'vip_request'
        WHERE appointment_type IS NULL
          AND paystack_reference ILIKE '%vip_request%';
        """,
        """
        UPDATE appointments
        SET appointment_type = 'specialist_scheduled'
        WHERE appointment_type IS NULL
          AND paystack_reference ILIKE '%specialist%';
        """,
        """
        UPDATE appointments
        SET appointment_type = 'general_queue'
        WHERE appointment_type IS NULL
          AND doctor_id IS NULL
          AND slot_id IS NULL;
        """,
        # Subscription auto-renew state (added 2026-06-16). Backfill only on
        # first column creation so cancelled users are not re-enabled on restart.
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM information_schema.columns
                WHERE table_name = 'users'
                  AND column_name = 'auto_renew'
            ) THEN
                ALTER TABLE users
                ADD COLUMN auto_renew BOOLEAN NOT NULL DEFAULT FALSE;

                UPDATE users
                SET auto_renew = TRUE
                WHERE paystack_subscription_code IS NOT NULL
                  AND COALESCE(plan, 'free') IN ('premium', 'family');
            END IF;
        END $$;
        """,
        # ── AI quota tracking columns (added 2026-05-11) ─────────────────────
        # last_chat_date — used by /api/v1/chat/analyze for inline daily resets
        # Versioned, one-time AI consent (added 2026-06-19)
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS ai_consent_granted_at TIMESTAMPTZ NULL;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS ai_consent_version VARCHAR NULL;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS ai_consent_withdrawn_at TIMESTAMPTZ NULL;
        """,
        # AI Health Vault summary provenance and review state (added 2026-06-19)
        """
        ALTER TABLE ai_chat_summaries
        ADD COLUMN IF NOT EXISTS source VARCHAR NOT NULL DEFAULT 'ai_generated';
        """,
        """
        ALTER TABLE ai_chat_summaries
        ADD COLUMN IF NOT EXISTS doctor_review_status VARCHAR NOT NULL DEFAULT 'not_reviewed';
        """,
        """
        ALTER TABLE ai_chat_summaries
        ADD COLUMN IF NOT EXISTS reviewed_by_doctor_id INTEGER NULL;
        """,
        """
        ALTER TABLE ai_chat_summaries
        ADD COLUMN IF NOT EXISTS reviewed_at TIMESTAMPTZ NULL;
        """,
        """
        DO $$
        BEGIN
            IF NOT EXISTS (
                SELECT 1
                FROM pg_constraint
                WHERE conname = 'fk_ai_chat_summaries_reviewed_by_doctor'
            ) THEN
                ALTER TABLE ai_chat_summaries
                ADD CONSTRAINT fk_ai_chat_summaries_reviewed_by_doctor
                FOREIGN KEY (reviewed_by_doctor_id)
                REFERENCES doctors(id)
                ON DELETE SET NULL;
            END IF;
        END $$;
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_ai_chat_summaries_reviewed_by_doctor_id
        ON ai_chat_summaries (reviewed_by_doctor_id);
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS last_chat_date DATE NULL;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS monthly_chat_count INTEGER NOT NULL DEFAULT 0;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS monthly_chat_image_count INTEGER NOT NULL DEFAULT 0;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS last_chat_month_reset DATE NULL;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS rolling_chat_count INTEGER NOT NULL DEFAULT 0;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS rolling_chat_image_count INTEGER NOT NULL DEFAULT 0;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS rolling_chat_window_start TIMESTAMPTZ NULL;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS burst_chat_count INTEGER NOT NULL DEFAULT 0;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS burst_start_time TIMESTAMPTZ NULL;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS chat_blocked_until TIMESTAMPTZ NULL;
        """,
        # monthly_lab_count — hard cap on Gemini Vision calls per calendar month
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS monthly_lab_count INTEGER NOT NULL DEFAULT 0;
        """,
        # last_lab_reset — the date (year+month) the monthly counter was last zeroed
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS last_lab_reset DATE NULL;
        """,
        # AI chat reports — Google Play AI-Generated Content Policy compliance (added 2026-06-28)
        """
        CREATE TABLE IF NOT EXISTS ai_chat_reports (
            id           SERIAL PRIMARY KEY,
            user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            message_text TEXT    NOT NULL,
            reason       VARCHAR(200) NOT NULL,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        );
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_ai_chat_reports_user_id
        ON ai_chat_reports (user_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_ai_chat_reports_created_at
        ON ai_chat_reports (created_at);
        """,
        # Lab scanner failed-attempt guard (added 2026-06-25)
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS lab_failed_attempt_count INTEGER NOT NULL DEFAULT 0;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS lab_failed_attempt_started_at TIMESTAMPTZ NULL;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS lab_last_failed_attempt_at TIMESTAMPTZ NULL;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS lab_cooldown_until TIMESTAMPTZ NULL;
        """,
        # Voice / TTS quota tracking columns (added 2026-06-16)
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS monthly_audio_count INTEGER NOT NULL DEFAULT 0;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS rolling_audio_count INTEGER NOT NULL DEFAULT 0;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS rolling_audio_window_start TIMESTAMPTZ NULL;
        """,
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS last_audio_month_reset TIMESTAMPTZ NULL;
        """,
        # ── Family Plan: self-referential account linking (added 2026-05-11) ──
        # primary_account_id = NULL  → primary account holder
        # primary_account_id = <id>  → dependent linked to that primary user
        # ON DELETE SET NULL ensures dependents are unlinked (not deleted) when
        # the primary account is removed.
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS primary_account_id INTEGER
            REFERENCES users(id) ON DELETE SET NULL;
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_users_primary_account_id
        ON users (primary_account_id)
        WHERE primary_account_id IS NOT NULL;
        """,
        # ── Doctor earnings ledger (added 2026-05-28) ─────────────────────────
        # Accumulated from Paystack transfer.success webhook events.
        # Stored in NGN (kobo ÷ 100); reversed transfers remove the credit.
        """
        ALTER TABLE doctors
        ADD COLUMN IF NOT EXISTS total_earnings NUMERIC(14,2) NOT NULL DEFAULT 0.00;
        """,
        # Consultation attendance and no-show tracking (added 2026-06-20).
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS patient_joined_at TIMESTAMP NULL;
        """,
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS doctor_joined_at TIMESTAMP NULL;
        """,
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS consultation_started_at TIMESTAMP NULL;
        """,
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS no_show_marked_at TIMESTAMP NULL;
        """,
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS refund_status VARCHAR(32) NULL;
        """,
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS refund_reference VARCHAR NULL;
        """,
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS refund_id VARCHAR NULL;
        """,
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS refund_amount DOUBLE PRECISION NULL;
        """,
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS refund_approved_by_admin_id INTEGER NULL
            REFERENCES users(id);
        """,
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS refund_approved_at TIMESTAMP NULL;
        """,
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS refund_rejected_by_admin_id INTEGER NULL
            REFERENCES users(id);
        """,
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS refund_rejected_at TIMESTAMP NULL;
        """,
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS refund_processed_at TIMESTAMP NULL;
        """,
        """
        ALTER TABLE appointments
        ADD COLUMN IF NOT EXISTS refund_last_error VARCHAR NULL;
        """,
        """
        CREATE UNIQUE INDEX IF NOT EXISTS ix_appointments_refund_reference
        ON appointments (refund_reference)
        WHERE refund_reference IS NOT NULL;
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_appointments_refund_id
        ON appointments (refund_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_appointments_refund_approved_admin
        ON appointments (refund_approved_by_admin_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_appointments_refund_rejected_admin
        ON appointments (refund_rejected_by_admin_id);
        """,
        """
        UPDATE appointments
        SET refund_status = 'awaiting_admin'
        WHERE refund_status = 'pending'
          AND refund_approved_at IS NULL;
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_appointments_consultation_started_at
        ON appointments (consultation_started_at);
        """,
        # Idempotent general-queue doctor payout ledger (added 2026-06-20).
        """
        CREATE TABLE IF NOT EXISTS consultation_payouts (
            id SERIAL PRIMARY KEY,
            appointment_id INTEGER NOT NULL UNIQUE
                REFERENCES appointments(id),
            doctor_id INTEGER NOT NULL REFERENCES doctors(id),
            amount NUMERIC(14,2) NOT NULL,
            status VARCHAR(32) NOT NULL DEFAULT 'awaiting_admin',
            reference VARCHAR(64) NOT NULL UNIQUE,
            recipient_code VARCHAR NULL,
            transfer_code VARCHAR NULL,
            attempts INTEGER NOT NULL DEFAULT 0,
            last_error VARCHAR NULL,
            created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
            paid_at TIMESTAMP NULL,
            approved_by_admin_id INTEGER NULL REFERENCES users(id),
            approved_at TIMESTAMP NULL,
            rejected_by_admin_id INTEGER NULL REFERENCES users(id),
            rejected_at TIMESTAMP NULL,
            rejection_reason VARCHAR NULL
        );
        """,
        """
        ALTER TABLE consultation_payouts
        ADD COLUMN IF NOT EXISTS approved_by_admin_id INTEGER NULL
            REFERENCES users(id);
        """,
        """
        ALTER TABLE consultation_payouts
        ADD COLUMN IF NOT EXISTS approved_at TIMESTAMP NULL;
        """,
        """
        ALTER TABLE consultation_payouts
        ADD COLUMN IF NOT EXISTS rejected_by_admin_id INTEGER NULL
            REFERENCES users(id);
        """,
        """
        ALTER TABLE consultation_payouts
        ADD COLUMN IF NOT EXISTS rejected_at TIMESTAMP NULL;
        """,
        """
        ALTER TABLE consultation_payouts
        ADD COLUMN IF NOT EXISTS rejection_reason VARCHAR NULL;
        """,
        """
        ALTER TABLE consultation_payouts
        ALTER COLUMN status SET DEFAULT 'awaiting_admin';
        """,
        """
        UPDATE consultation_payouts
        SET status = 'awaiting_admin'
        WHERE status = 'pending'
           OR (status = 'blocked' AND approved_at IS NULL);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_consultation_payouts_status
        ON consultation_payouts (status);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_consultation_payouts_doctor_id
        ON consultation_payouts (doctor_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_consultation_payouts_transfer_code
        ON consultation_payouts (transfer_code);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_consultation_payouts_approved_admin
        ON consultation_payouts (approved_by_admin_id);
        """,
        """
        CREATE INDEX IF NOT EXISTS ix_consultation_payouts_rejected_admin
        ON consultation_payouts (rejected_by_admin_id);
        """,
    ]
    with engine.connect() as conn:
        from sqlalchemy import text
        for sql in patches:
            try:
                conn.execute(text(sql))
                conn.commit()
            except Exception as exc:
                conn.rollback()
                logger.exception("[SCHEMA PATCH] Failed applying startup schema patch: %s", exc)
                raise

        unresolved_appointment_types = conn.execute(
            text(
                """
                SELECT COUNT(*)
                FROM appointments
                WHERE appointment_type IS NULL
                """
            )
        ).scalar_one()
        if unresolved_appointment_types:
            logger.warning(
                "[SCHEMA PATCH] %d legacy appointment(s) still have no durable "
                "appointment_type and require review before NOT NULL enforcement.",
                unresolved_appointment_types,
            )
        else:
            logger.info(
                "[SCHEMA PATCH] All appointments have a durable appointment_type."
            )

_apply_schema_patches()


# ---------------------------------------------------------------------------
# ⏰ APScheduler jobs
# ---------------------------------------------------------------------------

import logging as _logging
_sched_log = _logging.getLogger("uvicorn.error")


async def _run_scrubber_job_async():
    """Async wrapper for the sync scrubber so it runs on the AsyncIOScheduler
    without blocking the event loop."""
    import asyncio
    db = SessionLocal()
    try:
        await asyncio.to_thread(scrub_expired_accounts, db)
    except Exception as exc:
        _sched_log.exception("[NDPA SCRUBBER] Unhandled error: %s", exc)
    finally:
        db.close()


async def _run_ai_temp_cleanup_async():
    """Run Cloudinary cleanup off the event loop."""
    import asyncio

    try:
        await asyncio.to_thread(chat.cleanup_stale_temp_images)
    except Exception as exc:
        _sched_log.exception(
            "[AI TEMP IMAGE] Scheduled cleanup failed: %s",
            exc,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: start AsyncIOScheduler on boot, stop on shutdown.

    Jobs registered:
      • ndpa_pii_scrubber       — daily 02:00 UTC  (NDPA 30-day PII scrub)
      • payment_watchdog        — every 5 minutes  (sweep stale transactions)
      • doctor_slot_cleanup     — daily 00:00 UTC  (delete expired free slots)
      • stale_appointment_sweep — hourly           (close/cancel stale bookings)
      • notification_cleanup    — daily 00:15 UTC  (90-day retention cleanup)
      • ai_temp_image_cleanup   — hourly           (delete abandoned AI images)
    """
    scheduler = AsyncIOScheduler(timezone="UTC")

    # Job 1: NDPA PII scrubber — daily at 02:00 UTC
    scheduler.add_job(
        _run_scrubber_job_async,
        trigger=CronTrigger(hour=2, minute=0, timezone="UTC"),
        id="ndpa_pii_scrubber",
        name="NDPA 30-day PII scrubber",
        replace_existing=True,
    )

    # Job 2: Payment watchdog — every 5 minutes
    scheduler.add_job(
        sweep_pending_transactions,
        trigger=IntervalTrigger(minutes=5),
        id="payment_watchdog",
        name="Payment watchdog (sweep pending transactions)",
        replace_existing=True,
    )

    # Job 3: Doctor-slot cleanup — nightly at 00:00 UTC
    scheduler.add_job(
        cleanup_expired_slots,
        trigger=CronTrigger(hour=0, minute=0, timezone="UTC"),
        id="doctor_slot_cleanup",
        name="Nightly expired-slot cleaner",
        replace_existing=True,
    )

    # Job 4: Stale-appointment sweep — every hour
    scheduler.add_job(
        sweep_stale_appointments,
        trigger=IntervalTrigger(hours=1),
        id="stale_appointment_sweep",
        name="Hourly stale pending appointment sweep",
        replace_existing=True,
    )

    # Job 5: Nightly wrap-up for consultations doctors forgot to complete.
    scheduler.add_job(
        complete_expired_consultations,
        trigger=CronTrigger(hour=23, minute=30, timezone="UTC"),
        id="consultation_completion_sweep",
        name="Nightly consultation completion sweep",
        replace_existing=True,
    )

    # Job 6: Mark absent participants after the attendance grace window.
    scheduler.add_job(
        mark_consultation_no_shows,
        trigger=IntervalTrigger(minutes=1),
        id="consultation_no_show_sweep",
        name="Consultation attendance no-show sweep",
        replace_existing=True,
    )

    # Job 7: Initiate admin-approved doctor consultation payouts.
    scheduler.add_job(
        process_approved_consultation_payouts,
        trigger=CronTrigger(minute="*/10", hour="3", timezone="UTC"),
        id="consultation_payout_processor",
        name="Admin-approved consultation payout processor",
        replace_existing=True,
    )

    # Job 8: Initiate admin-approved no-show patient refunds.
    scheduler.add_job(
        process_approved_consultation_refunds,
        trigger=CronTrigger(minute="*/10", hour="2", timezone="UTC"),
        id="consultation_refund_processor",
        name="Admin-approved consultation refund processor",
        replace_existing=True,
    )

    # Job 8: Notification retention cleanup — nightly at 00:15 UTC
    scheduler.add_job(
        cleanup_old_notifications,
        trigger=CronTrigger(hour=0, minute=15, timezone="UTC"),
        id="notification_retention_cleanup",
        name="Nightly 90-day notification retention cleanup",
        replace_existing=True,
    )

    # Job 9: Temporary AI image cleanup — hourly
    scheduler.add_job(
        _run_ai_temp_cleanup_async,
        trigger=IntervalTrigger(hours=1),
        id="ai_temp_image_cleanup",
        name="Hourly temporary AI image cleanup",
        replace_existing=True,
    )

    scheduler.start()
    _sched_log.info(
        "[SCHEDULER] AsyncIOScheduler started. "
        "NDPA scrubber @ 02:00 UTC daily | "
        "Payment watchdog every 5 min | "
        "Doctor-slot cleanup @ 00:00 UTC daily | "
        "Stale-appointment sweep every 1 hour | "
        "AI temporary-image cleanup every 1 hour."
    )

    yield  # ← application runs here

    scheduler.shutdown(wait=False)
    _sched_log.info("[SCHEDULER] AsyncIOScheduler shut down gracefully.")


# ✅ redirect_slashes=False prevents 307 redirects that strip CORS headers
app = FastAPI(title="MDQplus API", redirect_slashes=False, lifespan=lifespan, docs_url=None, redoc_url=None)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)


@app.exception_handler(SQLAlchemyTimeoutError)
async def database_pool_timeout_handler(request: Request, exc: SQLAlchemyTimeoutError):
    """Expose pool exhaustion clearly during load tests without leaking details."""
    try:
        pool_status = engine.pool.status()
    except Exception:
        pool_status = "unavailable"

    logger.error(
        "[DB POOL TIMEOUT] %s %s — pool=%s error=%s",
        request.method,
        request.url.path,
        pool_status,
        exc,
    )
    return JSONResponse(
        status_code=503,
        content={
            "detail": "Database is temporarily busy. Please retry shortly.",
            "error_code": "database_pool_timeout",
        },
        headers={"Retry-After": "1"},
    )



# --- Global Exception Handler: ensures CORS headers are present even on 500 errors ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(
        "🔥 [UNHANDLED ERROR] %s %s — %s",
        request.method,
        request.url.path,
        exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
        headers={
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "*",
            "Access-Control-Allow-Headers": "*",
        },
    )

# ========================================================================
# MIDDLEWARE ORDER MATTERS! Starlette processes middleware in LIFO order.
# The LAST middleware added is the FIRST to process requests/responses.
# So we add CORSMiddleware LAST to ensure it wraps everything.
# ========================================================================

# 1. Payload limiter (innermost — runs closest to the route handlers)
@app.middleware("http")
async def limit_payload_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 10 * 1024 * 1024:
        return JSONResponse(
            status_code=413,
            content={"detail": "Payload exceeds the 10MB limit."}
        )
    return await call_next(request)

# 2. CORS Middleware — MUST be added LAST so it runs FIRST (outermost wrapper)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["AI Health Assistant"])
app.include_router(ai_consent.router, prefix="/api/v1/ai", tags=["AI Consent"])
app.include_router(doctors.router, prefix="/api/v1/doctors", tags=["Doctors"])
app.include_router(appointments.router, prefix="/api/v1/appointments", tags=["Appointments"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin Control"])
app.include_router(content.router, prefix="/api/v1/content", tags=["Content"])
app.include_router(subscription.router, prefix="/api/v1/subscription", tags=["Subscription"])
app.include_router(reviews.router, prefix="/api/v1/reviews", tags=["Reviews"])
app.include_router(media.router, prefix="/api/v1/media", tags=["Media"])
app.include_router(video.router, prefix="/api/v1/video", tags=["Video Call"])
app.include_router(chat_socket.router, prefix="/api/v1/p2p", tags=["P2P Chat"])
app.include_router(upload.router, prefix="/api/v1/upload", tags=["Upload"])
app.include_router(lab.router, prefix="/api/v1/lab", tags=["Lab Scanner"])

app.include_router(emergency.router, prefix="/api/v1/emergency", tags=["Emergency"])
app.include_router(payments.router, prefix="/api/v1/payments", tags=["Payments"])
app.include_router(family.router, prefix="/api/v1/family", tags=["Family Plan"])
app.include_router(vault.router, prefix="/api/v1/vault", tags=["Vault"])
app.include_router(voice.router, prefix="/api/v1/voice", tags=["Voice"])
app.include_router(ai_report.router, prefix="/api/v1/chat", tags=["AI Health Assistant"])
app.include_router(support.router, prefix="/api/v1/support", tags=["Support"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["Notifications"])

# --- STATIC FILES ---
static_dir = "static"
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def health_check():
    return {"status": "healthy", "service": "MDQ+ API"}
