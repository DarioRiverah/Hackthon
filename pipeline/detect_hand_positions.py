"""
Detección de posición de manos (muñecas) sobre un video, usando YOLOv8-pose.

IMPORTANTE (alcance honesto): este módulo detecta CUÁNDO Y DÓNDE una persona
mete la mano al estante (aproximación + interacción física), NO distingue
con certeza si "tomó" o "devolvió" un producto -- esa distinción requeriría
modelos de reconocimiento de acciones especializados (ej. con flujo óptico,
como los que usa el propio dataset MERL en sus papers académicos), fuera
del alcance de un MVP de 15 días. Este es un límite técnico conocido,
comunicado desde el plan original del proyecto.

Lo que SÍ entrega de forma confiable:
    - Cuántas veces la persona metió la mano al estante
    - Cuánto tiempo duró cada interacción
    - En qué zona del estante ocurrió

No se procesan ni almacenan rostros ni ningún dato biométrico -- solo
la posición (x,y) de la muñeca, igual que se hace con el cuerpo completo
en detect_and_track.py.

La salida usa EXACTAMENTE el mismo formato de columnas que
detect_and_track.py (frame, timestamp, track_id, x_center, y_center, ...)
para poder reutilizar track_stitching.py sin ningún cambio.

Uso:
    python pipeline\\detect_hand_positions.py --video data\\raw\\1_2_crop.mp4
    python pipeline\\detect_hand_positions.py --video data\\raw\\1_2_crop.mp4 --conf 0.15
"""

import argparse
import csv
import os
import sys

import cv2
from ultralytics import YOLO

from detect_and_track import load_model

DEFAULT_VIDEO_PATH = "data/raw/synthetic_store_demo.webm"
POSE_MODEL_NAME = "yolov8n-pose.pt"
DEFAULT_TRACKER_CONFIG = "pipeline/custom_bytetrack.yaml"

# Índices de keypoints COCO-pose (formato estándar de Ultralytics)
KEYPOINT_LEFT_WRIST = 9
KEYPOINT_RIGHT_WRIST = 10

# Medio-ancho de la caja SINTÉTICA que se guarda en x1/y1/x2/y2 alrededor
# de la muñeca -- NO es una detección real, es solo para que el video de
# verificación (render_stitched_preview.py) tenga algo que dibujar/medir.
# Tiene que dar un ancho bien por debajo del umbral de 40px que usa
# detect_mode() en ese mismo archivo para distinguir "punto" (mano) de
# "caja" (cuerpo completo) -- si esto alguna vez vuelve a escribir la
# caja de la PERSONA completa (como hacía antes de esta corrección) el
# video de manos vuelve a mostrar un rectángulo grande en vez de un punto.
HAND_BOX_HALF_SIZE = 15


def parse_args():
    parser = argparse.ArgumentParser(description="Detección de posición de manos (muñecas) en video.")
    parser.add_argument("--video", type=str, default=DEFAULT_VIDEO_PATH,
                         help="Ruta del video a procesar (default: %(default)s)")
    parser.add_argument("--conf", type=float, default=0.2,
                         help="Umbral mínimo de confianza de detección (default: 0.2)")
    parser.add_argument("--keypoint-conf", type=float, default=0.3,
                         help="Confianza mínima del keypoint de muñeca para considerarlo válido (default: 0.3)")
    parser.add_argument("--tracker", type=str, default=DEFAULT_TRACKER_CONFIG,
                         help="Configuración del tracker (default: %(default)s)")
    return parser.parse_args()


