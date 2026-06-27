import os, json
import firebase_admin
from firebase_admin import credentials, messaging
from app.core.config import settings

if not firebase_admin._apps:
    cred_dict = json.loads(settings.FIREBASE_CREDENTIALS)
    cred = credentials.Certificate(cred_dict)
    firebase_admin.initialize_app(cred)

def send_push(token: str, title: str, body: str):
    message = messaging.Message(
        notification=messaging.Notification(title, body),
        token=token
    )
    return messaging.send(message)