"""
Endpoints JSON/AJAX + servido de archivos generados (imágenes, video,
PDF) -- todo lo que el frontend consume vía fetch() en vez de una
recarga completa de página.
"""

import io
import os
import sys

from flask import Blueprint, jsonify, request, send_file, abort, Response

import pandas as pd

import store_service
import tienda_service
import layout_view
import simulator
import job_manager
import video_utils
import calibration_service
import data_management_service
import storytelling
import trends
from report_generator import generate_pdf_report

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "pipeline"))

api_bp = Blueprint("api", __name__, url_prefix="/api")

# Directorios desde los que SÍ está permitido servir archivos -- cualquier
# ruta fuera de estos se rechaza, para no exponer el filesystem entero
# a través de este endpoint genérico.
_ALLOWED_MEDIA_DIRS = ("data/output", "data/processed", "data/raw", "data/history")


@api_bp.route("/media/<path:relpath>")
def media(relpath):
    """Sirve un archivo generado por el pipeline (heatmap, video de
    verificación, frame de referencia) directo desde disco."""
    normalized = relpath.replace("\\", "/")
    if not any(normalized.startswith(d + "/") for d in _ALLOWED_MEDIA_DIRS):
        abort(403)
    if ".." in normalized.split("/"):
        abort(403)
    if not os.path.exists(normalized):
        abort(404)
    return send_file(os.path.abspath(normalized))


@api_bp.route("/store/<store_name>/layout-plot.png")
def layout_plot(store_name):
    """El plano colorea cada zona según su tráfico -- si se pasa
    ?fecha=YYYY-MM-DD, usa la instantánea archivada de esa fecha (ver
    docs/architecture.md sección 34) en vez de los datos en vivo, para
    que el plano de la vista histórica muestre el tráfico REAL de esa
    fecha y no el actual."""
    fecha = request.args.get("fecha", "").strip()
    if fecha:
        summary_df, zones_config, _ = store_service.load_archived_store_data(store_name, fecha)
    else:
        summary_df, zones_config, _ = store_service.load_store_data(store_name)
    if summary_df is None:
        abort(404)

    fig = layout_view.render_layout_plot(
        zones_config["zones"], summary_df,
        zones_config["frame_width"], zones_config["frame_height"],
    )
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=110)
    buf.seek(0)
    import matplotlib.pyplot as plt
    plt.close(fig)
    return send_file(buf, mimetype="image/png")


