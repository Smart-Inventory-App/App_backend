
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from jose import jwt
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.user import PasswordRecoveryCode
from app.schemas.user import (
    EmailCheckRequest,
    EmailCheckResponse,
    ForgotPasswordRequest,
    ResetPasswordRequest,
    ResetTokenResponse,
    SocialCallbackRequest,
    TokenResponse,
    UserLogin,
    UserRegister,
    VerifyCodeRequest,
)
from app.services.keycloak_service import keycloak

router = APIRouter(prefix="/auth", tags=["auth"])

_RESET_TOKEN_MINUTES = 15


def _make_reset_token(email: str) -> str:
    payload = {
        "sub": email,
        "purpose": "password_reset",
        "exp": datetime.now(timezone.utc) + timedelta(minutes=_RESET_TOKEN_MINUTES),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def _decode_reset_token(token: str) -> str:
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if payload.get("purpose") != "password_reset":
            raise ValueError
        return payload["sub"]
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Token de reset inválido")


@router.post("/login", response_model=TokenResponse)
async def login(body: UserLogin):
    return await keycloak.login(body.email, body.password)


@router.post("/register", status_code=201)
async def register(body: UserRegister):
    await keycloak.register(body.email, body.password)
    return {"detail": "Usuario creado"}


@router.post("/check-email", response_model=EmailCheckResponse)
async def check_email(body: EmailCheckRequest):
    exists = await keycloak.email_exists(body.email)
    return EmailCheckResponse(exists=exists)


@router.get("/me")
async def me(current_user: dict = Depends(get_current_user)):
    return {
        "email": current_user.get("email"),
        "username": current_user.get("preferred_username"),
        "sub": current_user.get("sub"),
    }


@router.post("/forgot-password")
async def forgot_password(body: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Always returns 200 to avoid email enumeration."""
    user_exists = await keycloak.email_exists(body.email)
    if user_exists:
        code = keycloak.generate_recovery_code()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        db.add(PasswordRecoveryCode(email=body.email, code=code, expires_at=expires_at))
        db.commit()
        keycloak.send_recovery_email(body.email, code)
    return {"detail": "Si el email está registrado, recibirás un código"}


@router.post("/verify-code", response_model=ResetTokenResponse)
async def verify_code(body: VerifyCodeRequest, db: Session = Depends(get_db)):
    now = datetime.now(timezone.utc)
    record = (
        db.query(PasswordRecoveryCode)
        .filter(
            PasswordRecoveryCode.email == body.email,
            PasswordRecoveryCode.code == body.code,
            PasswordRecoveryCode.used == False,  # noqa: E712
            PasswordRecoveryCode.expires_at > now,
        )
        .order_by(PasswordRecoveryCode.created_at.desc())
        .first()
    )
    if not record:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Código inválido o expirado")

    record.used = True
    db.commit()
    return ResetTokenResponse(reset_token=_make_reset_token(body.email))


@router.post("/reset-password")
async def reset_password(body: ResetPasswordRequest):
    email = _decode_reset_token(body.reset_token)
    user_id = await keycloak.get_user_id_by_email(email)
    if not user_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Usuario no encontrado")
    await keycloak.reset_password(user_id, body.new_password)
    return {"detail": "Contraseña actualizada"}


@router.post("/social-callback", response_model=TokenResponse)
async def social_callback(body: SocialCallbackRequest):
    return await keycloak.exchange_code(body.code, body.redirect_uri, body.code_verifier)
