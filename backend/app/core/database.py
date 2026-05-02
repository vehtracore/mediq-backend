import logging
import os
import sys
from urllib.parse import urlparse, urlunparse
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# 1. Load Secrets
load_dotenv()

# 2. Get Database URL
# CHANGE: We removed the "sqlite" fallback. Now it is None if .env is missing.
SQLALCHEMY_DATABASE_URL = os.getenv("DATABASE_URL")

if not SQLALCHEMY_DATABASE_URL:
    logger.critical("DATABASE_URL is not set — cannot start. Check your .env / environment config.")
    sys.exit(1)  # Crash intentionally so we know something is wrong

# Log a redacted URL so we can confirm which host we're connecting to
# without exposing the password in plaintext.
try:
    _parsed = urlparse(SQLALCHEMY_DATABASE_URL)
    _safe_url = urlunparse(_parsed._replace(netloc=(
        f"{_parsed.username}:***@{_parsed.hostname}"
        + (f":{_parsed.port}" if _parsed.port else "")
    )))
except Exception:
    _safe_url = "<unparseable URL>"
logger.info("[DB] Connecting to: %s", _safe_url)

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