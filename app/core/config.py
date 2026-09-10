from pydantic_settings import BaseSettings
from typing import List, Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # API
    API_TITLE: str = "TPP API"
    API_VERSION: str = "1.0.0"
    DEBUG: bool = False
    SECRET_KEY: str = "your-secret-key-change-in-production"

    # Database
    DATABASE_URL: str = "postgresql://user:password@localhost:5432/tpp_db"

    # CORS — comma-separated in .env; stored as plain str, exposed as list via property
    ALLOWED_ORIGINS_STR: str = "http://localhost:3000,http://localhost:8081,http://localhost:8100,http://localhost:19000"

    @property
    def ALLOWED_ORIGINS(self) -> List[str]:
        return [o.strip() for o in self.ALLOWED_ORIGINS_STR.split(",") if o.strip()]

    # JWT — shared secret with Auth service
    JWT_SECRET: str = "dev-secret-change-in-prod"
    JWT_ALGORITHM: str = "HS256"

    # Email (SMTP) for recovery codes
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = "noreply@smartinventory.com"

    # Internal service auth (used by ML service)
    INTERNAL_SERVICE_TOKEN: str = "change-this-internal-token"

    # ML service URL for smart alerts
    ML_SERVICE_URL: str = ""

    # OCR module service URL and timeout
    OCR_SERVICE_URL: str = ""
    # Cubre la subida de la foto y el encolado, no el reconocimiento. Tiene que
    # ser mayor que el timeout con el que ocr_service sube al storage (30 s): si
    # cortamos antes, la imagen temporal queda subida y sin nadie que la borre.
    OCR_TIMEOUT_SECONDS: float = 60.0

    # Firebase
    FIREBASE_CREDENTIALS: str

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
