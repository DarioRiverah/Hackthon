"""
Encriptación local simétrica -- reconstruida a partir del mismo
mecanismo que usaba el guardado local de la API key de Groq (retirado
del proyecto por completo, ver docs/architecture.md secciones 20/21/38,
así que no queda ningún módulo que reutilizar tal cual): Fernet
(cryptography, encriptación simétrica estándar), con una clave local
aleatoria generada la primera vez que hace falta y guardada en
.secrets/encryption.key -- NUNCA en el repositorio.

Mismo alcance de seguridad que entonces, sin adornos: esto protege
contra exposición ACCIDENTAL (copiar/compartir el proyecto sin querer,
ver el patrón guardado como texto plano). NO protege contra alguien con
acceso completo a esta misma computadora -- la clave vive junto a lo
que desbloquea. La carpeta .secrets/ nunca debe copiarse ni compartirse
junto con el resto del proyecto.
"""

import os

from cryptography.fernet import Fernet

SECRETS_DIR = ".secrets"
ENCRYPTION_KEY_PATH = os.path.join(SECRETS_DIR, "encryption.key")


def ensure_secrets_dir():
    """Crea .secrets/ si hace falta, con su propio .gitignore (ignora
    todo lo de adentro) y una advertencia legible -- mismo patrón que
    usaba el guardado de la key de Groq."""
    os.makedirs(SECRETS_DIR, exist_ok=True)
    gitignore_path = os.path.join(SECRETS_DIR, ".gitignore")
    if not os.path.exists(gitignore_path):
        with open(gitignore_path, "w", encoding="utf-8") as f:
            f.write("*\n")
    warn_path = os.path.join(SECRETS_DIR, "NO_COMPARTIR.txt")
    if not os.path.exists(warn_path):
        with open(warn_path, "w", encoding="utf-8") as f:
            f.write(
                "Esta carpeta contiene claves y credenciales locales (cuenta de "
                "usuario, patron de manos encriptado, clave de firma de sesion).\n"
                "NUNCA la copies, respaldes ni compartas junto con el resto del "
                "proyecto -- ni siquiera con alguien de confianza.\n"
            )


def _get_or_create_fernet_key() -> bytes:
    ensure_secrets_dir()
    if os.path.exists(ENCRYPTION_KEY_PATH):
        with open(ENCRYPTION_KEY_PATH, "rb") as f:
            return f.read()
    key = Fernet.generate_key()
    with open(ENCRYPTION_KEY_PATH, "wb") as f:
        f.write(key)
    return key


def encrypt_bytes(data: bytes) -> bytes:
    return Fernet(_get_or_create_fernet_key()).encrypt(data)


def decrypt_bytes(token: bytes) -> bytes | None:
    """None si no se pudo desencriptar (clave faltante/corrupta, token
    corrupto) -- nunca lanza, para que el llamador pueda degradar con
    elegancia (ej. "no hay patrón guardado, usa tu contraseña") en vez
    de que el dashboard truene."""
    try:
        return Fernet(_get_or_create_fernet_key()).decrypt(token)
    except Exception:
        return None
