"""
Detección y tracking de personas sobre un video, usando UN SOLO modelo:
YOLO26-pose + ByteTrack (tracking, integrado en Ultralytics).

Antes este pipeline corría DOS modelos por separado sobre el mismo video
(YOLO26 solo-detección para el cuerpo completo, en este archivo, y
YOLOv8-pose para la muñeca, en el ahora eliminado detect_hand_positions.py).
Un modelo de pose YA incluye la caja de la persona completa (igual que un
detector normal) MÁS los keypoints del esqueleto -- así que correr el
video dos veces era trabajo duplicado: una sola pasada de YOLO26-pose
entrega ambas señales (caja de cuerpo y keypoint de muñeca) al mismo
tiempo, por persona y por frame.

Solo detecta/seguimiento de la clase "person" (única clase de los
modelos de pose COCO) -- no se procesan ni almacenan rostros ni ningún
dato biométrico, solo posición del cuerpo y de la muñeca.

Incluye un filtro OPCIONAL de proporción de caja (aspect ratio) para
descartar falsos positivos como señales de tránsito u objetos redondos
que el modelo a veces confunde con personas a distancia. Este filtro
SOLO debe activarse en cámaras laterales/de calle -- en cámaras
cenitales (vista desde arriba, ej. MERL) una persona real también
genera cajas anchas, así que activar el filtro ahí eliminaría
detecciones válidas.

Salidas:
    data/processed/tracks_<video>.csv  -> caja de cuerpo completo, con
        columnas [frame, timestamp, track_id, x_center, y_center,
        x1, y1, x2, y2, conf] (alimenta zoning.py y el heatmap de flujo)
    data/processed/hands_<video>.csv   -> posición de CADA muñeca (caja
        SINTÉTICA alrededor del keypoint, no una detección real) -- una
        fila POR MUÑECA (columna "hand_side": "izquierda"/"derecha"), no
        una sola posición combinada, ya que ambas manos son puntos de
        contacto independientes con el estante. Mismas columnas base que
        el CSV de cuerpo (más "hand_side") -- para poder reutilizar
        track_stitching.py sin cambios. Alcance honesto: esto detecta
        CUÁNDO Y DÓNDE una persona mete la mano al estante, NO distingue
        con certeza si "tomó" o "devolvió" un producto (ver
        interaction_events.py).
    data/processed/keypoints_<video>.csv -> los 17 keypoints COCO-pose
        completos por detección (frame, track_id, kp0_x..kp16_conf) --
        alimenta el dibujo de esqueleto estilo Ultralytics en
        render_stitched_preview.py, que ya no tiene acceso al objeto
        Results original.
    data/processed/tracked_preview_<video>.webm -> UN SOLO video de
        verificación con la caja de cuerpo, el esqueleto completo y
        AMBAS muñecas superpuestos en el mismo frame (antes eran dos
        videos separados, uno por cada script/modelo, y solo se marcaba
        una muñeca). El dibujo de caja+esqueleto usa directamente
        results.plot() de Ultralytics (estilo estándar de un modelo de
        pose), no un redibujado manual con cv2.

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

from device_utils import resolve_device, should_skip_openvino
from pose_drawing import (
    LEFT_WRIST, RIGHT_WRIST, keypoint_field_names, keypoints_to_row, draw_wrist_markers,
)

DEFAULT_VIDEO_PATH = "data/raw/synthetic_store_demo.webm"
MODEL_NAME = "yolo26n-pose.pt"
PERSON_CLASS_ID = 0
DEFAULT_TRACKER_CONFIG = "pipeline/custom_bytetrack.yaml"

BODY_FIELDNAMES = ["frame", "timestamp", "track_id", "x_center", "y_center",
                    "x1", "y1", "x2", "y2", "conf"]
HAND_FIELDNAMES = BODY_FIELDNAMES + ["hand_side"]
KEYPOINT_FIELDNAMES = ["frame", "track_id"] + keypoint_field_names()

# Medio-ancho de la caja SINTÉTICA que se guarda en x1/y1/x2/y2 alrededor
# de la muñeca -- NO es una detección real, es solo para que el CSV de
# manos tenga el mismo formato de columnas que el de cuerpo. Tiene que
# dar un ancho bien por debajo de las cajas reales de cuerpo completo
# para que sea inconfundible en cualquier inspección manual del CSV.
HAND_BOX_HALF_SIZE = 15


def load_model(pt_name: str, skip_openvino: bool = False) -> YOLO:
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
    nivel de proceso en el llamador.

    `skip_openvino=True` es lo que decide device_utils.should_skip_openvino():
    el backend OpenVINO IR de Ultralytics está pensado para CPU/GPU
    integrada de Intel y NUNCA corre sobre una GPU NVIDIA/CUDA -- así que
    tanto forzar GPU como 'auto' con una GPU CUDA disponible deben ir
    directo al .pt original en vez de intentar cargar el optimizado (ver
    el docstring de should_skip_openvino para el porqué: OpenVINO podía
    terminar corriendo silenciosamente en una GPU integrada de Intel en
    vez de la GPU NVIDIA dedicada, mucho más rápida)."""
    openvino_dir = f"{os.path.splitext(pt_name)[0]}_openvino_model"
    if skip_openvino or os.environ.get("DISABLE_OPENVINO") == "1":
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
    parser = argparse.ArgumentParser(description="Detección y tracking de personas (cuerpo + muñeca) en video.")
    parser.add_argument("--video", type=str, default=DEFAULT_VIDEO_PATH,
                         help="Ruta del video a procesar (default: %(default)s)")
    parser.add_argument("--conf", type=float, default=0.2,
                         help="Umbral mínimo de confianza de detección (default: 0.2)")
    parser.add_argument("--keypoint-conf", type=float, default=0.3,
                         help="Confianza mínima del keypoint de muñeca para considerarlo válido (default: 0.3)")
    parser.add_argument("--tracker", type=str, default=DEFAULT_TRACKER_CONFIG,
                         help="Ruta al archivo de configuración del tracker (default: %(default)s)")
    parser.add_argument("--filter-aspect-ratio", action="store_true",
                         help="Descarta detecciones con proporción atípica de persona (alto/ancho). "
                              "SOLO usar en cámaras laterales/de calle, NO en cámaras cenitales.")
    parser.add_argument("--min-aspect-ratio", type=float, default=1.1,
                         help="Proporción mínima alto/ancho para considerar plausible (default: 1.1)")
    parser.add_argument("--max-aspect-ratio", type=float, default=5.0,
                         help="Proporción máxima alto/ancho para considerar plausible (default: 5.0)")
    parser.add_argument("--device", type=str, default="auto", choices=["auto", "cpu", "gpu"],
                         help="Dispositivo de procesamiento a forzar (default: %(default)s). 'auto' deja "
                              "que Ultralytics elija GPU si hay disponible o CPU si no, igual que siempre.")
    return parser.parse_args()


