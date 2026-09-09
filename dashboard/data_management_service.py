"""
Gestión de datos por cámara: ver espacio en disco y eliminar -- ver
docs/architecture.md sección 35.

100% pura (sin Flask) -- solo filesystem + los módulos puros ya
existentes (tienda_service, pipeline/history_archive, pipeline/history_db).
Todas las funciones de borrado operan directo sobre archivos/registros
reales -- NINGUNA confirmación vive acá, eso es responsabilidad de la
ruta Flask (que exige un POST explícito) y del frontend (que exige un
diálogo de confirmación antes de llamar a la ruta) -- ver
dashboard/routes/api_routes.py y dashboard/templates/data_management.html.
"""

import json
import os
import sys

import tienda_service

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
import history_archive  # noqa: E402
import history_db  # noqa: E402


def _resolve_video_basename(camara_id: str):
    """El basename del video de referencia de una cámara -- heatmap.py y
    spaghetti_diagram.py nombran sus artefactos por ESE basename, no por
    camara_id (ver docs/architecture.md sección 33)."""
    zones_path = f"config/zones_{camara_id}.json"
    if not os.path.exists(zones_path):
        return None
    with open(zones_path, "r", encoding="utf-8") as f:
        video_ref = json.load(f).get("video_reference")
    return os.path.splitext(os.path.basename(video_ref))[0] if video_ref else None


def _processed_output_paths(camara_id: str) -> list:
    """Todos los archivos de data/processed/ + data/output/ que
    pertenecen a esta cámara (NO data/raw, NO data/history -- esos se
    manejan por separado). Solo devuelve los que EXISTEN de verdad."""
    video_basename = _resolve_video_basename(camara_id)
    candidates = [
        f"data/output/zone_summary_{camara_id}.csv",
        f"data/output/interaction_summary_{camara_id}.csv",
        f"data/output/zone_events_{camara_id}.csv",
        f"data/output/interaction_events_{camara_id}.csv",
        f"data/output/reporte_{camara_id}.pdf",
    ]
    if video_basename:
        candidates += [
            f"data/output/heatmap_{video_basename}.png",
            f"data/output/heatmap_manos_{video_basename}.png",
            f"data/output/spaghetti_{video_basename}.png",
            f"data/processed/tracks_{video_basename}.csv",
            f"data/processed/tracks_{video_basename}_stitched.csv",
            f"data/processed/tracked_preview_{video_basename}.webm",
            f"data/processed/tracked_preview_corregido_{video_basename}.webm",
            f"data/processed/hands_{video_basename}.csv",
            f"data/processed/hands_{video_basename}_stitched.csv",
            f"data/processed/hands_preview_{video_basename}.webm",
            f"data/processed/hands_preview_corregido_{video_basename}.webm",
        ]
    return [p for p in candidates if os.path.exists(p)]


def get_raw_video_files(camara_id: str) -> list:
    """Video(s) crudo(s) en data/raw/ asociados a esta cámara -- el
    referenciado en zones_<camara>.json (si existe) más cualquier otro
    archivo en data/raw/ cuyo nombre empiece con el id de la cámara
    (cubre variantes como <camara>_recortado.webm -- ver
    dashboard/video_utils.py:trim_video())."""
    candidates = set()

    zones_path = f"config/zones_{camara_id}.json"
    if os.path.exists(zones_path):
        with open(zones_path, "r", encoding="utf-8") as f:
            video_ref = json.load(f).get("video_reference")
        if video_ref:
            candidates.add(os.path.normpath(video_ref))

    if os.path.isdir("data/raw"):
        for filename in os.listdir("data/raw"):
            if filename.startswith(camara_id):
                candidates.add(os.path.normpath(os.path.join("data/raw", filename)))

    results = []
    for path in sorted(candidates):
        if os.path.exists(path):
            size_bytes = os.path.getsize(path)
            results.append({
                "path": path.replace("\\", "/"),
                "size_mb": round(size_bytes / (1024 * 1024), 1),
            })
    return results


def get_processed_output_info(camara_id: str) -> dict:
    paths = _processed_output_paths(camara_id)
    total_bytes = sum(os.path.getsize(p) for p in paths)
    return {"n_files": len(paths), "size_mb": round(total_bytes / (1024 * 1024), 1)}


