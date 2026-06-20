import logging
import os
import sys
from urllib.parse import urlparse, urlunparse
from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


def _positive_int_from_env(name: str, default: int, *, allow_zero: bool = False) -> int:
    """Read a non-negative/positive integer setting without breaking startup."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError:
        logger.warning("[DB] Invalid %s=%r; using default %d", name, raw_value, default)
        return default

    minimum = 0 if allow_zero else 1
    if value < minimum:
        logger.warning(
            "[DB] %s must be at least %d; using default %d",
            name,
            minimum,
            default,
        )
        return default

    return value


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
_parsed = None
try:
    _parsed = urlparse(SQLALCHEMY_DATABASE_URL)
    _safe_url = urlunparse(_parsed._replace(netloc=(
        f"{_parsed.username}:***@{_parsed.hostname}"
        + (f":{_parsed.port}" if _parsed.port else "")
    )))
except Exception:
    _safe_url = "<unparseable URL>"
logger.info("[DB] Connecting to: %s", _safe_url)

# Supabase's pooler hostname contains "pooler.supabase.com". The transaction
# pooler normally uses port 6543 and is the preferred fit for this deployment.
if _parsed and _parsed.hostname and _parsed.hostname.endswith("pooler.supabase.com"):
    logger.info(
        "[DB] Supabase pooler detected: host=%s port=%s",
        _parsed.hostname,
        _parsed.port,
    )
elif _parsed and _parsed.hostname and _parsed.hostname.endswith("supabase.co"):
    logger.warning(
        "[DB] Direct Supabase database host detected (%s:%s). "
        "Use the Supabase pooler connection string on Render.",
        _parsed.hostname,
        _parsed.port,
    )

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
    # A single backend worker can use at most 10 connections by default:
    # seven steady connections plus three short-lived burst connections.
    db_pool_size = _positive_int_from_env("DB_POOL_SIZE", 7)
    db_max_overflow = _positive_int_from_env(
        "DB_MAX_OVERFLOW",
        3,
        allow_zero=True,
    )
    db_pool_timeout = _positive_int_from_env("DB_POOL_TIMEOUT", 10)

    logger.info(
        "[DB] Pool configured: size=%d overflow=%d timeout=%ds max_connections=%d",
        db_pool_size,
        db_max_overflow,
        db_pool_timeout,
        db_pool_size + db_max_overflow,
    )

    engine = create_engine(
        SQLALCHEMY_DATABASE_URL,
        pool_size=db_pool_size,
        max_overflow=db_max_overflow,
        pool_timeout=db_pool_timeout,
        pool_pre_ping=True,  # Validate connections before checkout.
    )

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
