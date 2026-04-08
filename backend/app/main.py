import os
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from app.core.limiter import limiter
from app.core.database import engine, Base

# ✅ KEEP "app." prefix because your main.py is inside the app folder
from app.api.v1 import auth, chat, doctors, appointments, admin, content, subscription, reviews, media, video, chat_socket, upload, lab
from app.api.v1 import google_auth

Base.metadata.create_all(bind=engine)

app = FastAPI(title="MDQplus API")
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

@app.middleware("http")
async def limit_payload_size(request: Request, call_next):
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > 10 * 1024 * 1024:
        return JSONResponse(
            status_code=413,
            content={"detail": "Payload exceeds the 10MB limit."}
        )
    return await call_next(request)

SECRET_KEY = os.getenv("SECRET_KEY")
if not SECRET_KEY:
    raise ValueError("FATAL: SECRET_KEY environment variable is missing.")

# --- Session Middleware (required for Google OAuth state tracking) ---
app.add_middleware(
    SessionMiddleware,
    secret_key=SECRET_KEY,
)

origins = os.getenv("ALLOWED_ORIGINS", "http://localhost,http://localhost:3000").split(",")

# --- 🚀 RENDER CORS FIX (The Critical Part) ---
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