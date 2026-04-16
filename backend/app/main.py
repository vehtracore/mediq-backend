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
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from app.core.limiter import limiter
from app.core.database import engine, Base, SessionLocal

# ✅ KEEP "app." prefix because your main.py is inside the app folder
from app.api.v1 import auth, chat, doctors, appointments, admin, content, subscription, reviews, media, video, chat_socket, upload, lab
from app.api.v1 import google_auth
from app.api.v1.auth import scrub_expired_accounts

Base.metadata.create_all(bind=engine)


# ---------------------------------------------------------------------------
# ⏰ APScheduler — NDPA 30-day PII scrubber runs daily at 02:00 UTC
# ---------------------------------------------------------------------------

def _run_scrubber_job():
    """Wrapper executed by APScheduler. Opens its own DB session so the
    scheduler thread never shares state with the request-handling threads."""
    db = SessionLocal()
    try:
        scrub_expired_accounts(db)
    except Exception as exc:  # pragma: no cover
        # Exceptions inside scheduler jobs are swallowed by default —
        # log them explicitly so they surface in Render's log stream.
        import logging
        logging.getLogger("uvicorn.error").exception(
            f"[NDPA SCRUBBER] Unhandled error during scheduled run: {exc}"
        )
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """FastAPI lifespan: start scheduler on boot, stop it on shutdown."""
    scheduler = BackgroundScheduler(timezone="UTC")
    scheduler.add_job(
        _run_scrubber_job,
        trigger=CronTrigger(hour=2, minute=0, timezone="UTC"),  # 02:00 UTC daily
        id="ndpa_pii_scrubber",
        name="NDPA 30-day PII scrubber",
        replace_existing=True,
    )
    scheduler.start()
    import logging
    logging.getLogger("uvicorn.error").info(
        "[SCHEDULER] APScheduler started. NDPA scrubber scheduled at 02:00 UTC daily."
    )

    yield  # ← application runs here

    scheduler.shutdown(wait=False)
    logging.getLogger("uvicorn.error").info(
        "[SCHEDULER] APScheduler shut down gracefully."
    )


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

# --- STATIC FILES ---
static_dir = "static"
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
async def health_check():
    return {"status": "healthy", "service": "MDQ+ API"}