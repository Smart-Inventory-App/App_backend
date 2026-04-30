"""
REST API adapter for tRPC-like endpoints
Maps REST routes to tRPC procedures
"""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.core.database import get_db
from app.core.security import get_current_user
from app.routers import auth as auth_router

router = APIRouter(prefix="/api", tags=["api"])


# Auth endpoints
@router.post("/auth/register")
async def register(email: str, username: str, password: str, db: Session = Depends(get_db)):
    """Register endpoint"""
    from app.schemas.user import UserCreate
    user = UserCreate(email=email, username=username, password=password)
    return await auth_router.register(user, db)


@router.post("/auth/login")
async def login(email: str, password: str, db: Session = Depends(get_db)):
    """Login endpoint"""
    from app.schemas.user import UserLogin
    login_data = UserLogin(email=email, password=password)
    return await auth_router.login(login_data, db)


@router.get("/auth/me")
async def me(current_user: dict = Depends(get_current_user), db: Session = Depends(get_db)):
    """Get current user endpoint"""
    return await auth_router.me(current_user, db)