def is_plausible_person_box(x1, y1, x2, y2, min_ratio, max_ratio):
    width = x2 - x1
    height = y2 - y1
    if width <= 0:
        return False
    ratio = height / width
    return min_ratio <= ratio <= max_ratio


def extract_wrists(kpts_xy_person, kpts_conf_person, keypoint_conf_threshold):
    """Devuelve una lista de (lado, x, y, conf) por CADA muñeca (izquierda
    y derecha) que supere el umbral de confianza -- a diferencia de un
    solo punto "elegido", ambas muñecas son puntos de contacto
    independientes con el estante, así que se conservan por separado.
    `kpts_xy_person` y `kpts_conf_person` son las 17 filas de keypoints de
    UNA sola persona (ya indexadas fuera de esta función)."""
    wrists = []
    for side, kp_idx in (("izquierda", LEFT_WRIST), ("derecha", RIGHT_WRIST)):
        x, y = kpts_xy_person[kp_idx]
        conf = kpts_conf_person[kp_idx] if kpts_conf_person is not None else 1.0
        if conf >= keypoint_conf_threshold and (x > 0 or y > 0):
            wrists.append((side, float(x), float(y), float(conf)))
    return wrists


def main():
    args = parse_args()
    video_path = args.video

    if not os.path.exists(video_path):
        print(f"ERROR: no se encontró el video en '{video_path}'")
        sys.exit(1)

    video_basename = os.path.splitext(os.path.basename(video_path))[0]
    output_body_csv = f"data/processed/tracks_{video_basename}.csv"
    output_hand_csv = f"data/processed/hands_{video_basename}.csv"
    output_keypoints_csv = f"data/processed/keypoints_{video_basename}.csv"
    output_video = f"data/processed/tracked_preview_{video_basename}.webm"

    os.makedirs("data/processed", exist_ok=True)

    try:
        device_value = resolve_device(args.device)
    except RuntimeError as e:
        print(f"ERROR: {e}")
        sys.exit(1)
    print(f"[Dispositivo] --device={args.device} -> "
          f"{'auto (elige Ultralytics)' if device_value is None else device_value}")

    model = load_model(MODEL_NAME, skip_openvino=should_skip_openvino(args.device))

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

    body_rows = []
    hand_rows = []
    keypoint_rows = []
    frame_idx = 0
    n_filtered_out = 0
    n_no_wrist = 0

    track_kwargs = dict(
        source=video_path,
        classes=[PERSON_CLASS_ID],
        conf=args.conf,
        persist=True,
        stream=True,
        tracker=args.tracker,
        verbose=False,
    )
    if device_value is not None:
        track_kwargs["device"] = device_value
    results = model.track(**track_kwargs)

    for result in results:
        timestamp = frame_idx / fps if fps > 0 else 0

        # Caja + esqueleto estilo Ultralytics (results.plot()) en vez de
        # redibujar todo a mano con cv2 -- acá SÍ existe el objeto Results
        # original, así que es la forma más simple y fiel de obtener el
        # mismo lenguaje visual que usa Ultralytics para modelos de pose.
        # NOTA: plot() dibuja TODAS las cajas que detectó el modelo, sin
        # pasar por el filtro opcional de aspect-ratio de abajo (que solo
        # afecta qué se GUARDA en el CSV) -- en la práctica solo importa
        # con --filter-aspect-ratio activo (cámaras de calle).
        annotated = result.plot(conf=True, line_width=2)

        if result.boxes is not None and result.boxes.id is not None:
            boxes = result.boxes.xyxy.cpu().numpy()
            track_ids = result.boxes.id.cpu().numpy().astype(int)
            confs = result.boxes.conf.cpu().numpy()

            has_keypoints = result.keypoints is not None
            kpts_xy = result.keypoints.xy.cpu().numpy() if has_keypoints else None
            kpts_conf = (result.keypoints.conf.cpu().numpy()
                         if has_keypoints and result.keypoints.conf is not None else None)

            for i, (box, track_id) in enumerate(zip(boxes, track_ids)):
                x1, y1, x2, y2 = box

                if args.filter_aspect_ratio:
                    if not is_plausible_person_box(x1, y1, x2, y2,
                                                    args.min_aspect_ratio,
                                                    args.max_aspect_ratio):
                        n_filtered_out += 1
                        continue

                x_center = (x1 + x2) / 2
                y_center = (y1 + y2) / 2

                body_rows.append({
                    "frame": frame_idx,
                    "timestamp": round(timestamp, 3),
                    "track_id": int(track_id),
                    "x_center": round(float(x_center), 1),
                    "y_center": round(float(y_center), 1),
                    "x1": round(float(x1), 1),
                    "y1": round(float(y1), 1),
                    "x2": round(float(x2), 1),
                    "y2": round(float(y2), 1),
                    "conf": round(float(confs[i]), 3),
                })

                person_kpts_xy = kpts_xy[i] if has_keypoints else None
                person_kpts_conf = kpts_conf[i] if (has_keypoints and kpts_conf is not None) else None

                wrists = []
                if has_keypoints:
                    wrists = extract_wrists(person_kpts_xy, person_kpts_conf, args.keypoint_conf)
                    keypoint_rows.append({
                        "frame": frame_idx,
                        "track_id": int(track_id),
                        **keypoints_to_row(person_kpts_xy, person_kpts_conf),
                    })
                    # Además del esqueleto completo que ya dibujó plot(),
                    # resalta ambas muñecas -- son el punto de contacto
                    # relevante para la interacción con el estante.
                    draw_wrist_markers(annotated, person_kpts_xy, person_kpts_conf, args.keypoint_conf)

                if not wrists:
                    n_no_wrist += 1
                    continue

                for side, wrist_x, wrist_y, wrist_conf in wrists:
                    hand_rows.append({
                        "frame": frame_idx,
                        "timestamp": round(timestamp, 3),
                        "track_id": int(track_id),
                        "x_center": round(wrist_x, 1),
                        "y_center": round(wrist_y, 1),
                        "x1": round(wrist_x - HAND_BOX_HALF_SIZE, 1),
                        "y1": round(wrist_y - HAND_BOX_HALF_SIZE, 1),
                        "x2": round(wrist_x + HAND_BOX_HALF_SIZE, 1),
                        "y2": round(wrist_y + HAND_BOX_HALF_SIZE, 1),
                        "conf": round(wrist_conf, 3),
                        "hand_side": side,
                    })

        writer.write(annotated)
        frame_idx += 1

    writer.release()

    with open(output_body_csv, "w", newline="") as f:
        writer_csv = csv.DictWriter(f, fieldnames=BODY_FIELDNAMES)
        writer_csv.writeheader()
        writer_csv.writerows(body_rows)

    with open(output_hand_csv, "w", newline="") as f:
        writer_csv = csv.DictWriter(f, fieldnames=HAND_FIELDNAMES)
        writer_csv.writeheader()
        writer_csv.writerows(hand_rows)

    with open(output_keypoints_csv, "w", newline="") as f:
        writer_csv = csv.DictWriter(f, fieldnames=KEYPOINT_FIELDNAMES)
        writer_csv.writeheader()
        writer_csv.writerows(keypoint_rows)

    n_unique_body_ids = len(set(r["track_id"] for r in body_rows))
    n_unique_hand_ids = len(set(r["track_id"] for r in hand_rows))

    print("Procesamiento completo (un solo modelo YOLO26-pose: cuerpo + ambas muñecas).")
    print(f"Tracks de cuerpo guardados en: {output_body_csv} "
          f"({len(body_rows)} detecciones, {n_unique_body_ids} IDs únicos)")
    print(f"Posiciones de muñeca guardadas en: {output_hand_csv} "
          f"({len(hand_rows)} filas -- hasta 2 por persona/frame, izquierda y derecha, "
          f"{n_unique_hand_ids} IDs únicos)")
    print(f"Keypoints completos (17 por detección) guardados en: {output_keypoints_csv} "
          f"({len(keypoint_rows)} filas)")
    if args.filter_aspect_ratio:
        print(f"Detecciones descartadas por filtro de proporción: {n_filtered_out}")
    print(f"Personas sin ninguna muñeca detectada con suficiente confianza: {n_no_wrist}")
    print(f"Video de verificación (caja + esqueleto estilo Ultralytics + ambas muñecas) en: {output_video}")


if __name__ == "__main__":
    main()
