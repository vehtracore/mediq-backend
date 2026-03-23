"""
Google OAuth Endpoints — Login redirect and callback handler.
"""
import os
import uuid
import logging

from fastapi import APIRouter, Request, Depends
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core import security
from app.models.user import User
from app.services.oauth_service import oauth

router = APIRouter()
logger = logging.getLogger("uvicorn.error")

FRONTEND_CALLBACK_URL = os.getenv(
    "GOOGLE_FRONTEND_CALLBACK",
    "http://localhost:64603/#/auth_callback",
)


# ───────────────────────── 1. Redirect to Google ─────────────────────────
@router.get("/login", name="google_login")
async def google_login(request: Request):
    """Redirect the user to Google's consent screen."""
    redirect_uri = request.url_for("google_callback")
    # Force HTTPS in production (proxy / Render strips the scheme)
    if os.getenv("RENDER"):
        redirect_uri = str(redirect_uri).replace("http://", "https://")
    logger.info(f"[GOOGLE AUTH] Redirecting to Google. callback={redirect_uri}")
    return await oauth.google.authorize_redirect(request, str(redirect_uri))


# ───────────────────────── 2. Handle Google Callback ─────────────────────
@router.get("/callback", name="google_callback")
async def google_callback(request: Request, db: Session = Depends(get_db)):
    """
    Google redirects here after user grants access.
    Exchange the code for a token, fetch user info, and either log in
    or auto-create a new account.
    """
    try:
        token = await oauth.google.authorize_access_token(request)
    except Exception as exc:
        logger.error(f"[GOOGLE AUTH] Token exchange failed: {exc}")
        return RedirectResponse(f"{FRONTEND_CALLBACK_URL}?error=token_exchange_failed")

    # --- Extract user info from the ID token (or userinfo endpoint) ---
    try:
        user_info = token.get("userinfo")
        if not user_info:
            user_info = await oauth.google.userinfo(token=token)
    except Exception as exc:
        logger.error(f"[GOOGLE AUTH] Userinfo fetch failed: {exc}")
        return RedirectResponse(f"{FRONTEND_CALLBACK_URL}?error=userinfo_failed")

    email = user_info.get("email")
    given_name = user_info.get("given_name", "")
    family_name = user_info.get("family_name", "")
    picture = user_info.get("picture")

    if not email:
        logger.error("[GOOGLE AUTH] No email returned from Google.")
        return RedirectResponse(f"{FRONTEND_CALLBACK_URL}?error=no_email")

    logger.info(f"[GOOGLE AUTH] Google user: {email} ({given_name} {family_name})")

    # --- Look up or create the user ---
    user = db.query(User).filter(User.email == email).first()

    if user:
        # Existing user — update picture & provider if not set
        if picture and not user.image_url:
            user.image_url = picture
        if not user.auth_provider:
            user.auth_provider = "google"
        db.commit()
        logger.info(f"[GOOGLE AUTH] Existing user logged in: {user.email}")
    else:
        # Auto-create new account
        random_password = uuid.uuid4().hex
        user = User(
            email=email,
            first_name=given_name or "Google",
            last_name=family_name or "User",
            hashed_password=security.get_password_hash(random_password),
            is_verified=True,
            is_active=True,
            auth_provider="google",
            image_url=picture,
            role="patient",
        )
        db.add(user)
        db.commit()
        db.refresh(user)
        logger.info(f"[GOOGLE AUTH] New user created: {user.email}")

    # --- Issue JWT pair and redirect to frontend ---
    access_token = security.create_access_token(data={"sub": user.email})
    refresh_token = security.create_refresh_token(data={"sub": user.email})
    redirect_url = f"{FRONTEND_CALLBACK_URL}?token={access_token}&refresh_token={refresh_token}"
    return RedirectResponse(redirect_url)
