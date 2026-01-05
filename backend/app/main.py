from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import engine, Base

# 1. Import API Routers
from app.api.v1 import auth, chat, doctors, appointments, admin, content, subscription, reviews, media, video # <--- ADDED VIDEO

# 2. Import Models
from app.models import user, doctor, appointment, audit, review
from app.models import content as content_model 

from app.models import user, doctor, appointment, audit, review, message 

from app.api.v1 import auth, chat, doctors, appointments, admin, content, subscription, reviews, media, video, chat_socket
# Create Database Tables
Base.metadata.create_all(bind=engine)

app = FastAPI(title="MDQplus API")

# --- CORS CONFIGURATION ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- ROUTER REGISTRATION ---
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(chat.router, prefix="/api/v1/chat", tags=["AI Health Assistant"])
app.include_router(doctors.router, prefix="/api/v1/doctors", tags=["Doctors"])
app.include_router(appointments.router, prefix="/api/v1/appointments", tags=["Appointments"])
app.include_router(admin.router, prefix="/api/v1/admin", tags=["Admin Control"])
app.include_router(content.router, prefix="/api/v1/content", tags=["Content"])
app.include_router(subscription.router, prefix="/api/v1/subscription", tags=["Subscription"])
app.include_router(reviews.router, prefix="/api/v1/reviews", tags=["Reviews"])
app.include_router(media.router, prefix="/api/v1/media", tags=["Media"])
app.include_router(video.router, prefix="/api/v1/video", tags=["Video Call"]) # <--- NEW ROUTE
app.include_router(chat_socket.router, prefix="/api/v1/p2p", tags=["P2P Chat"])

@app.get("/")
def root():
    return {"message": "MedIQ Brain is Online"}

# update chat