from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.profile import DEFAULT_COVERAGE_DAYS, DEFAULT_DIAS_ALERTA_VENCIMIENTO, UserProfile
from app.schemas.user import ProfileResponse, ProfileUpdate

router = APIRouter(prefix="/profile", tags=["profile"])


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
    )


@router.get("/", response_model=ProfileResponse)
async def get_profile(
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    profile = _get_or_create(user_id, db)
    return _to_response(user_id, current_user.get("email"), profile)


@router.put("/", response_model=ProfileResponse)
async def update_profile(
    data: ProfileUpdate,
    current_user: dict = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    user_id = current_user["sub"]
    profile = _get_or_create(user_id, db)
    profile.first_name = data.firstName
    profile.last_name = data.lastName
    profile.username = data.username
    if data.coverageDaysThreshold is not None:
        profile.stock_minimo = data.coverageDaysThreshold
    if data.expiryDaysThreshold is not None:
        profile.dias_alerta_vencimiento = data.expiryDaysThreshold
    db.commit()
    db.refresh(profile)
    return _to_response(user_id, current_user.get("email"), profile)
