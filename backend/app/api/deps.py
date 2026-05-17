import os
import logging

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import jwt, JWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User

logger = logging.getLogger("uvicorn.error")

# ---------------------------------------------------------------------------
# Supabase JWT configuration
# ---------------------------------------------------------------------------
# The JWT secret is found in your Supabase dashboard:
#   Settings → API → JWT Secret
#
# Supabase access tokens are signed with HS256 and carry
# aud="authenticated" for logged-in users.
# ---------------------------------------------------------------------------
SUPABASE_JWT_SECRET: str = os.getenv("SUPABASE_JWT_SECRET", "")
SUPABASE_JWT_ALGORITHM: str = "HS256"
SUPABASE_JWT_AUDIENCE: str = "authenticated"

# The tokenUrl is kept for OpenAPI docs compatibility — the frontend no
# longer calls this endpoint; Supabase handles token issuance.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=True)


def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: Session = Depends(get_db),
) -> User:
    """
    Decode and verify a Supabase-issued JWT, then resolve the local User row.

    Token flow:
        1. Frontend authenticates with Supabase Auth (email/password, OAuth, etc.)
        2. Frontend sends the Supabase `access_token` in `Authorization: Bearer <token>`
        3. This function verifies the JWT signature (HS256) and audience claim.
        4. The `email` field from the JWT payload is used to look up the local User.
    """

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # ── Guard: JWT secret must be configured ──────────────────────────────────
    if not SUPABASE_JWT_SECRET:
        logger.error(
            "[AUTH] FATAL: SUPABASE_JWT_SECRET is not set. "
            "Add it to your .env / Render environment variables. "
            "Find it at Supabase Dashboard → Settings → API → JWT Secret."
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Server authentication misconfigured.",
        )

    # ── Decode & verify ───────────────────────────────────────────────────────
    try:
        logger.debug(f"[AUTH] Verifying token: {token[:15]}...")

        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=[SUPABASE_JWT_ALGORITHM],
            audience=SUPABASE_JWT_AUDIENCE,
        )

        # Supabase stores the user's email in the top-level `email` claim.
        email: str | None = payload.get("email")
        if email is None:
            logger.warning("[AUTH] Token decoded but 'email' claim is missing.")
            raise credentials_exception

    except JWTError as e:
        logger.warning(f"[AUTH] JWT verification failed: {e}")
        raise credentials_exception

    # ── Resolve local user ────────────────────────────────────────────────────
    user = db.query(User).filter(User.email == email).first()
    if user is None:
        logger.warning(f"[AUTH] Authenticated email {email} has no local User row.")
        raise credentials_exception

    # --- SUSPENSION / BAN CHECK ---
    doctor_status = None
    if user.role == "doctor":
        from app.models.doctor import Doctor
        doctor = db.query(Doctor).filter(Doctor.user_id == user.id).first()
        if doctor:
            doctor_status = doctor.status

    if user.is_banned:
        logger.info(f"[AUTH] Banned user attempted access: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account suspended. Please contact support."
        )

    if not user.is_active:
        if doctor_status == "rejected":
            pass  # Allow access to quarantine flow
        elif doctor_status == "pending":
            logger.info(f"[AUTH] Pending doctor attempted access: {user.email}")
            raise HTTPException(status_code=401, detail="Account pending approval")
        else:
            logger.info(f"[AUTH] Inactive user attempted access: {user.email}")
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account suspended. Please contact support.",
            )

    logger.debug(f"[AUTH] ✅ Authenticated: {user.first_name} ({user.email})")
    return user