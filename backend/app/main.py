import os
import traceback
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from app.core.limiter import limiter
from app.core.database import engine, Base, SessionLocal

# ✅ KEEP "app." prefix because your main.py is inside the app folder
from app.api.v1 import auth, chat, doctors, appointments, admin, content, subscription, reviews, media, video, chat_socket, upload, lab
from app.api.v1 import google_auth
from app.api.v1 import emergency
from app.api.v1 import payments
from app.api.v1.auth import scrub_expired_accounts
from app.services.watchdog_service import sweep_pending_transactions

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
    ]
    with engine.connect() as conn:
        from sqlalchemy import text
        for sql in patches:
            conn.execute(text(sql))
        conn.commit()

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


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: start AsyncIOScheduler on boot, stop on shutdown.

    Jobs registered:
      • ndpa_pii_scrubber       — daily 02:00 UTC  (NDPA 30-day PII scrub)
      • payment_watchdog        — every 5 minutes  (sweep stale transactions)
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

    scheduler.start()
    _sched_log.info(
        "[SCHEDULER] AsyncIOScheduler started. "
        "NDPA scrubber @ 02:00 UTC daily | Payment watchdog every 5 min."
    )

    yield  # ← application runs here

    scheduler.shutdown(wait=False)
    _sched_log.info("[SCHEDULER] AsyncIOScheduler shut down gracefully.")


# ✅ redirect_slashes=False prevents 307 redirects that strip CORS headers
app = FastAPI(title="MDQplus API", redirect_slashes=False, lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("FATAL: SECRET_KEY environment variable is missing.")

# --- Global Exception Handler: ensures CORS headers are present even on 500 errors ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    tb = traceback.format_exc()
    print(f"🔥 [UNHANDLED ERROR] {request.method} {request.url.path}")
    print(f"   Exception: {exc}")
    print(f"   Traceback:\n{tb}")
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

# 2. Session Middleware (required for Google OAuth state tracking)
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
)

# 3. CORS Middleware — MUST be added LAST so it runs FIRST (outermost wrapper)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["AI Health Assistant"])
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
app.include_router(google_auth.router, prefix="/auth/google", tags=["Google OAuth"])
app.include_router(emergency.router, prefix="/api/v1/emergency", tags=["Emergency"])
app.include_router(payments.router, prefix="/api/v1/payments", tags=["Payments"])

# --- STATIC FILES ---
static_dir = "static"
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def health_check():
    return {"status": "healthy", "service": "MDQ+ API"}