@api_bp.route("/store/<store_name>/report.pdf")
def report_pdf(store_name):
    """Arma TODO el contexto que report_generator.py necesita para el
    reporte ampliado (ver docs/architecture.md) -- cada pieza viene de
    una función YA EXISTENTE en otro módulo (storytelling, trends,
    tienda_service), igual que ya hace _build_results_context() en
    main_routes.py para la página de resultados. report_generator.py
    se queda "tonto" a propósito: solo ensambla lo que se le pasa, no
    va a buscar nada al filesystem por su cuenta."""
    summary_df, zones_config, interaction_df = store_service.load_store_data(store_name)
    if summary_df is None:
        abort(404)

    classifications = layout_view.classify_zones(summary_df)
    video_ref = zones_config.get("video_reference", "")
    video_basename = os.path.splitext(os.path.basename(video_ref))[0] if video_ref else ""

    # Mismas 3 rutas/etiquetas que ya arma main_routes.py:results() para
    # la pestaña Mapas -- no se reinventan acá.
    heatmap_paths = {}
    if video_basename:
        candidatos = {
            "Flujo (tráfico corporal)": f"data/output/heatmap_{video_basename}.png",
            "Interacción (mano)": f"data/output/heatmap_manos_{video_basename}.png",
            "Trayectorias (espagueti)": f"data/output/spaghetti_{video_basename}.png",
        }
        heatmap_paths = {label: path for label, path in candidatos.items() if os.path.exists(path)}

    # "Plano de la tienda" -- la pestaña Mapas del dashboard la muestra
    # PRIMERO, junto a los heatmaps (ver templates/results.html), pero el
    # PDF nunca la incluía porque /api/store/<...>/layout-plot.png la
    # genera al vuelo (BytesIO, sin tocar disco). Se renderiza con la
    # MISMA función (layout_view.render_layout_plot) y esta vez sí se
    # guarda a disco para que report_generator.py pueda incrustarla como
    # una imagen más -- reutiliza _fitted_image() y su límite de tamaño,
    # nada de lógica nueva de layout ahí.
    import matplotlib.pyplot as plt
    layout_plot_path = f"data/output/layout_plot_{store_name}.png"
    fig = layout_view.render_layout_plot(
        zones_config["zones"], summary_df,
        zones_config["frame_width"], zones_config["frame_height"],
    )
    fig.savefig(layout_plot_path, format="png", dpi=110)
    plt.close(fig)
    heatmap_paths = {"Plano de la tienda": layout_plot_path, **heatmap_paths}

    # Resumen narrado agregado (Historia) -- mismo camino que ya usa
    # main_routes.py: cargar los eventos crudos y armar zone_labels
    # desde zones_config, no desde summary_df (zones_config es la
    # fuente de verdad de qué zonas existen, summary_df solo trae las
    # que tuvieron al menos una visita).
    zone_events_df, interaction_events_df = storytelling.load_events(store_name)
    zone_labels = {z["id"]: z["label"] for z in zones_config["zones"]}
    story = storytelling.build_story(zone_events_df, interaction_events_df, zone_labels)
    narrative = story["narrative"] if story["has_data"] else None

    # Contexto de tienda -- solo se menciona si la cámara pertenece a
    # una tienda con MÁS de una cámara (una tienda de 1 sola cámara no
    # necesita aclarar "1 de 1").
    tienda_context = None
    tienda_id = tienda_service.find_tienda_de_camara(store_name)
    if tienda_id:
        tienda = tienda_service.get_tienda(tienda_id)
        camaras = tienda_service.get_camaras_de_tienda(tienda_id)
        if tienda and len(camaras) > 1:
            tienda_context = {"tienda_label": tienda.get("label", tienda_id), "n_camaras": len(camaras)}

    # Tendencia -- se omite del todo si hay menos de 2 fechas
    # archivadas (has_enough_dates=False) o si por alguna razón la
    # comparación no produjo tarjetas.
    trends_data = trends.get_trends_data(store_name)
    if not trends_data.get("has_enough_dates") or trends_data.get("same_dates") or not trends_data.get("cards"):
        trends_data = None

    fecha_referencia = tienda_service.get_camara_referencia(store_name).get("fecha_referencia")

    report_path = f"data/output/reporte_{store_name}.pdf"
    generate_pdf_report(
        store_name, summary_df, interaction_df, report_path,
        heatmap_paths=heatmap_paths, classifications=classifications,
        narrative=narrative, tienda_context=tienda_context,
        trends_data=trends_data, fecha_referencia=fecha_referencia,
    )
    return send_file(os.path.abspath(report_path), as_attachment=True,
                      download_name=f"reporte_{store_name}.pdf")


@api_bp.route("/store/<store_name>/simulate", methods=["POST"])
def simulate(store_name):
    data = request.get_json(force=True)
    from_id, to_id = data.get("from_id"), data.get("to_id")
    if not from_id or not to_id:
        return jsonify({"ok": False, "error": "Faltan zona de origen y/o destino."}), 400

    summary_df, _, interaction_df = store_service.load_store_data(store_name)
    if summary_df is None:
        return jsonify({"ok": False, "error": "No se encontraron datos de esta tienda."}), 404

    result = simulator.run_simulation(summary_df, interaction_df, from_id, to_id)
    return jsonify(result)


