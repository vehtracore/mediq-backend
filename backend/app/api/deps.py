import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt import PyJWKClient, PyJWTError
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.user import User

logger = logging.getLogger("uvicorn.error")


def _positive_number_from_env(name: str, default: float) -> float:
    """Read a positive numeric setting without making auth fail at startup."""
    raw_value = os.getenv(name)
    if raw_value is None:
        return default

    try:
        value = float(raw_value)
    except ValueError:
        logger.warning("[AUTH] Invalid %s=%r; using default %s", name, raw_value, default)
        return default

    if value <= 0:
        logger.warning("[AUTH] %s must be positive; using default %s", name, default)
        return default

    return value


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
SUPABASE_URL: str = os.getenv(
    "SUPABASE_URL",
    "https://hzrjaquqlpkbggwdcres.supabase.co",
).rstrip("/")
JWKS_URL: str = f"{SUPABASE_URL}/auth/v1/.well-known/jwks.json"
SUPABASE_JWT_AUDIENCE: str = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
SUPABASE_JWT_ISSUER: str = os.getenv(
    "SUPABASE_JWT_ISSUER",
    f"{SUPABASE_URL}/auth/v1",
).rstrip("/")

# Keep the JWKS document in-process so normal authenticated requests do not
# depend on a Supabase network call. An unknown key ID still forces a refresh,
# which preserves signing-key rotation support.
jwks_client = PyJWKClient(
    JWKS_URL,
    cache_jwk_set=True,
    lifespan=_positive_number_from_env("JWKS_CACHE_LIFESPAN_SECONDS", 3600),
    timeout=_positive_number_from_env("JWKS_FETCH_TIMEOUT_SECONDS", 5),
)

# The tokenUrl is kept for OpenAPI docs compatibility — the frontend no
# longer calls this endpoint; Supabase handles token issuance.
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=True)


@dataclass(frozen=True)
class SupabaseIdentity:
    """Verified immutable identity claims from a Supabase access token."""

    auth_id: UUID
    email: str
    expires_at: datetime


def get_supabase_identity(token: str = Depends(oauth2_scheme)) -> SupabaseIdentity:
    """Verify a Supabase JWT without requiring an existing local User row."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        signing_key = jwks_client.get_signing_key_from_jwt(token)
        payload = jwt.decode(
            token,
            signing_key.key,
            algorithms=["ES256"],
            audience=SUPABASE_JWT_AUDIENCE,
            issuer=SUPABASE_JWT_ISSUER,
        )
        email = payload.get("email")
        subject = payload.get("sub")
        expires_at_epoch = payload.get("exp")
        if not isinstance(email, str) or not email.strip():
            raise credentials_exception
        if not isinstance(subject, str):
            raise credentials_exception
        if not isinstance(expires_at_epoch, (int, float)):
            raise credentials_exception
        auth_id = UUID(subject)
    except HTTPException:
        raise
    except (PyJWTError, ValueError, TypeError) as exc:
        logger.warning(
            "[AUTH] JWT verification failed failure_category=%s",
            type(exc).__name__,
        )
        raise credentials_exception
    except Exception as exc:
        logger.error(
            "[AUTH] Unexpected token verification failure_category=%s",
            type(exc).__name__,
        )
        raise credentials_exception

    return SupabaseIdentity(
        auth_id=auth_id,
        email=email.strip().lower(),
        expires_at=datetime.fromtimestamp(expires_at_epoch, tz=timezone.utc),
    )


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
        4. The immutable `sub` UUID resolves the local User. Signed email is
           used only once to bind pre-migration rows that have no UUID yet.
    """

    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    identity = get_supabase_identity(token)

    # ── Resolve local user ────────────────────────────────────────────────────
    user = (
        db.query(User)
        .filter(User.supabase_auth_id == identity.auth_id)
        .first()
    )
    if user is None:
        # One-time bridge for rows created before immutable Supabase IDs were
        # stored. A signed token proves control of the normalized email, and an
        # already-bound row can never be claimed by a different auth subject.
        legacy_matches = (
            db.query(User)
            .filter(User.email.ilike(identity.email))
            .limit(2)
            .all()
        )
        legacy_user = legacy_matches[0] if len(legacy_matches) == 1 else None
        if legacy_user is not None and legacy_user.supabase_auth_id is None:
            legacy_user.supabase_auth_id = identity.auth_id
            db.commit()
            db.refresh(legacy_user)
            user = legacy_user
    if user is None:
        logger.warning("[AUTH] Authenticated identity has no local User row.")
        raise credentials_exception

    # Used by long-lived protocols such as WebSocket to enforce token expiry
    # after the initial handshake. It is transient and never persisted.
    user._auth_expires_at = identity.expires_at

    if user.is_banned:
        logger.info(f"[AUTH] Banned user attempted access: {user.email}")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Account suspended. Please contact support."
        )

    if not user.is_active:
        doctor_status = None
        if user.role == "doctor":
            from app.models.doctor import Doctor

            # Only inactive doctors need their onboarding status checked.
            # Select the status column alone instead of loading the full profile.
            doctor_status = (
                db.query(Doctor.status)
                .filter(Doctor.user_id == user.id)
                .scalar()
            )

        if doctor_status == "rejected":
            pass  # Allow access to quarantine flow
        elif doctor_status == "pending":
            logger.info(f"[AUTH] Pending doctor attempted access: {user.email}")
            raise HTTPException(status_code=403, detail="Account pending approval")
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
        user.auto_renew = False
        # Cascade downgrade to all dependents
        db.query(User).filter(User.primary_account_id == user.id).update(
            {
                User.plan: "free",
                User.subscription_expiry: None,
                User.auto_renew: False,
            },
            synchronize_session=False,
        )
        db.commit()
        db.refresh(user)

    logger.debug("[AUTH] Authenticated local user_id=%s", user.id)
    return user
