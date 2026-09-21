from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # API
    API_TITLE: str = "TPP API"
    API_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str

    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/tpp_db"

    # CORS — comma-separated in .env; stored as plain str, exposed as list via property
    ALLOWED_ORIGINS_STR: str = "http://localhost:3000,http://localhost:8081,http://localhost:8100,http://localhost:19000"

    @property
    def ALLOWED_ORIGINS(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS_STR.split(",") if o.strip()]

    # JWT — shared secret with Auth service
    JWT_SECRET: str
    JWT_ALGORITHM: str = "HS256"

    # Email (SMTP) for recovery codes
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = "noreply@smartinventory.com"

    # Internal service auth (used by ML service)
    INTERNAL_SERVICE_TOKEN: str

    # ML service URL for smart alerts
    ML_SERVICE_URL: str = ""

    # Firebase
    FIREBASE_CREDENTIALS: str = ""

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    #Notification Service
    NOTIFICATION_SERVICE_URL: str = "http://localhost:8010/notification"

    class Config:
        env_file = ".env"
        case_sensitive = True
        extra = "ignore"


settings = Settings()
