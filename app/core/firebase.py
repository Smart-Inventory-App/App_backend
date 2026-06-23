import os, json
import firebase_admin
from firebase_admin import credentials, messaging
from app.core.config import settings

if not firebase_admin._apps:
    cred_dict = {
        "type": settings.FIREBASE_TYPE,
        "project_id": settings.FIREBASE_PROJECT_ID,
        "private_key_id": settings.FIREBASE_PRIVATE_KEY_ID,
        "private_key": settings.FIREBASE_PRIVATE_KEY.replace("\\n", "\n"),
        "client_email": settings.FIREBASE_CLIENT_EMAIL,
        "client_id": settings.FIREBASE_CLIENT_ID,
        "auth_uri": settings.FIREBASE_AUTH_URI,
        "token_uri": settings.FIREBASE_TOKEN_URI,
        "auth_provider_x509_cert_url": settings.FIREBASE_AUTH_PROVIDER_X509_CERT_URL,
        "client_x509_cert_url": settings.FIREBASE_CLIENT_X509_CERT_URL,
        "universe_domain": settings.FIREBASE_UNIVERSE_DOMAIN,
    }
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)

def send_push(token: str, title: str, body: str):
    message = messaging.Message(
        notification=messaging.Notification(title, body),
        token=token
    )
    return messaging.send(message)