@api_bp.route("/store/<store_name>/simulate/recommend", methods=["POST"])
def simulate_recommend(store_name):
    """Dado solo el origen, prueba TODAS las demás zonas de la cámara
    como destino (reutilizando simulator.run_simulation() por dentro de
    simulator.recommend_best_destination()) y devuelve la de mejor
    cambio_pct -- o, si ninguna mejora, un error honesto en vez de una
    recomendación forzada."""
    data = request.get_json(force=True)
    from_id = data.get("from_id")
    if not from_id:
        return jsonify({"ok": False, "error": "Falta la zona de origen."}), 400

    summary_df, _, interaction_df = store_service.load_store_data(store_name)
    if summary_df is None:
        return jsonify({"ok": False, "error": "No se encontraron datos de esta tienda."}), 404

    result = simulator.recommend_best_destination(summary_df, interaction_df, from_id)
    return jsonify(result)


@api_bp.route("/tienda/<tienda_id>/simulate", methods=["POST"])
def tienda_simulate(tienda_id):
    """Análogo a /store/<store_name>/simulate pero para la vista
    combinada de tienda -- from_id/to_id son claves compuestas
    "camara_id::zone_id" (ver simulator.get_zone_options_multi)."""
    data = request.get_json(force=True)
    from_id, to_id = data.get("from_id"), data.get("to_id")
    if not from_id or not to_id:
        return jsonify({"ok": False, "error": "Faltan zona de origen y/o destino."}), 400

    zone_summary_combinado, _ = tienda_service.get_zone_summary_combinado(tienda_id)
    if zone_summary_combinado.empty:
        return jsonify({"ok": False, "error": "No se encontraron datos de esta tienda."}), 404
    interaction_combinado = tienda_service.get_interaction_summary_combinado(tienda_id)

    result = simulator.run_simulation_multi(zone_summary_combinado, interaction_combinado, from_id, to_id)
    return jsonify(result)


@api_bp.route("/tienda/<tienda_id>/simulate/recommend", methods=["POST"])
def tienda_simulate_recommend(tienda_id):
    """Análogo a /store/<store_name>/simulate/recommend pero para la
    vista combinada de tienda -- las candidatas cruzan TODAS las
    cámaras de la tienda (ver simulator.recommend_best_destination_multi)."""
    data = request.get_json(force=True)
    from_id = data.get("from_id")
    if not from_id:
        return jsonify({"ok": False, "error": "Falta la zona de origen."}), 400

    zone_summary_combinado, _ = tienda_service.get_zone_summary_combinado(tienda_id)
    if zone_summary_combinado.empty:
        return jsonify({"ok": False, "error": "No se encontraron datos de esta tienda."}), 404
    interaction_combinado = tienda_service.get_interaction_summary_combinado(tienda_id)

    result = simulator.recommend_best_destination_multi(zone_summary_combinado, interaction_combinado, from_id)
    return jsonify(result)


# --- Asistente de configuración: frames, calibración, procesamiento --------

@api_bp.route("/frame")
def frame():
    """Extrae un frame de un video como JPEG -- usado para las miniaturas
    de inicio/fin del recorte y como referencia de calibración."""
    video_path = request.args.get("video", "")
    at_second = float(request.args.get("at", "0"))
    with_heat_preview = request.args.get("heat", "0") == "1"

    if not video_path or not os.path.exists(video_path):
        abort(404)

    frame_bgr = video_utils.extract_frame_bgr(video_path, at_second)
    if frame_bgr is None:
        abort(404)

    if with_heat_preview:
        import cv2
        video_basename = os.path.splitext(os.path.basename(video_path))[0]
        tracks_csv = f"data/processed/tracks_{video_basename}.csv"
        if os.path.exists(tracks_csv):
            frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
            frame_rgb = video_utils.build_heat_preview(frame_rgb, tracks_csv)
            frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

    jpeg_bytes = video_utils.encode_frame_as_jpeg(frame_bgr)
    return Response(jpeg_bytes, mimetype="image/jpeg")


