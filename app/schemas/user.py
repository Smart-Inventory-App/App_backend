from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Optional


class UserRegister(BaseModel):
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str
    firebase_token: str


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: Optional[str] = None
    token_type: str = "bearer"


class EmailCheckRequest(BaseModel):
    email: EmailStr


class EmailCheckResponse(BaseModel):
    exists: bool


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class VerifyCodeRequest(BaseModel):
    email: EmailStr
    code: str


class ResetTokenResponse(BaseModel):
    reset_token: str


class ResetPasswordRequest(BaseModel):
    reset_token: str
    new_password: str


class SocialCallbackRequest(BaseModel):
    code: str
    redirect_uri: str
    code_verifier: Optional[str] = None


class ProfileResponse(BaseModel):
    sub: str
    email: Optional[str] = None
    username: Optional[str] = None
    firstName: Optional[str] = None
    lastName: Optional[str] = None
    coverageDaysThreshold: int
    expiryDaysThreshold: int
    alertCheckHour: int


class ProfileUpdate(BaseModel):
    firstName: str
    lastName: str
    username: Optional[str] = None
    coverageDaysThreshold: Optional[int] = Field(None, gt=0)
    expiryDaysThreshold: Optional[int] = Field(None, gt=0)
    alertCheckHour: Optional[int] = Field(None, ge=0, le=23)


# Keep legacy schemas so existing code that imports them doesn't break
class UserBase(BaseModel):
    email: EmailStr
    username: str


class UserCreate(UserBase):
    password: str


class UserResponse(UserBase):
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class TransactionBase(BaseModel):
    amount: int
    description: str


class TransactionResponse(TransactionBase):
    id: int
    user_id: int
    created_at: datetime

    class Config:
        from_attributes = True
