import os
import sys
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# 1. Load Secrets
load_dotenv()

# 2. Get Database URL
# CHANGE: We removed the "sqlite" fallback. Now it is None if .env is missing.
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

# DEBUG PRINT: This will tell us exactly what the script is seeing
print(f"🔌 CONNECTING TO: {SQLALCHEMY_DATABASE_URL}")

if not SQLALCHEMY_DATABASE_URL:
    print("❌ ERROR: Could not find DATABASE_URL in .env file.")
    sys.exit(1) # Crash intentionally so we know something is wrong

# --- FIX: Handle Supabase/Render URL format compatibility ---
if SQLALCHEMY_DATABASE_URL.startswith("postgres://"):
    SQLALCHEMY_DATABASE_URL = SQLALCHEMY_DATABASE_URL.replace("postgres://", "postgresql://", 1)

# 3. Configure Engine
if "sqlite" in SQLALCHEMY_DATABASE_URL:
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
    )
else:
    # PostgreSQL specific args (Cloud Production)
    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"prepare_threshold": None}
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()