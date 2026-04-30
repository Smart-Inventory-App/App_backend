"""
tRPC Router for authentication
Type-safe API endpoints that can be called from frontend
"""
from fastapi import Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.schemas.user import UserCreate, UserLogin, UserResponse, TokenResponse
from app.services.user_service import UserService


async def register(user: UserCreate, db: Session = Depends(get_db)) -> UserResponse:
    """Register a new user"""
    created_user = UserService.create_user(db, user)
    return UserResponse.from_orm(created_user)


async def login(login: UserLogin, db: Session = Depends(get_db)) -> TokenResponse:
    """Login user and get access token"""
    return UserService.authenticate_user(db, login)


async def me(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)) -> UserResponse:
    """Get current user information"""
    user = UserService.get_user_by_id(db, int(current_user["user_id"]))
    return UserResponse.from_orm(user)
