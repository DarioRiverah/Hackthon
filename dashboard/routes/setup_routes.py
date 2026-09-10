"""
Asistente de configuración: subir video, recortar (opcional), calibrar
zonas, procesar. Usa flask.session SOLO para recordar qué video está
"en curso" para esta tienda entre pasos (estado transitorio real) --
todo lo demás (zonas calibradas, resultados) ya vive en archivos.
"""

import os
import sys

from flask import Blueprint, render_template, request, redirect, url_for, session, flash

import store_service
import tienda_service
import video_utils

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "pipeline"))
import device_utils

setup_bp = Blueprint("setup", __name__, url_prefix="/setup")


def _sidebar_context(store_name):
    context = {
        "all_stores": store_service.list_all_stores(),
        "current_store": store_name,
        "store_state": store_service.get_store_state(store_name),
    }
    context.update(tienda_service.build_sidebar_context(camara_id=store_name))
    return context


def _session_key(store_name):
    return f"setup_video_{store_name}"


@setup_bp.route("")
def wizard():
    store_name = request.args.get("store", "").strip()
    if not store_name:
        return redirect(url_for("main.store_home"))

    video_path = session.get(_session_key(store_name))
    duration = video_utils.get_video_duration(video_path) if video_path and os.path.exists(video_path) else 0

    video_basename = os.path.splitext(os.path.basename(video_path))[0] if video_path else ""
    tracks_csv_path = f"data/processed/tracks_{video_basename}.csv" if video_basename else ""
    has_heat_preview = bool(tracks_csv_path) and os.path.exists(tracks_csv_path)
    zones_exist = store_service.get_store_state(store_name)["has_zones"]

    context = _sidebar_context(store_name)
    context.update({
        "video_path": video_path,
        "duration": duration,
        "has_heat_preview": has_heat_preview,
        "zones_exist": zones_exist,
        "gpu_info": device_utils.get_gpu_info(),
    })
    return render_template("setup.html", **context)


@setup_bp.route("/upload", methods=["POST"])
def upload():
    store_name = request.form.get("store", "").strip()
    if not store_name:
        return redirect(url_for("main.store_home"))

    uploaded_file = request.files.get("video")
    if not uploaded_file or uploaded_file.filename == "":
        flash("Sube un video para continuar.")
        return redirect(url_for("setup.wizard", store=store_name))

    os.makedirs("data/raw", exist_ok=True)
    # Namespaced por cámara (NO el nombre de archivo original) -- dos
    # cámaras distintas subidas desde archivos locales con el mismo
    # nombre (ej. dos videos de prueba llamados igual) NO deben terminar
    # compartiendo el mismo archivo físico en disco. Ver
    # docs/architecture.md sección 33.
    _, ext = os.path.splitext(uploaded_file.filename)
    raw_video_path = os.path.join("data/raw", f"{store_name}{ext}")
    uploaded_file.save(raw_video_path)

    duration = video_utils.get_video_duration(raw_video_path)
    if duration <= 0:
        flash("No se pudo leer la duración del video. ¿Es un archivo de video válido?")
        return redirect(url_for("setup.wizard", store=store_name))

    session[_session_key(store_name)] = raw_video_path
    return redirect(url_for("setup.wizard", store=store_name))


@setup_bp.route("/use-trimmed", methods=["POST"])
def use_trimmed():
    """Tras recortar (ver /api/store/<name>/trim), el frontend llama
    aquí para que el paso de calibración/procesamiento use el video
    recortado en vez del original."""
    store_name = request.form.get("store", "").strip()
    trimmed_path = request.form.get("trimmed_path", "").strip()
    if store_name and trimmed_path and os.path.exists(trimmed_path):
        session[_session_key(store_name)] = trimmed_path
    return redirect(url_for("setup.wizard", store=store_name))


@setup_bp.route("/reset", methods=["POST"])
def reset():
    store_name = request.form.get("store", "").strip()
    session.pop(_session_key(store_name), None)
    return redirect(url_for("setup.wizard", store=store_name))
