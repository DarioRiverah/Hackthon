"""
Autenticación: login por contraseña o por patrón de manos (4 poses),
emisión de la cookie de sesión (JWT, ver jwt_service.py), y la página de
Configuración para cambiar la contraseña o volver a registrar el
patrón -- un solo usuario por instalación (ver auth_service.py).

PUBLIC_AUTH_ENDPOINTS es la lista EXPLÍCITA de endpoints de este
blueprint que NO requieren sesión (login y registro inicial) -- se
importa desde dashboard/app.py para el chequeo global de autenticación.
A propósito no es "todo el blueprint auth": /settings y sus dos POST
viven acá también pero SÍ deben quedar protegidos, así que no alcanza
con eximir el blueprint entero.
"""

from flask import Blueprint, g, jsonify, render_template, request

import auth_service
import jwt_service
from hand_pattern import POSE_COUNT, compare_pattern
from routes.main_routes import _sidebar_context

auth_bp = Blueprint("auth", __name__)

PUBLIC_AUTH_ENDPOINTS = {
    "auth.login",
    "auth.register_account",
    "auth.login_password",
    "auth.login_pattern",
    "auth.logout",
}

GENERIC_PATTERN_ERROR = "Patrón no reconocido, intenta de nuevo o usa tu contraseña."


def _login_response(username: str):
    resp = jsonify({"ok": True})
    token = jwt_service.issue_token(username)
    resp.set_cookie(
        jwt_service.COOKIE_NAME, token,
        httponly=True, samesite="Lax",
        max_age=jwt_service.JWT_EXPIRY_HOURS * 3600,
    )
    return resp


@auth_bp.route("/login")
def login():
    if not auth_service.user_exists():
        return render_template("login.html", first_run=True, has_pattern=False)
    return render_template("login.html", first_run=False, has_pattern=auth_service.has_hand_pattern())


@auth_bp.route("/login/register-account", methods=["POST"])
def register_account():
    """Crea la ÚNICA cuenta de esta instalación -- solo funciona la
    primera vez (si ya existe una cuenta, se rechaza; para cambiar la
    contraseña de una cuenta existente ya autenticada, ver
    /settings/password más abajo)."""
    if auth_service.user_exists():
        return jsonify({"ok": False, "error": "Ya existe una cuenta en esta instalación."}), 400
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not username:
        return jsonify({"ok": False, "error": "El usuario no puede estar vacío."}), 400
    if len(password) < 8:
        return jsonify({"ok": False, "error": "La contraseña debe tener al menos 8 caracteres."}), 400
    auth_service.create_user(username, password)
    return _login_response(username)


@auth_bp.route("/login/password", methods=["POST"])
def login_password():
    data = request.get_json(force=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    if not auth_service.verify_password(username, password):
        return jsonify({"ok": False, "error": "Usuario o contraseña incorrectos."}), 401
    return _login_response(username)


@auth_bp.route("/login/pattern", methods=["POST"])
def login_pattern():
    """Recibe la secuencia de 4 poses del intento de login, desencripta
    el patrón guardado y compara EN ORDEN (ver hand_pattern.compare_pattern).
    Mensaje de error siempre genérico -- nunca revela cuál de las 4
    poses falló, ni si el problema fue "no hay patrón guardado" vs "no
    coincidió", para no darle pistas a un intento de fuerza bruta."""
    data = request.get_json(force=True) or {}
    poses = data.get("poses")
    stored = auth_service.get_hand_pattern()
    username = auth_service.get_username()
    if not stored or not username or not compare_pattern(poses, stored):
        return jsonify({"ok": False, "error": GENERIC_PATTERN_ERROR}), 401
    return _login_response(username)


@auth_bp.route("/logout", methods=["POST"])
def logout():
    resp = jsonify({"ok": True})
    resp.delete_cookie(jwt_service.COOKIE_NAME)
    return resp


@auth_bp.route("/settings")
def settings():
    return render_template(
        "settings.html",
        username=auth_service.get_username(),
        has_pattern=auth_service.has_hand_pattern(),
        **_sidebar_context(None),
    )


@auth_bp.route("/settings/password", methods=["POST"])
def settings_password():
    data = request.get_json(force=True) or {}
    current_password = data.get("current_password") or ""
    new_password = data.get("new_password") or ""
    if not auth_service.verify_password(g.current_user, current_password):
        return jsonify({"ok": False, "error": "La contraseña actual no es correcta."}), 400
    if len(new_password) < 8:
        return jsonify({"ok": False, "error": "La nueva contraseña debe tener al menos 8 caracteres."}), 400
    auth_service.set_password(new_password)
    return jsonify({"ok": True})


@auth_bp.route("/settings/pattern", methods=["POST"])
def settings_pattern():
    data = request.get_json(force=True) or {}
    poses = data.get("poses")
    if not isinstance(poses, list) or len(poses) != POSE_COUNT:
        return jsonify({"ok": False, "error": f"Se necesitan las {POSE_COUNT} poses."}), 400
    auth_service.set_hand_pattern(poses)
    return jsonify({"ok": True})
