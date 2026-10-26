from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.profile import DEFAULT_ALERT_CHECK_HOUR, DEFAULT_COVERAGE_DAYS, DEFAULT_DIAS_ALERTA_VENCIMIENTO, DEFAULT_USER_TYPE, UserProfile
from app.models.user import AuthUser
from app.schemas.user import PROFILE_TEXT_MAX, ProfileResponse, ProfileUpdate, NotificationToken

router = APIRouter(prefix="/profile", tags=["profile"])


def _as_uuid(value):
    """`sub` del token a UUID. Devuelve None si no lo es, para que no haya match."""
    try:
        return UUID(str(value))
    except ValueError:
        return None


def _clean_username(username: str | None) -> str | None:
    """El nombre de usuario sin espacios en los bordes; vacío es lo mismo que no tener."""
    cleaned = (username or "").strip()
    return cleaned or None


def _same_username(a: str | None, b: str | None) -> bool:
    """Dos nombres son el mismo aunque cambien las mayúsculas: «Ana» y «ana» no pueden convivir."""
    return a is not None and b is not None and a.lower() == b.lower()


def _username_taken(username: str, user_id: str, db: Session) -> bool:
    """Si otra cuenta ya tiene ese nombre de usuario."""
    return (
        db.query(UserProfile.user_id)
        .filter(func.lower(UserProfile.username) == username.lower(), UserProfile.user_id != user_id)
        .first()
        is not None
    )


def _get_or_create(user_id: str, db: Session) -> UserProfile:
    profile = db.query(UserProfile).filter(UserProfile.user_id == user_id).first()
    if not profile:
        profile = UserProfile(user_id=user_id)
        db.add(profile)
        db.commit()
        db.refresh(profile)
    return profile


def _to_response(user_id: str, email: str | None, profile: UserProfile) -> ProfileResponse:
    return ProfileResponse(
        sub=user_id,
        email=email,
        username=profile.username,
        firstName=profile.first_name,
        lastName=profile.last_name,
        coverageDaysThreshold=profile.stock_minimo or DEFAULT_COVERAGE_DAYS,
        expiryDaysThreshold=profile.dias_alerta_vencimiento or DEFAULT_DIAS_ALERTA_VENCIMIENTO,
        alertCheckHour=profile.alert_check_hour if profile.alert_check_hour is not None else DEFAULT_ALERT_CHECK_HOUR,
        userType=profile.user_type or DEFAULT_USER_TYPE,
    )


@router.get("/", response_model=ProfileResponse)
async def get_profile(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    profile = _get_or_create(user_id, db)
    return _to_response(user_id, current_user.get("email"), profile)


@router.get("/username-available")
async def username_available(
    username: str = Query(..., max_length=PROFILE_TEXT_MAX),
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Si el nombre de usuario se puede usar. Un nombre que ya es el de esta cuenta cuenta como disponible."""
    user_id = current_user["sub"]
    cleaned = _clean_username(username)
    if cleaned is None:
        return {"available": True}
    own = db.query(UserProfile.username).filter(UserProfile.user_id == user_id).scalar()
    if _same_username(own, cleaned):
        return {"available": True}
    return {"available": not _username_taken(cleaned, user_id, db)}


@router.put("/", response_model=ProfileResponse)
async def update_profile(
    data: ProfileUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    profile = _get_or_create(user_id, db)
    username = _clean_username(data.username)
    # Solo se valida si el nombre cambia: quien ya tiene un nombre repetido (de antes de esta regla) puede seguir
    # guardando su perfil sin tocarlo
    if username is not None and not _same_username(profile.username, username) and _username_taken(username, user_id, db):
        raise HTTPException(status_code=409, detail="profile.username_taken")
    profile.first_name = data.firstName
    profile.last_name = data.lastName
    profile.username = username
    if data.coverageDaysThreshold is not None:
        profile.stock_minimo = data.coverageDaysThreshold
    if data.expiryDaysThreshold is not None:
        profile.dias_alerta_vencimiento = data.expiryDaysThreshold
    if data.alertCheckHour is not None:
        profile.alert_check_hour = data.alertCheckHour
    if data.userType is not None:
        profile.user_type = data.userType
    db.commit()
    db.refresh(profile)
    return _to_response(user_id, current_user.get("email"), profile)

@router.post("/register_notification_token", status_code=200)
async def register_token(
    data: NotificationToken,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user_id = current_user["sub"]
    
    auth_user = db.query(AuthUser).filter(AuthUser.id == _as_uuid(user_id)).first()
    if not auth_user:
        return {"message": "User not found"}
    auth_user.firebase_token = data.token
    db.commit()
    db.refresh(auth_user)
    print(f"Registered notification token for user {user_id}: {data.token}")
    return {"message": "Token registered successfully"}

@router.delete("/unregister_notification_token", status_code=200)
async def unregister_token(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    user_id = current_user["sub"]

    auth_user = db.query(AuthUser).filter(AuthUser.id == _as_uuid(user_id)).first()
    if not auth_user:
        return {"message": "User not found"}
    auth_user.firebase_token = None
    db.commit()
    db.refresh(auth_user)
    print(f"Unregistered notification token for user {user_id}")
    return {"message": "Token unregistered successfully"}
