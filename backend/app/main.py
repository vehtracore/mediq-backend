import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles 
from app.core.database import engine, Base

# ✅ KEEP "app." prefix because your main.py is inside the app folder
from app.api.v1 import auth, chat, doctors, appointments, admin, content, subscription, reviews, media, video, chat_socket, upload

Base.metadata.create_all(bind=engine)

app = FastAPI(title="MDQplus API")

# --- 🚀 RENDER CORS FIX (The Critical Part) ---
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex="https?://.*", # ✅ Allows Render + Localhost
    allow_credentials=True,
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

# --- STATIC FILES ---
static_dir = "static"
if not os.path.exists(static_dir):
    os.makedirs(static_dir)

app.mount("/static", StaticFiles(directory=static_dir), name="static")

@app.get("/")
def root():
    return {"message": "MedIQ Brain is Online"}