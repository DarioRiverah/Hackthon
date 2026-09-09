"""
Utilidades de video para el asistente de configuración -- 100% puras
(sin Streamlit ni Flask), extraídas tal cual de la versión anterior del
dashboard (ahora en _legacy_streamlit/app.py) al migrar a Flask. La
lógica interna NO cambió -- solo se removieron las llamadas st.* de
presentación.
"""

import os

import cv2
import pandas as pd

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
from heatmap import build_density_map, render_heatmap as render_heatmap_overlay  # noqa: E402


def format_seconds(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def get_video_duration(video_path: str) -> float:
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    if fps <= 0:
        return 0.0
    return frame_count / fps


def extract_frame_bgr(video_path: str, at_second: float):
    """Extrae un frame en BGR (formato nativo de OpenCV/cv2.imencode,
    conveniente para servirlo directo como imagen vía Flask) en el
    segundo dado. Devuelve None si no se pudo leer."""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_idx = int(at_second * fps) if fps > 0 else 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return None
    return frame


def extract_frame_rgb(video_path: str, at_second: float):
    """Igual que extract_frame_bgr, pero en RGB -- para cuando el
    resultado se vaya a procesar más (ej. build_heat_preview)."""
    frame = extract_frame_bgr(video_path, at_second)
    if frame is None:
        return None
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def trim_video(input_path: str, output_path: str, start_sec: float, end_sec: float) -> int:
    """Recorta el video al rango [start_sec, end_sec] y lo guarda como un
    nuevo archivo. Devuelve el número de frames escritos.

    `output_path` debe terminar en .webm -- VP8/WebM, NO mp4v/.mp4 (ver
    docs/architecture.md sección 19: mp4v no lo reproducen los
    navegadores nativamente, y H.264 real no está disponible sin la DLL
    de OpenH264 con licencia Cisco). Antes este archivo se generaba en
    .mp4 porque supuestamente "nunca se muestra con <video>, solo
    alimenta el pipeline" -- esa suposición dejó de ser cierta cuando el
    asistente de configuración empezó a mostrar el recorte en un
    reproductor real (paso "1. Sube tu video"), reproduciendo el mismo
    bug ya resuelto en pipeline/render_stitched_preview.py y los preview
    generators de detect_and_track.py/detect_hand_positions.py."""
    cap = cv2.VideoCapture(input_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    start_frame = int(start_sec * fps)
    end_frame = int(end_sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    writer = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*"VP80"), fps, (width, height))

    frame_idx = start_frame
    n_written = 0
    while frame_idx < end_frame:
        ret, frame = cap.read()
        if not ret:
            break
        writer.write(frame)
        frame_idx += 1
        n_written += 1

    cap.release()
    writer.release()
    return n_written


def build_heat_preview(frame_rgb, tracks_csv_path: str, blur_radius: int = 35):
    """Genera una vista previa de calor sobre el frame de calibración,
    reutilizando la lógica de pipeline/heatmap.py."""
    df = pd.read_csv(tracks_csv_path)
    if df.empty:
        return frame_rgb

    height, width = frame_rgb.shape[:2]
    density = build_density_map(df, width, height, blur_radius)

    frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    blended_bgr = render_heatmap_overlay(frame_bgr, density, opacity=0.5)
    return cv2.cvtColor(blended_bgr, cv2.COLOR_BGR2RGB)


def encode_frame_as_jpeg(frame_bgr) -> bytes:
    """Codifica un frame (BGR, formato nativo de cv2) como JPEG en
    memoria, para servirlo directo desde una ruta de Flask sin escribir
    un archivo temporal."""
    ok, buffer = cv2.imencode(".jpg", frame_bgr, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        raise ValueError("No se pudo codificar el frame como JPEG.")
    return buffer.tobytes()
