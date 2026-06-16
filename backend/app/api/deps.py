import logging
from datetime import datetime, timezone

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import PyJWKClient, PyJWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User

logger = logging.getLogger("uvicorn.error")


def _is_subscription_expired(user: User) -> bool:
    if user.subscription_expiry is None:
        return False

    expiry = user.subscription_expiry
    if expiry.tzinfo is None:
        expiry = expiry.replace(tzinfo=timezone.utc)

    return expiry < datetime.now(timezone.utc)

# ---------------------------------------------------------------------------
# Supabase JWT configuration — asymmetric ES256 via JWKS
# ---------------------------------------------------------------------------
# Supabase's modern API keys sign access tokens with ECDSA P-256 (ES256).
# We fetch the public signing key dynamically from the project's JWKS endpoint
# so we never need to store or rotate a shared secret.
#
# The client is initialised once at module load time and caches the JWKS
# response internally, refreshing only when it encounters an unknown key ID.
# ---------------------------------------------------------------------------
SUPABASE_URL: str = "https://hzrjaquqlpkbggwdcres.supabase.co"
JWKS_URL: str = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
SUPABASE_JWT_AUDIENCE: str = "authenticated"

jwks_client = PyJWKClient(JWKS_URL)

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
        3. This function fetches the matching public key from the Supabase JWKS
           endpoint and verifies the JWT signature (ES256) and audience claim.
        4. The `email` field from the JWT payload is used to look up the local User.
    """

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    # ── Decode & verify ───────────────────────────────────────────────────────
    try:
        logger.debug(f"[AUTH] Verifying token: {token[:15]}...")

        # Resolve the correct public key using the token's `kid` header claim.
        signing_key = jwks_client.get_signing_key_from_jwt(token)

        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience=SUPABASE_JWT_AUDIENCE,
        )

        # Supabase stores the user's email in the top-level `email` claim.
        email: str | None = payload.get("email")
        if email is None:
            logger.warning("[AUTH] Token decoded but 'email' claim is missing.")
            raise credentials_exception

    except PyJWTError as e:
        logger.warning(f"[AUTH] JWT verification failed: {e}")
        raise credentials_exception
    except Exception as e:
        # Catch JWKS fetch failures, network errors, etc.
        logger.error(f"[AUTH] Unexpected error during token verification: {e}")
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

    if _is_subscription_expired(user):
        logger.info(
            "[AUTH] Lazy subscription downgrade — user_id=%s expired_at=%s",
            user.id,
            user.subscription_expiry,
        )
        user.plan = "free"
        user.subscription_expiry = None
        user.paystack_subscription_code = None
        # Cascade downgrade to all dependents
        db.query(User).filter(User.primary_account_id == user.id).update(
            {
                User.plan: "free",
                User.subscription_expiry: None,
            },
            synchronize_session=False,
        )
        db.commit()
        db.refresh(user)

    logger.debug(f"[AUTH] ✅ Authenticated: {user.first_name} ({user.email})")
    return user