@api_bp.route("/store/<store_name>/save-zones", methods=["POST"])
def save_zones(store_name):
    data = request.get_json(force=True)
    try:
        path = calibration_service.save_zones_config(
            store_name, data["video_path"], data["frame_width"], data["frame_height"], data["zones"],
        )
    except (ValueError, KeyError) as e:
        return jsonify({"ok": False, "error": str(e)}), 400
    return jsonify({"ok": True, "path": path})


@api_bp.route("/store/<store_name>/generate-preview", methods=["POST"])
def generate_preview(store_name):
    """Lanza detect_and_track.py en segundo plano para generar la vista
    previa de calor usada como referencia de calibración."""
    import sys as _sys
    video_path = (request.get_json(force=True) or {}).get("video_path")
    if not video_path:
        return jsonify({"ok": False, "error": "Falta la ruta del video."}), 400

    job_key = f"{store_name}:preview"
    started, blocked_by = job_manager.start_job(
        job_key, [_sys.executable, "pipeline/detect_and_track.py", "--video", video_path],
        retry_env={"DISABLE_OPENVINO": "1"}, exclusive=True,
    )
    if not started:
        return jsonify({
            "ok": False, "busy": True,
            "error": f"Ya hay un trabajo en curso ({blocked_by}). Solo se puede procesar un video a la "
                     f"vez -- espera a que termine para no saturar la GPU/CPU.",
        })
    return jsonify({"ok": True, "started": True, "job_key": job_key})


@api_bp.route("/store/<store_name>/process", methods=["POST"])
def process(store_name):
    """Lanza run_pipeline.py en segundo plano."""
    import sys as _sys
    payload = request.get_json(force=True) or {}
    video_path = payload.get("video_path")
    if not video_path:
        return jsonify({"ok": False, "error": "Falta la ruta del video."}), 400

    device = payload.get("device", "auto")
    if device not in ("auto", "cpu", "gpu"):
        return jsonify({"ok": False, "error": f"Dispositivo inválido: '{device}'."}), 400

    command = [
        _sys.executable, "pipeline/run_pipeline.py",
        "--video", video_path, "--store-name", store_name,
        "--body-max-gap", str(payload.get("body_max_gap", 2.0)),
        "--body-max-speed", str(payload.get("body_max_speed", 500.0)),
        "--hand-max-gap", str(payload.get("hand_max_gap", 5.0)),
        "--hand-max-speed", str(payload.get("hand_max_speed", 300.0)),
        "--device", device,
    ]
    if payload.get("skip_hands"):
        command.append("--skip-hands")
    if payload.get("record_history"):
        command.append("--record-history")
        if payload.get("run_date"):
            command.extend(["--run-date", payload["run_date"]])

    job_key = f"{store_name}:process"
    started, blocked_by = job_manager.start_job(job_key, command, exclusive=True)
    if not started:
        return jsonify({
            "ok": False, "busy": True,
            "error": f"Ya hay un trabajo en curso ({blocked_by}). Solo se puede procesar un video a la "
                     f"vez -- espera a que termine para no saturar la GPU/CPU.",
        })
    return jsonify({"ok": True, "started": True, "job_key": job_key})


@api_bp.route("/store/<store_name>/status")
def status(store_name):
    """Endpoint de polling: el frontend lo consulta cada 1-2s mientras
    hay un job corriendo (generar vista previa o procesar)."""
    job_type = request.args.get("job", "process")
    job_key = f"{store_name}:{job_type}"
    job = job_manager.get_job(job_key)
    return jsonify(job)


