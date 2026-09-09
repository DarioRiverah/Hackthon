"""
Detección y tracking de personas sobre un video.

Usa YOLOv8 (detección) + ByteTrack (tracking, integrado en Ultralytics).
Solo detecta la clase "person" (clase 0 de COCO) — no se procesan ni
almacenan rostros ni ningún dato biométrico, solo posición del cuerpo.

Incluye un filtro OPCIONAL de proporción de caja (aspect ratio) para
descartar falsos positivos como señales de tránsito u objetos redondos
que el modelo a veces confunde con personas a distancia. Este filtro
SOLO debe activarse en cámaras laterales/de calle -- en cámaras
cenitales (vista desde arriba, ej. MERL) una persona real también
genera cajas anchas, así que activar el filtro ahí eliminaría
detecciones válidas.

Salida: un CSV con columnas [frame, timestamp, track_id, x_center, y_center,
x1, y1, x2, y2] que alimenta los módulos de zonificación y dwell time.

Uso:
    python pipeline\\detect_and_track.py --video data\\raw\\1_2_crop.mp4
    python pipeline\\detect_and_track.py --video data\\raw\\calle.mp4 --filter-aspect-ratio
"""

import cv2
import csv
import os
import sys
import argparse
from ultralytics import YOLO

DEFAULT_VIDEO_PATH = "data/raw/synthetic_store_demo.webm"
MODEL_NAME = "yolo26n.pt"
PERSON_CLASS_ID = 0
DEFAULT_TRACKER_CONFIG = "pipeline/custom_bytetrack.yaml"


def load_model(pt_name: str) -> YOLO:
    """Carga el modelo optimizado a OpenVINO si existe (más rápido en CPU
    Intel -- ver pipeline/export_openvino.py y docs/architecture.md), o el
    .pt original si no. La conversión a OpenVINO es puramente una
    optimización, nunca una dependencia dura: DISABLE_OPENVINO=1 (variable
    de entorno) fuerza el .pt original sin ni siquiera intentar cargar el
    optimizado -- es lo que usa dashboard/job_manager.py y
    pipeline/run_pipeline.py para reintentar automáticamente si un intento
    anterior con OpenVINO falló. Si el directorio existe pero falla al
    CARGAR (versión de openvino incompatible, archivos corruptos, etc.),
    también cae de vuelta al .pt sin propagar la excepción -- lo único que
    esto NO puede atrapar es una caída nativa (segfault) durante la
    INFERENCIA en sí, ya iniciada la carga; para eso está el reintento a
    nivel de proceso en el llamador."""
    openvino_dir = f"{os.path.splitext(pt_name)[0]}_openvino_model"
    if os.environ.get("DISABLE_OPENVINO") == "1":
        return YOLO(pt_name)
    if os.path.isdir(openvino_dir):
        try:
            model = YOLO(openvino_dir)
            print(f"[OpenVINO] Usando modelo optimizado: {openvino_dir}")
            return model
        except Exception as e:
            print(f"[OpenVINO] No se pudo cargar '{openvino_dir}' ({e}) -- usando '{pt_name}' sin optimizar.")
    return YOLO(pt_name)


def parse_args():
    parser = argparse.ArgumentParser(description="Detección y tracking de personas en video.")
    parser.add_argument("--video", type=str, default=DEFAULT_VIDEO_PATH,
                         help="Ruta del video a procesar (default: %(default)s)")
    parser.add_argument("--conf", type=float, default=0.2,
                         help="Umbral mínimo de confianza de detección (default: 0.2)")
    parser.add_argument("--tracker", type=str, default=DEFAULT_TRACKER_CONFIG,
                         help="Ruta al archivo de configuración del tracker (default: %(default)s)")
    parser.add_argument("--filter-aspect-ratio", action="store_true",
                         help="Descarta detecciones con proporción atípica de persona (alto/ancho). "
                              "SOLO usar en cámaras laterales/de calle, NO en cámaras cenitales.")
    parser.add_argument("--min-aspect-ratio", type=float, default=1.1,
                         help="Proporción mínima alto/ancho para considerar plausible (default: 1.1)")
    parser.add_argument("--max-aspect-ratio", type=float, default=5.0,
                         help="Proporción máxima alto/ancho para considerar plausible (default: 5.0)")
    return parser.parse_args()


def is_plausible_person_box(x1, y1, x2, y2, min_ratio, max_ratio):
    width = x2 - x1
    height = y2 - y1
    if width <= 0:
        return False
    ratio = height / width
    return min_ratio <= ratio <= max_ratio


def main():
    args = parse_args()
    video_path = args.video

    if not os.path.exists(video_path):
        print(f"ERROR: no se encontró el video en '{video_path}'")
        sys.exit(1)

    video_basename = os.path.splitext(os.path.basename(video_path))[0]
    output_csv = f"data/processed/tracks_{video_basename}.csv"
    output_video = f"data/processed/tracked_preview_{video_basename}.webm"

    os.makedirs("data/processed", exist_ok=True)

    model = load_model(MODEL_NAME)

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
    n_filtered_out = 0

    results = model.track(
        source=video_path,
        classes=[PERSON_CLASS_ID],
        conf=args.conf,
        persist=True,
        stream=True,
        tracker=args.tracker,
        verbose=False,
    )

    for result in results:
        frame = result.orig_img.copy()
        timestamp = frame_idx / fps if fps > 0 else 0

        if result.boxes is not None and result.boxes.id is not None:
            boxes = result.boxes.xyxy.cpu().numpy()
            track_ids = result.boxes.id.cpu().numpy().astype(int)

            for box, track_id in zip(boxes, track_ids):
                x1, y1, x2, y2 = box

                if args.filter_aspect_ratio:
                    if not is_plausible_person_box(x1, y1, x2, y2,
                                                    args.min_aspect_ratio,
                                                    args.max_aspect_ratio):
                        n_filtered_out += 1
                        continue

                x_center = (x1 + x2) / 2
                y_center = (y1 + y2) / 2

                rows.append({
                    "frame": frame_idx,
                    "timestamp": round(timestamp, 3),
                    "track_id": int(track_id),
                    "x_center": round(float(x_center), 1),
                    "y_center": round(float(y_center), 1),
                    "x1": round(float(x1), 1),
                    "y1": round(float(y1), 1),
                    "x2": round(float(x2), 1),
                    "y2": round(float(y2), 1),
                })

                cv2.rectangle(frame, (int(x1), int(y1)), (int(x2), int(y2)),
                              (0, 255, 0), 2)
                cv2.putText(frame, f"ID {track_id}", (int(x1), int(y1) - 8),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

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

    print(f"Procesamiento completo.")
    print(f"Tracks guardados en: {output_csv} ({len(rows)} detecciones, {n_unique_ids} IDs únicos)")
    if args.filter_aspect_ratio:
        print(f"Detecciones descartadas por filtro de proporción: {n_filtered_out}")
    print(f"Video de verificación en: {output_video}")


if __name__ == "__main__":
    main()