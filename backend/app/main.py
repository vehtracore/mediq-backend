from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.core.database import engine, Base

# 1. Import API Routers (The Logic)
from app.api.v1 import auth, chat, doctors, appointments, admin, content, subscription, reviews

# 2. Import Models (The Database) - ALIASING 'content' TO AVOID CONFLICT
from app.models import user, doctor, appointment, audit, review
from app.models import content as content_model 

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

@app.get("/")
def root():
    return {"message": "MedIQ Brain is Online"}