@api_bp.route("/store/<store_name>/trim", methods=["POST"])
def trim(store_name):
    payload = request.get_json(force=True) or {}
    input_path = payload.get("input_path")
    start_sec = float(payload.get("start_sec", 0))
    end_sec = float(payload.get("end_sec", 0))
    if not input_path or not os.path.exists(input_path):
        return jsonify({"ok": False, "error": "No se encontró el video original."}), 400

    base, _ = os.path.splitext(os.path.basename(input_path))
    # .webm (VP8), no .mp4 -- ver dashboard/video_utils.py:trim_video()
    # para el porqué (mismo bug de códec ya resuelto en otros generadores
    # de video del proyecto, ver docs/architecture.md sección 19).
    output_path = os.path.join("data/raw", f"{base}_recortado.webm")
    n_frames = video_utils.trim_video(input_path, output_path, start_sec, end_sec)
    return jsonify({"ok": True, "output_path": output_path.replace("\\", "/"), "n_frames": n_frames})


# --- Gestión de datos (Parte 2, ver docs/architecture.md sección 35) -------
# Todas estas rutas son destructivas -- la confirmación (diálogo real,
# no un solo clic) vive en dashboard/static/js/data_management.js, NO
# acá: cuando el frontend llama a esta ruta, la acción se ejecuta de
# inmediato, sin preguntar de nuevo.

@api_bp.route("/store/<store_name>/datos/eliminar-video", methods=["POST"])
def eliminar_video_crudo(store_name):
    n = data_management_service.delete_raw_video(store_name)
    return jsonify({"ok": True, "n_files": n})


@api_bp.route("/store/<store_name>/datos/eliminar-resultados", methods=["POST"])
def eliminar_resultados_actuales(store_name):
    n = data_management_service.delete_processed_output(store_name)
    return jsonify({"ok": True, "n_files": n})


@api_bp.route("/store/<store_name>/datos/eliminar-fecha", methods=["POST"])
def eliminar_fecha_archivada(store_name):
    payload = request.get_json(force=True) or {}
    fecha = payload.get("fecha", "").strip()
    if not fecha:
        return jsonify({"ok": False, "error": "Falta la fecha a eliminar."}), 400
    deleted = data_management_service.delete_archived_date(store_name, fecha)
    return jsonify({"ok": True, "deleted": deleted})


@api_bp.route("/store/<store_name>/datos/eliminar-camara", methods=["POST"])
def eliminar_camara_completa(store_name):
    payload = request.get_json(force=True) or {}
    confirmacion = payload.get("confirmacion", "").strip()
    if confirmacion != store_name:
        return jsonify({"ok": False, "error": "El nombre escrito no coincide con el de la cámara -- no se eliminó nada."}), 400
    data_management_service.delete_camera_completely(store_name)
    return jsonify({"ok": True})


@api_bp.route("/tienda/<tienda_id>/eliminar", methods=["POST"])
def eliminar_tienda_completa(tienda_id):
    """Elimina la tienda Y TODAS sus cámaras -- ver
    data_management_service.delete_tienda_completa(). La confirmación
    se valida contra el LABEL de la tienda (el nombre que el usuario ve
    en la interfaz), no contra el id interno -- igual en espíritu a
    eliminar_camara_completa() de arriba, que valida contra el nombre
    visible de la cámara."""
    tienda = tienda_service.get_tienda(tienda_id)
    if tienda is None:
        return jsonify({"ok": False, "error": "Esa tienda no existe."}), 404

    payload = request.get_json(force=True) or {}
    confirmacion = payload.get("confirmacion", "").strip()
    tienda_label = tienda.get("label", tienda_id)
    if confirmacion != tienda_label:
        return jsonify({"ok": False, "error": "El nombre escrito no coincide con el de la tienda -- no se eliminó nada."}), 400

    resultado = data_management_service.delete_tienda_completa(tienda_id)
    if resultado["fallidas"]:
        n_total = len(resultado["eliminadas"]) + len(resultado["fallidas"])
        return jsonify({
            "ok": False,
            "error": (
                f"Se eliminaron {len(resultado['eliminadas'])} de {n_total} cámara(s), pero "
                f"{len(resultado['fallidas'])} falló/fallaron -- la tienda NO se eliminó del registro "
                "para no dejar cámaras huérfanas sin tienda."
            ),
            **resultado,
        }), 500
    return jsonify({"ok": True, **resultado})
