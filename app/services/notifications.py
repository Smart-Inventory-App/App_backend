import logging

import httpx

logger = logging.getLogger(__name__)

NOTIFICATION_PATH = "/notification/send_notification"
SEND_TIMEOUT_SECONDS = 10.0

def notification_url(base_url: str) -> str:
    """URL completa del endpoint de envío a partir de la URL configurada.

    Acepta la base del servicio (`https://host`) y también la forma que traía el
    prefijo de la ruta (`https://host/notification`): apuntan al mismo servicio,
    y mezclarlas armaba `/notification/notification/send_notification`, un 404
    que nadie veía porque el envío es de mejor esfuerzo.
    """
    base = (base_url or "").rstrip("/")
    if base.endswith("/notification"):
        base = base[: -len("/notification")]
    return f"{base}{NOTIFICATION_PATH}"


class NotificationService:
    def __init__(self, api_url):
        self.api_url = api_url

    async def send_notification(
        self, user_token, title, body, user_email,
        kind=None, product_name=None, days=None, units=None, limit_days=None, daily_rate=None,
    ):
        """Pide el envío de un push y un email. Devuelve el status HTTP, o None si no hubo respuesta.

        Es asíncrono a propósito: se llama desde handlers `async` y desde el job
        de alertas, que corre en el mismo event loop que la API. Con un cliente
        bloqueante, un servicio de notificaciones lento frenaba a todos los
        usuarios mientras duraba el timeout.
        """
        payload = {
            "title": title,
            "body": body,
            "token": user_token,
            "email": user_email,
        }
        # Datos para que el mail explique el aviso (qué significa y qué hacer). Se mandan solo si hay: sin ellos el
        # servicio arma un mail simple con el título y el mensaje.
        extras = {
            "kind": kind, "product_name": product_name, "days": days, "units": units,
            "limit_days": limit_days, "daily_rate": daily_rate,
        }
        payload.update({key: value for key, value in extras.items() if value is not None})
        url = notification_url(self.api_url)
        try:
            async with httpx.AsyncClient(timeout=SEND_TIMEOUT_SECONDS) as client:
                response = await client.post(url, json=payload)
        except httpx.HTTPError as exc:
            logger.warning("No se pudo enviar la notificación a %s: %s", url, exc)
            return None

        if response.status_code >= 400:
            logger.warning("El servicio de notificaciones respondió %s en %s", response.status_code, url)
        return response.status_code
