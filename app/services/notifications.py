import requests

from app.models.product import Product
from app.models.user import User
from sqlalchemy.orm import Session

class NotificationService:
    def __init__(self, api_url):
        self.api_url = api_url

    def send_notification(self, user_token, title, body, user_email):
        payload = {
            'title': title,
            'body': body,
            'token': user_token,
            'email': user_email
        }
        try:
            response = requests.post(f"{self.api_url}/send_notification", json=payload, timeout=10)
            return response.status_code
        except requests.RequestException:
            # El push es best-effort: que falle no debe romper la operación del usuario
            return None
