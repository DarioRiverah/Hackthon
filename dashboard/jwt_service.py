"""
Emisión y verificación de JWT de sesión -- firmados con una clave local
aleatoria propia (.secrets/jwt_secret.key, generada la primera vez que
hace falta, mismo patrón que auth_crypto.py para la clave de
encriptación) en vez de reusar app.secret_key: ese valor por defecto es
un string fijo hardcodeado en el repo (dashboard/app.py) pensado solo
para mensajes flash, no para firmar credenciales de sesión.

El JWT viaja en una cookie HttpOnly (ver routes/auth_routes.py) -- el
frontend nunca necesita leerlo ni mandarlo a mano, el navegador lo
adjunta solo en cada request al mismo origen.
"""

import os
from datetime import datetime, timedelta, timezone

import jwt

import auth_crypto

JWT_SECRET_PATH = os.path.join(auth_crypto.SECRETS_DIR, "jwt_secret.key")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_HOURS = 12
COOKIE_NAME = "auth_token"


def _get_or_create_secret() -> str:
    auth_crypto.ensure_secrets_dir()
    if os.path.exists(JWT_SECRET_PATH):
        with open(JWT_SECRET_PATH, "r", encoding="utf-8") as f:
            return f.read().strip()
    secret = os.urandom(32).hex()
    with open(JWT_SECRET_PATH, "w", encoding="utf-8") as f:
        f.write(secret)
    return secret


def issue_token(username: str) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": username, "iat": now, "exp": now + timedelta(hours=JWT_EXPIRY_HOURS)}
    return jwt.encode(payload, _get_or_create_secret(), algorithm=JWT_ALGORITHM)


def verify_token(token: str | None) -> str | None:
    """Devuelve el username si el token es válido y no expiró, None en
    cualquier otro caso (falta, corrupto, expirado, firma inválida) --
    nunca lanza, para que el before_request de app.py pueda hacer un
    chequeo simple sí/no."""
    if not token:
        return None
    try:
        payload = jwt.decode(token, _get_or_create_secret(), algorithms=[JWT_ALGORITHM])
        return payload.get("sub")
    except jwt.PyJWTError:
        return None
