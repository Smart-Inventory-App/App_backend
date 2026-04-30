from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.user import UserCreate, UserLogin, UserResponse, TokenResponse
from app.services.user_service import UserService

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
)


@router.post("/register", response_model=UserResponse)
async def register(user: UserCreate, db: Session = Depends(get_db)):
    """Register a new user"""
    return UserService.create_user(db, user)


@router.post("/login", response_model=TokenResponse)
async def login(login: UserLogin, db: Session = Depends(get_db)):
    """Login user and get access token"""
    return UserService.authenticate_user(db, login)


@router.get("/me", response_model=UserResponse)
async def get_current_user_info(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get current user information"""
    user = UserService.get_user_by_id(db, int(current_user["user_id"]))
    return user