def main():
    args = parse_args()
    video_path = args.video

    if not os.path.exists(video_path):
        print(f"ERROR: no se encontró el video en '{video_path}'")
        sys.exit(1)

    video_basename = os.path.splitext(os.path.basename(video_path))[0]
    output_csv = f"data/processed/hands_{video_basename}.csv"
    output_video = f"data/processed/hands_preview_{video_basename}.webm"

    os.makedirs("data/processed", exist_ok=True)

    model = load_model(POSE_MODEL_NAME)  # se descarga automáticamente la primera vez (~6-7MB) si no está cacheado

    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    cap.release()

    # VP8/WebM, no mp4v -- mp4v (MPEG-4 Part 2) no lo reproducen los
    # navegadores nativamente. Ver la nota equivalente en
    # render_stitched_preview.py para el detalle de por qué VP8 y no
    # H.264 (avc1 no es viable en esta instalación de OpenCV/FFmpeg sin
    # instalar la DLL de OpenH264, con licencia Cisco).
    writer = cv2.VideoWriter(
        output_video, cv2.VideoWriter_fourcc(*"VP80"), fps, (width, height)
    )

    rows = []
    frame_idx = 0
    n_no_wrist = 0

    results = model.track(
        source=video_path,
        conf=args.conf,
        persist=True,
        stream=True,
        tracker=args.tracker,
        verbose=False,
    )

    for result in results:
        frame = result.orig_img.copy()
        timestamp = frame_idx / fps if fps > 0 else 0

        has_tracks = result.boxes is not None and result.boxes.id is not None
        has_keypoints = result.keypoints is not None

        if has_tracks and has_keypoints:
            track_ids = result.boxes.id.cpu().numpy().astype(int)
            kpts_xy = result.keypoints.xy.cpu().numpy()      # (n_personas, 17, 2)
            kpts_conf = result.keypoints.conf.cpu().numpy() if result.keypoints.conf is not None else None

            for i, track_id in enumerate(track_ids):
                # Elegir la muñeca con mayor confianza entre izquierda y derecha
                candidates = []
                for kp_idx in (KEYPOINT_LEFT_WRIST, KEYPOINT_RIGHT_WRIST):
                    x, y = kpts_xy[i][kp_idx]
                    conf = kpts_conf[i][kp_idx] if kpts_conf is not None else 1.0
                    if conf >= args.keypoint_conf and (x > 0 or y > 0):
                        candidates.append((conf, x, y))

                if not candidates:
                    n_no_wrist += 1
                    continue

                candidates.sort(reverse=True)  # mayor confianza primero
                _, wrist_x, wrist_y = candidates[0]

                rows.append({
                    "frame": frame_idx,
                    "timestamp": round(timestamp, 3),
                    "track_id": int(track_id),
                    "x_center": round(float(wrist_x), 1),
                    "y_center": round(float(wrist_y), 1),
                    "x1": round(float(wrist_x) - HAND_BOX_HALF_SIZE, 1),
                    "y1": round(float(wrist_y) - HAND_BOX_HALF_SIZE, 1),
                    "x2": round(float(wrist_x) + HAND_BOX_HALF_SIZE, 1),
                    "y2": round(float(wrist_y) + HAND_BOX_HALF_SIZE, 1),
                })

                cv2.circle(frame, (int(wrist_x), int(wrist_y)), 6, (0, 255, 255), -1)
                cv2.putText(frame, f"ID {track_id}", (int(wrist_x) + 8, int(wrist_y)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 255), 2)

        writer.write(frame)
        frame_idx += 1

    writer.release()

    with open(output_csv, "w", newline="") as f:
        fieldnames = ["frame", "timestamp", "track_id", "x_center", "y_center",
                      "x1", "y1", "x2", "y2"]
        writer_csv = csv.DictWriter(f, fieldnames=fieldnames)
        writer_csv.writeheader()
        writer_csv.writerows(rows)

    n_unique_ids = len(set(r["track_id"] for r in rows))

    print("Detección de manos completa.")
    print(f"Posiciones de muñeca guardadas en: {output_csv} ({len(rows)} detecciones, {n_unique_ids} IDs únicos)")
    print(f"Frames sin muñeca detectada con suficiente confianza: {n_no_wrist}")
    print(f"Video de verificación en: {output_video}")
    print("\nSiguiente paso: correr track_stitching.py sobre este CSV igual que con tracks de cuerpo.")


if __name__ == "__main__":
    main()