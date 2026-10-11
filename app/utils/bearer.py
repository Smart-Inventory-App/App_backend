from fastapi import HTTPException, Request, status

def get_bearer_token(request: Request) -> str:
    """
    Devuelve el token tal como llegó: `get_current_user` da el payload 
    decodificado, que sirve para autorizar. Para hablar con otro servicio en 
    nombre del usuario hace falta el token original: ocr_service y el 
    storage validan el mismo JWT del servicio Auth, así que reenviarlo evita 
    inventar un token de servicio.
    """
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")

    if scheme.lower() != "bearer" or not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o ausente",
        )

    return token
