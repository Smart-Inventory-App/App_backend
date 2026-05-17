"""Keycloak service — wraps Keycloak REST API so the app uses our own UI."""
import logging
import random
import smtplib
from datetime import datetime, timedelta, timezone
from email.mime.text import MIMEText
from typing import Optional

import httpx
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.config import settings

logger = logging.getLogger(__name__)


class KeycloakService:
    @property
    def _token_url(self) -> str:
        return f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token"

    @property
    def _introspect_url(self) -> str:
        return f"{settings.KEYCLOAK_URL}/realms/{settings.KEYCLOAK_REALM}/protocol/openid-connect/token/introspect"

    @property
    def _admin_users_url(self) -> str:
        return f"{settings.KEYCLOAK_URL}/admin/realms/{settings.KEYCLOAK_REALM}/users"

    # ------------------------------------------------------------------ admin token
    async def _get_admin_token(self) -> str:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                f"{settings.KEYCLOAK_URL}/realms/master/protocol/openid-connect/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": settings.KEYCLOAK_ADMIN_CLIENT_ID,
                    "client_secret": settings.KEYCLOAK_ADMIN_CLIENT_SECRET,
                },
                timeout=10.0,
            )
            try:
                resp.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error("Could not get admin token: %s", exc.response.text)
                raise HTTPException(status_code=503, detail="Auth service unavailable")
            return resp.json()["access_token"]

    # ------------------------------------------------------------------ login
    async def login(self, email: str, password: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._token_url,
                data={
                    "grant_type": "password",
                    "client_id": settings.KEYCLOAK_CLIENT_ID,
                    "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
                    "username": email,
                    "password": password,
                },
                timeout=10.0,
            )
            if resp.status_code in (400, 401):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="INVALID_CREDENTIALS",
                )
            resp.raise_for_status()
            data = resp.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "token_type": "bearer",
            }

    # ------------------------------------------------------------------ register
    async def register(self, email: str, password: str) -> None:
        admin_token = await self._get_admin_token()
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._admin_users_url,
                headers={"Authorization": f"Bearer {admin_token}"},
                json={
                    "email": email,
                    "username": email,
                    "enabled": True,
                    "emailVerified": True,
                    "credentials": [
                        {"type": "password", "value": password, "temporary": False}
                    ],
                },
                timeout=10.0,
            )
            if resp.status_code == 409:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="EMAIL_TAKEN",
                )
            resp.raise_for_status()

    # ------------------------------------------------------------------ email check
    async def email_exists(self, email: str) -> bool:
        admin_token = await self._get_admin_token()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                self._admin_users_url,
                headers={"Authorization": f"Bearer {admin_token}"},
                params={"email": email, "exact": "true"},
                timeout=10.0,
            )
            resp.raise_for_status()
            return len(resp.json()) > 0

    # ------------------------------------------------------------------ get user
    async def get_user_id_by_email(self, email: str) -> Optional[str]:
        admin_token = await self._get_admin_token()
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                self._admin_users_url,
                headers={"Authorization": f"Bearer {admin_token}"},
                params={"email": email, "exact": "true"},
                timeout=10.0,
            )
            resp.raise_for_status()
            users = resp.json()
            return users[0]["id"] if users else None

    # ------------------------------------------------------------------ reset password
    async def reset_password(self, user_id: str, new_password: str) -> None:
        admin_token = await self._get_admin_token()
        async with httpx.AsyncClient() as client:
            resp = await client.put(
                f"{self._admin_users_url}/{user_id}/reset-password",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"type": "password", "value": new_password, "temporary": False},
                timeout=10.0,
            )
            if resp.status_code == 400:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="PASSWORD_POLICY_VIOLATION",
                )
            resp.raise_for_status()

    # ------------------------------------------------------------------ validate token
    async def validate_token(self, token: str) -> dict:
        async with httpx.AsyncClient() as client:
            resp = await client.post(
                self._introspect_url,
                data={
                    "token": token,
                    "client_id": settings.KEYCLOAK_CLIENT_ID,
                    "client_secret": settings.KEYCLOAK_CLIENT_SECRET,
                },
                timeout=10.0,
            )
            resp.raise_for_status()
            data = resp.json()
            if not data.get("active"):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Token inválido o expirado",
                )
            return data

    # ------------------------------------------------------------------ recovery codes
    @staticmethod
    def generate_recovery_code() -> str:
        return "".join(random.choices("0123456789", k=6))

    def send_recovery_email(self, email: str, code: str) -> None:
        """Send recovery code via SMTP. Falls back to console log in dev."""
        if not settings.SMTP_USER:
            logger.warning("SMTP not configured — recovery code for %s: %s", email, code)
            return

        msg = MIMEText(
            f"Tu código de recuperación de Smart Inventory es: {code}\n\n"
            "Este código expira en 1 hora. Si no solicitaste esto, ignorá este mensaje."
        )
        msg["Subject"] = "Código de recuperación — Smart Inventory"
        msg["From"] = settings.EMAIL_FROM
        msg["To"] = email

        try:
            with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
                server.starttls()
                server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
                server.sendmail(settings.EMAIL_FROM, [email], msg.as_string())
        except Exception as exc:
            logger.error("Failed to send recovery email: %s", exc)


keycloak = KeycloakService()
