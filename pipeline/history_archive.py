"""
Archivado histórico completo por fecha -- ver docs/architecture.md
sección 34.

Hasta esta sección, "guardar en el historial" (--record-history, en
run_pipeline.py) solo guardaba NÚMEROS AGREGADOS (zone_summary/
interaction_summary) en history.db -- los archivos "ricos" (heatmaps,
eventos crudos, video de verificación) vivían solo en data/output/ y
data/processed/, y se SOBREESCRIBÍAN en la siguiente corrida. Este
módulo copia una instantánea completa de los artefactos de una corrida
a data/history/<camara>/<fecha>/, para poder ver "cómo se veía el
heatmap del 17 de agosto" incluso después de reprocesar la cámara.

Alcance deliberado -- qué SÍ y qué NO se archiva:
  SÍ: zone_summary, interaction_summary, zone_events, interaction_events
      (los 4 CSV que alimentan Historia/Interacción/Recomendaciones),
      heatmap de flujo, heatmap de manos, diagrama de espagueti (las 3
      imágenes que alimentan Mapas), y una copia de zones.json (para
      que la vista histórica pueda mostrar las etiquetas/clasificación
      de zona tal como eran en ese momento, sin depender de que la
      calibración actual no haya cambiado).
  NO: los videos de verificación de tracking (tracked_preview_corregido_*.webm,
      hands_preview_corregido_*.webm). Son herramientas de control de
      calidad técnico (¿se siguió bien a cada persona?), no contenido
      que el dueño de la tienda necesite revisar por fecha histórica --
      y pesan ~decenas-cientos de MB cada uno, lo que volvería el
      archivado insostenible en disco corrida tras corrida. La vista
      histórica de Mapas simplemente no ofrece el expander de video
      para una fecha archivada (ver dashboard/templates/results.html).

100% pura (sin Flask) -- solo shutil/os, ningún estado en memoria.
"""

import json
import os
import shutil

ARCHIVE_ROOT = "data/history"

# Cada tupla es (nombre_fuente_relativo_a_data_output_O_data_processed,
# nombre_archivado_generico, es_ruta_por_video_basename). Los que llevan
# "prefix" se resuelven como f"data/output/{prefix}_{store_o_video}.ext".
_CSV_ARTIFACTS = [
    ("zone_summary", "zone_summary.csv"),
    ("interaction_summary", "interaction_summary.csv"),
    ("zone_events", "zone_events.csv"),
    ("interaction_events", "interaction_events.csv"),
]
# Estos tres se nombran por el BASENAME DEL VIDEO (no por store_name) en
# pipeline/heatmap.py y pipeline/spaghetti_diagram.py -- ver
# docs/architecture.md sección 33 para el porqué de esta inconsistencia
# de nombres, ya existente antes de esta tarea.
_IMAGE_ARTIFACTS = [
    ("heatmap_{video}.png", "heatmap_flujo.png"),
    ("heatmap_manos_{video}.png", "heatmap_manos.png"),
    ("spaghetti_{video}.png", "spaghetti.png"),
]


def get_archive_dir(camara_id: str, run_date: str) -> str:
    return os.path.join(ARCHIVE_ROOT, camara_id, run_date)


def archive_run(camara_id: str, run_date: str, video_reference: str = None) -> list:
    """Copia los artefactos "ricos" de la corrida actual de `camara_id`
    a data/history/<camara_id>/<run_date>/. Se llama DESPUÉS de que el
    pipeline ya generó todo en data/output/ (mismo momento en que se
    llama a history_db.record_run()). Devuelve la lista de archivos
    copiados (para loguear); no falla si algún artefacto opcional no
    existe (ej. una corrida con --skip-hands no tiene heatmap de
    manos)."""
    archive_dir = get_archive_dir(camara_id, run_date)
    os.makedirs(archive_dir, exist_ok=True)

    video_basename = os.path.splitext(os.path.basename(video_reference))[0] if video_reference else camara_id

    copied = []

    for prefix, archived_name in _CSV_ARTIFACTS:
        src = f"data/output/{prefix}_{camara_id}.csv"
        if os.path.exists(src):
            dst = os.path.join(archive_dir, archived_name)
            shutil.copy2(src, dst)
            copied.append(dst)

    for pattern, archived_name in _IMAGE_ARTIFACTS:
        src = os.path.join("data/output", pattern.format(video=video_basename))
        if os.path.exists(src):
            dst = os.path.join(archive_dir, archived_name)
            shutil.copy2(src, dst)
            copied.append(dst)

    zones_src = f"config/zones_{camara_id}.json"
    if os.path.exists(zones_src):
        zones_dst = os.path.join(archive_dir, "zones.json")
        shutil.copy2(zones_src, zones_dst)
        copied.append(zones_dst)

    return copied


def list_archived_dates(camara_id: str) -> list:
    """Fechas archivadas para una cámara, más recientes primero. Una
    fecha "archivada" es simplemente una subcarpeta de
    data/history/<camara_id>/ -- no depende de que la fila siga
    existiendo en history.db (aunque en el flujo normal ambas se crean
    y se borran juntas)."""
    camara_dir = os.path.join(ARCHIVE_ROOT, camara_id)
    if not os.path.isdir(camara_dir):
        return []
    dates = [d for d in os.listdir(camara_dir) if os.path.isdir(os.path.join(camara_dir, d))]
    return sorted(dates, reverse=True)


def archive_exists(camara_id: str, run_date: str) -> bool:
    return os.path.isdir(get_archive_dir(camara_id, run_date))


def get_archive_size_bytes(camara_id: str, run_date: str) -> int:
    archive_dir = get_archive_dir(camara_id, run_date)
    if not os.path.isdir(archive_dir):
        return 0
    total = 0
    for root, _, files in os.walk(archive_dir):
        for name in files:
            total += os.path.getsize(os.path.join(root, name))
    return total


def delete_archived_date(camara_id: str, run_date: str) -> bool:
    """Borra la carpeta archivada de una fecha. Devuelve True si algo se
    borró. NO toca history.db -- el llamador es responsable de también
    invocar pipeline.history_db.delete_run() si corresponde (se
    mantienen separados a propósito: uno es un borrado de archivos,
    el otro de filas de base de datos)."""
    archive_dir = get_archive_dir(camara_id, run_date)
    if not os.path.isdir(archive_dir):
        return False
    shutil.rmtree(archive_dir)
    return True


def delete_all_archived(camara_id: str) -> bool:
    """Borra TODAS las fechas archivadas de una cámara -- usado al
    eliminar la cámara completa (ver Parte 2, "Eliminar cámara
    completa")."""
    camara_dir = os.path.join(ARCHIVE_ROOT, camara_id)
    if not os.path.isdir(camara_dir):
        return False
    shutil.rmtree(camara_dir)
    return True


def load_archived_zones_config(camara_id: str, run_date: str) -> dict:
    """Lee zones.json tal como estaba en el momento en que se archivó
    esta fecha (para clasificar/etiquetar zonas con la configuración de
    ESE momento, no la actual)."""
    path = os.path.join(get_archive_dir(camara_id, run_date), "zones.json")
    if not os.path.exists(path):
        return {}
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)
