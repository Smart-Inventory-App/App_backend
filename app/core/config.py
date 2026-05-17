from pydantic_settings import BaseSettings
from typing import List


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

    # JWT (used for short-lived password-reset tokens)
    JWT_ALGORITHM: str = "HS256"
    JWT_EXPIRATION_HOURS: int = 24

    # Keycloak
    KEYCLOAK_URL: str = "http://localhost:8080"
    KEYCLOAK_REALM: str = "tpp"
    KEYCLOAK_CLIENT_ID: str = "tpp-app"
    KEYCLOAK_CLIENT_SECRET: str = ""
    # Admin access — uses master-realm admin-cli (password grant)
    KEYCLOAK_ADMIN_USERNAME: str = "admin"
    KEYCLOAK_ADMIN_PASSWORD: str = "admin"

    # Email (SMTP) for recovery codes
    SMTP_HOST: str = "smtp.gmail.com"
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    EMAIL_FROM: str = "noreply@smartinventory.com"

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()