def get_archived_dates_info(camara_id: str) -> list:
    """[{"fecha":, "size_mb":}, ...] -- una entrada por fecha archivada,
    más reciente primero (ver pipeline/history_archive.py)."""
    dates = history_archive.list_archived_dates(camara_id)
    return [
        {"fecha": d, "size_mb": round(history_archive.get_archive_size_bytes(camara_id, d) / (1024 * 1024), 2)}
        for d in dates
    ]


def delete_processed_output(camara_id: str) -> int:
    """Elimina data/processed/ + data/output/ de esta cámara -- deja la
    cámara "calibrada pero no procesada" (config/zones_<camara>.json y
    el video crudo NO se tocan). Devuelve cuántos archivos se borraron."""
    paths = _processed_output_paths(camara_id)
    for p in paths:
        os.remove(p)
    return len(paths)


def delete_raw_video(camara_id: str) -> int:
    """Elimina el/los video(s) crudo(s) de data/raw/ de esta cámara. NO
    toca resultados ya procesados ni el historial archivado -- pero sin
    el video, esta cámara no se puede reprocesar hasta subir uno nuevo
    (advertencia que muestra el frontend antes de confirmar)."""
    videos = get_raw_video_files(camara_id)
    for v in videos:
        os.remove(v["path"])
    return len(videos)


def delete_archived_date(camara_id: str, run_date: str) -> bool:
    """Elimina una fecha archivada: la carpeta de data/history/ Y la fila
    correspondiente en history.db (las dos mitades del archivado
    completo de la Parte 1)."""
    deleted = history_archive.delete_archived_date(camara_id, run_date)
    history_db.delete_run(camara_id, run_date)
    return deleted


def delete_camera_completely(camara_id: str) -> None:
    """Acción irreversible: borra TODO lo de esta cámara -- resultados
    actuales, video(s) crudo(s), TODAS las fechas archivadas (archivo +
    filas de history.db), config/zones_<camara>.json, y la quita del
    registro de su tienda (config/tiendas.json). El llamador (la ruta
    Flask) es responsable de exigir la confirmación fuerte (escribir el
    nombre de la cámara) ANTES de invocar esta función -- acá no hay
    ninguna confirmación, se ejecuta de inmediato."""
    delete_processed_output(camara_id)
    delete_raw_video(camara_id)

    for run_date in history_archive.list_archived_dates(camara_id):
        history_db.delete_run(camara_id, run_date)
    history_archive.delete_all_archived(camara_id)

    zones_path = f"config/zones_{camara_id}.json"
    if os.path.exists(zones_path):
        os.remove(zones_path)

    tienda_service.remove_camara(camara_id)


def delete_tienda_completa(tienda_id: str) -> dict:
    """Acción irreversible: borra la tienda completa -- TODAS sus
    cámaras, reusando delete_camera_completely() una por una (la MISMA
    función que ya usa "Eliminar cámara completa", no una reimplementación)
    y, solo si TODAS se eliminaron sin error, la entrada de la tienda en
    config/tiendas.json (delete_camera_completely() ya deja cada cámara
    borrada quitada de la lista de cámaras de su tienda por su cuenta,
    vía tienda_service.remove_camara() -- acá solo falta el paso final
    de borrar la tienda misma). El llamador (la ruta Flask) es
    responsable de exigir la confirmación fuerte (escribir el nombre de
    la tienda) ANTES de invocar esta función.

    Sigue intentando con el resto de las cámaras aunque alguna falle a
    mitad de camino (mejor esfuerzo, no aborta en el primer error) --
    las que sí se pudieron borrar quedan borradas (cada
    delete_camera_completely() ya es irreversible por sí sola, no hay
    rollback posible), y la tienda NO se borra del registro si quedó
    alguna cámara sin eliminar, para no dejar cámaras huérfanas sin
    tienda. El resultado reporta explícitamente qué se eliminó y qué
    no, en vez de fallar en silencio o dejar el estado ambiguo."""
    camaras = tienda_service.get_camaras_de_tienda(tienda_id)
    eliminadas = []
    fallidas = []
    for camara_id in camaras:
        try:
            delete_camera_completely(camara_id)
            eliminadas.append(camara_id)
        except Exception as e:
            fallidas.append({"camara_id": camara_id, "error": str(e)})

    tienda_eliminada = False
    if not fallidas:
        tienda_eliminada = tienda_service.delete_tienda(tienda_id)

    return {
        "eliminadas": eliminadas,
        "fallidas": fallidas,
        "tienda_eliminada": tienda_eliminada,
    }
