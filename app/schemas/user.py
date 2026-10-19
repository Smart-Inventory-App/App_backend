from pydantic import BaseModel, EmailStr, Field
from datetime import datetime
from typing import Literal, Optional

UserType = Literal["individuo", "comercio"]


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
    alertCheckHour: int = Field(description="Hora UTC (0 a 23) del chequeo diario de alertas")
    userType: UserType


# Límites del perfil: el nombre, el apellido y el usuario llegan a 20 caracteres; los días de las alertas
# van de 2 a 90. La app muestra los mismos números, así que se cambian en los dos lados a la vez.
PROFILE_TEXT_MAX = 20
ALERT_DAYS_MIN = 2
ALERT_DAYS_MAX = 90


class ProfileUpdate(BaseModel):
    firstName: str = Field(max_length=PROFILE_TEXT_MAX)
    lastName: str = Field(max_length=PROFILE_TEXT_MAX)
    username: Optional[str] = Field(None, max_length=PROFILE_TEXT_MAX)
    coverageDaysThreshold: Optional[int] = Field(None, ge=ALERT_DAYS_MIN, le=ALERT_DAYS_MAX)
    expiryDaysThreshold: Optional[int] = Field(None, ge=ALERT_DAYS_MIN, le=ALERT_DAYS_MAX)
    alertCheckHour: Optional[int] = Field(None, ge=0, le=23, description="Hora UTC (0 a 23) del chequeo diario de alertas")
    userType: Optional[UserType] = None

class NotificationToken(BaseModel):
    token: str

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
