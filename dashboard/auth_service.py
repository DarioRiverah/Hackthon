"""
Modelo de usuario -- UN SOLO usuario por instalación (un solo rol, sin
multi-tenant), guardado como JSON simple en .secrets/user.json (mismo
directorio, mismo criterio de "nunca en texto plano para lo sensible",
que ya usa auth_crypto.py para la clave de encriptación local).

Guarda: username, hash de contraseña (werkzeug.security -- scrypt por
defecto en esta versión; no hace falta bcrypt aparte, werkzeug ya trae
un hash de contraseña adecuado sin dependencias nuevas) y,
opcionalmente, el patrón de manos (4 poses de 21 landmarks) ENCRIPTADO
con auth_crypto.py antes de tocar disco.
"""

import base64
import json
import os
from datetime import datetime, timezone

from werkzeug.security import check_password_hash, generate_password_hash

import auth_crypto

USER_PATH = os.path.join(auth_crypto.SECRETS_DIR, "user.json")


def user_exists() -> bool:
    return os.path.exists(USER_PATH)


def _load_user() -> dict | None:
    if not os.path.exists(USER_PATH):
        return None
    with open(USER_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_user(data: dict):
    auth_crypto.ensure_secrets_dir()
    with open(USER_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)


def create_user(username: str, password: str):
    """Crea la única cuenta de esta instalación -- falla si ya existe
    una (un solo usuario, ver tarea). Usado solo en el registro inicial
    (primer arranque, ver /login GET con first_run=True)."""
    if user_exists():
        raise ValueError("Ya existe una cuenta en esta instalación.")
    _save_user({
        "username": username,
        "password_hash": generate_password_hash(password),
        "hand_pattern_enc": None,
        "created_at": datetime.now(timezone.utc).isoformat(),
    })


def verify_password(username: str, password: str) -> bool:
    user = _load_user()
    if not user or user["username"] != username:
        return False
    return check_password_hash(user["password_hash"], password)


def set_password(new_password: str):
    user = _load_user()
    if not user:
        raise ValueError("No hay ninguna cuenta creada todavía.")
    user["password_hash"] = generate_password_hash(new_password)
    _save_user(user)


def get_username() -> str | None:
    user = _load_user()
    return user["username"] if user else None


def has_hand_pattern() -> bool:
    user = _load_user()
    return bool(user and user.get("hand_pattern_enc"))


def set_hand_pattern(poses: list):
    """poses: lista de 4 vectores de 21 landmarks (x, y, z) YA
    normalizados por el frontend -- se serializan a JSON y se encriptan
    (auth_crypto.encrypt_bytes, Fernet) antes de guardar, nunca en texto
    plano en disco."""
    user = _load_user()
    if not user:
        raise ValueError("No hay ninguna cuenta creada todavía.")
    raw = json.dumps(poses).encode("utf-8")
    encrypted = auth_crypto.encrypt_bytes(raw)
    user["hand_pattern_enc"] = base64.b64encode(encrypted).decode("ascii")
    _save_user(user)


def get_hand_pattern() -> list | None:
    """None si no hay patrón guardado, o si no se pudo desencriptar --
    mismo criterio de degradación elegante que auth_crypto.decrypt_bytes:
    el llamador (login por patrón) lo trata igual que "sin patrón
    guardado todavía", nunca truena."""
    user = _load_user()
    if not user or not user.get("hand_pattern_enc"):
        return None
    encrypted = base64.b64decode(user["hand_pattern_enc"])
    raw = auth_crypto.decrypt_bytes(encrypted)
    if raw is None:
        return None
    return json.loads(raw.decode("utf-8"))
