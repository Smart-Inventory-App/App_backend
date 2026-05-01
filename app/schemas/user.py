from pydantic import BaseModel, EmailStr
from datetime import datetime
from typing import Optional


class UserBase(BaseModel):
    """Base user schema"""
    email: EmailStr
    username: str


class UserCreate(UserBase):
    """User creation schema"""
    password: str


class UserLogin(BaseModel):
    """User login schema"""
    email: EmailStr
    password: str


class UserResponse(UserBase):
    """User response schema"""
    id: int
    created_at: datetime
    
    class Config:
        from_attributes = True


class TokenResponse(BaseModel):
    """Token response schema"""
    access_token: str
    token_type: str = "bearer"


class TransactionBase(BaseModel):
    """Base transaction schema"""
    amount: int
    description: str


class TransactionResponse(TransactionBase):
    """Transaction response schema"""
    id: int
    user_id: int
    created_at: datetime
    
    class Config:
        from_attributes = True
