"""
Genera un video de verificación usando los IDs ya "cosidos" (id_persona)
en vez de los track_ids originales fragmentados -- caja de cuerpo
completo, esqueleto estilo Ultralytics (huesos + puntos por zona del
cuerpo) y AMBAS muñecas superpuestos en el MISMO video, más un mapa de
calor de tráfico que se va acumulando en vivo cuadro a cuadro conforme
avanza el video (antes se generaban dos videos separados -- uno para
cuerpo y otro para manos -- y el heatmap era solo una imagen estática
aparte al final).

Esto permite confirmar VISUALMENTE si la costura de tracks funcionó bien:
si ves que el mismo color/letra acompaña a la misma persona durante todo
su recorrido (incluso cuando se detiene frente al estante), la costura
está funcionando. Si ves colores distintos para la misma persona en
momentos distintos, hay que ajustar los parámetros de track_stitching.py.

NOTA DE DISEÑO: las etiquetas son letras genéricas (A, B, C...), NO el
número de id_persona ni la palabra "Persona X". Este video es una
herramienta de VERIFICACIÓN DE CONTINUIDAD DE TRACKING (¿el algoritmo
mantiene el mismo color en la misma persona?), no una identificación de
clientes -- ver docs/architecture.md sección 14 sobre por qué evitamos
presentar la identificación de personas como algo más certero de lo que
realmente es.

Sobre el esqueleto: este script ya NO tiene acceso al objeto Results
original de Ultralytics (el video se reconstruye a partir de los CSV
post-costura), así que el esqueleto se redibuja a mano con
pipeline/pose_drawing.py -- misma lógica de huesos/colores que usa
detect_and_track.py (que sí puede llamar results.plot() directamente).
Requiere el CSV de keypoints (data/processed/keypoints_<video>.csv,
generado por detect_and_track.py); si no existe, se cae de vuelta al
dibujo simple de un punto por muñeca a partir del CSV de manos.

Sobre el heatmap en vivo: reutiliza la misma función de color/densidad
de pipeline/heatmap.py (render_heatmap), pero en vez de calcular la
densidad de todo el video de una sola pasada, la acumula cuadro a cuadro
(cada posición de cuerpo detectada se suma al mapa de densidad ANTES de
dibujar ese cuadro) -- así el mapa de calor "crece" en vivo igual que
crecería la evidencia real de tráfico mientras se reproduce el video.
Se mezcla con transparencia (--heatmap-opacity) para no tapar el video
original.

Uso:
    python pipeline\\render_stitched_preview.py --video data\\raw\\1_2_crop.mp4 \\
        --body-csv data\\processed\\tracks_1_2_crop_stitched.csv \\
        --hand-csv data\\processed\\hands_1_2_crop_stitched.csv
"""

import argparse
import os
import string
import sys

import cv2
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from pose_drawing import draw_skeleton, draw_wrist_markers, draw_box_with_label, row_to_keypoints
from heatmap import render_heatmap

# Paleta "Tableau 10", una paleta categórica profesional y bien
# distinguible -- en BGR (OpenCV), no RGB.
PALETTE_BGR = [
    (180, 119, 31), (14, 127, 255), (44, 160, 44), (40, 39, 214),
    (189, 103, 148), (75, 86, 140), (194, 119, 227), (127, 127, 127),
    (34, 189, 188), (207, 190, 23),
]


def parse_args():
    parser = argparse.ArgumentParser(description="Renderiza preview con IDs corregidos por costura.")
    parser.add_argument("--video", type=str, required=True,
                         help="Video original correspondiente a los CSV")
    parser.add_argument("--body-csv", type=str, required=True,
                         help="CSV de tracks de CUERPO generado por track_stitching.py "
                              "(debe tener columna id_persona) -- se dibuja como caja")
    parser.add_argument("--hand-csv", type=str, default=None,
                         help="CSV de posiciones de MANO generado por track_stitching.py "
                              "(debe tener columna id_persona) -- OPCIONAL, se usa solo como "
                              "respaldo si no hay CSV de keypoints. Se omite con --skip-hands "
                              "en run_pipeline.py")
    parser.add_argument("--keypoints-csv", type=str, default=None,
                         help="CSV de keypoints generado por detect_and_track.py (default: se "
                              "infiere de --video, data/processed/keypoints_<video>.csv). Si "
                              "existe, se usa para dibujar el esqueleto completo estilo "
                              "Ultralytics; si no, el video solo muestra caja de cuerpo (+ "
                              "puntos de mano si hay --hand-csv).")
    parser.add_argument("--keypoint-conf", type=float, default=0.3,
                         help="Confianza mínima por keypoint para dibujarlo (default: 0.3)")
    parser.add_argument("--output", type=str, default=None,
                         help="Ruta del video de salida (default: <body-csv>_verificacion.webm)")
    parser.add_argument("--no-heatmap", action="store_true",
                         help="Desactiva el mapa de calor acumulado en vivo (solo caja/esqueleto)")
    parser.add_argument("--heatmap-opacity", type=float, default=0.45,
                         help="Opacidad del heatmap en vivo sobre el video, 0.0-1.0 (default: 0.45)")
    parser.add_argument("--heatmap-blur-radius", type=int, default=35,
                         help="Radio de difuminado del heatmap en vivo, en píxeles (default: 35, "
                              "misma escala que --blur-radius en heatmap.py)")
    return parser.parse_args()


def build_labels(unique_ids: list) -> dict:
    """Asigna una letra genérica (A, B, C...) a cada id_persona -- nunca
    el número de id_persona ni 'Persona X', para no sugerir una
    identificación de cliente que no podemos garantizar."""
    letters = list(string.ascii_uppercase)
    labels = {}
    for i, pid in enumerate(unique_ids):
        if i < len(letters):
            labels[pid] = letters[i]
        else:
            # Más de 26 tracks simultáneos sería inusual, pero por si acaso
            labels[pid] = f"{letters[i % 26]}{i // 26}"
    return labels


def build_color_and_label_maps(df: pd.DataFrame):
    unique_ids = sorted(df["id_persona"].unique())
    colors = {pid: PALETTE_BGR[i % len(PALETTE_BGR)] for i, pid in enumerate(unique_ids)}
    labels = build_labels(unique_ids)
    return unique_ids, colors, labels


def draw_body_detections(frame, frame_detections, colors, labels):
    for _, row in frame_detections.iterrows():
        pid = row["id_persona"]
        color = colors[pid]
        label = labels[pid]
        conf = row.get("conf")
        if conf is not None and not pd.isna(conf):
            label = f"{label} {conf:.2f}"
        x1, y1, x2, y2 = row["x1"], row["y1"], row["x2"], row["y2"]
        draw_box_with_label(frame, x1, y1, x2, y2, color, label)


def draw_hand_detections(frame, frame_detections, colors, labels):
    """Respaldo cuando no hay CSV de keypoints: un punto grande por cada
    fila de mano del cuadro (ya no una sola combinada -- si el CSV trae
    izquierda Y derecha, se dibujan ambas)."""
    for _, row in frame_detections.iterrows():
        pid = row["id_persona"]
        color = colors[pid]
        label = labels[pid]
        x1, y1, x2, y2 = row["x1"], row["y1"], row["x2"], row["y2"]
        cx, cy = int((x1 + x2) / 2), int((y1 + y2) / 2)
        cv2.circle(frame, (cx, cy), 8, color, -1)
        cv2.putText(frame, label, (cx + 12, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)


def draw_skeleton_detections(frame, frame_keypoints, keypoint_conf):
    """Dibuja el esqueleto completo (huesos + puntos por zona del cuerpo)
    y resalta ambas muñecas, para cada persona presente en este cuadro."""
    for _, row in frame_keypoints.iterrows():
        kpts_xy, kpts_conf = row_to_keypoints(row)
        draw_skeleton(frame, kpts_xy, kpts_conf, keypoint_conf)
        draw_wrist_markers(frame, kpts_xy, kpts_conf, keypoint_conf)


def main():
    args = parse_args()

    if not os.path.exists(args.video):
        print(f"ERROR: no se encontró el video '{args.video}'")
        return
    if not os.path.exists(args.body_csv):
        print(f"ERROR: no se encontró el CSV de cuerpo '{args.body_csv}'")
        return
    if args.hand_csv and not os.path.exists(args.hand_csv):
        print(f"ERROR: no se encontró el CSV de manos '{args.hand_csv}'")
        return

    output_path = args.output or args.body_csv.replace(".csv", "_verificacion.webm")

    body_df = pd.read_csv(args.body_csv)
    _, body_colors, body_labels = build_color_and_label_maps(body_df)
    body_by_frame = body_df.groupby("frame")

    hand_df = None
    hand_by_frame = None
    if args.hand_csv:
        hand_df = pd.read_csv(args.hand_csv)
        _, hand_colors, hand_labels = build_color_and_label_maps(hand_df)
        hand_by_frame = hand_df.groupby("frame")

    video_basename = os.path.splitext(os.path.basename(args.video))[0]
    keypoints_csv = args.keypoints_csv or f"data/processed/keypoints_{video_basename}.csv"
    keypoints_by_frame = None
    if os.path.exists(keypoints_csv):
        keypoints_df = pd.read_csv(keypoints_csv)
        # Los keypoints se guardaron con el track_id CRUDO (pre-costura) --
        # se unen contra body_df para saber a qué id_persona final
        # corresponden (la posición no cambia con la costura, solo la
        # identidad/color/letra que se le asigna).
        keypoints_df = keypoints_df.merge(
            body_df[["frame", "track_id", "id_persona"]], on=["frame", "track_id"], how="inner"
        )
        keypoints_by_frame = keypoints_df.groupby("frame")
    elif not args.hand_csv:
        print(f"AVISO: no se encontró '{keypoints_csv}' ni --hand-csv -- el video solo tendrá cajas de cuerpo.")
    else:
        print(f"AVISO: no se encontró '{keypoints_csv}' -- se usa el respaldo de puntos de mano del CSV.")

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # VP8/WebM en vez de mp4v: el contenedor .mp4 con códec mp4v (MPEG-4
    # Part 2, no H.264) no lo reproducen los navegadores nativamente --
    # causa el error "no se ha encontrado un video con formato/tipo MIME
    # compatible" en st.video(). H.264 real (avc1) tampoco es una opción
    # confiable aquí: requiere la DLL de OpenH264 (con licencia Cisco),
    # que esta build de OpenCV/FFmpeg no trae -- confirmado, no asumido:
    # al forzar avc1 el encoder falla en silencio ("Unable to create
    # encoder") y el archivo queda con metadata inconsistente. VP8, en
    # cambio, sí viene funcional (libvpx no tiene esa restricción de
    # licencia) y es compatible nativamente con todos los navegadores
    # modernos.
    writer = cv2.VideoWriter(
        output_path, cv2.VideoWriter_fourcc(*"VP80"), fps, (width, height)
    )

    # Mapa de densidad de posiciones de cuerpo, acumulado cuadro a cuadro
    # -- misma lógica de heatmap.py (acumulador + desenfoque gaussiano),
    # pero recalculado sobre el acumulador CRECIENTE en cada cuadro en vez
    # de una sola vez al final sobre el CSV completo.
    heatmap_enabled = not args.no_heatmap
    density_accum = np.zeros((height, width), dtype=np.float32) if heatmap_enabled else None
    has_any_point = False
    blur_ksize = args.heatmap_blur_radius * 2 + 1  # debe ser impar

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if heatmap_enabled and frame_idx in body_by_frame.groups:
            frame_bodies = body_by_frame.get_group(frame_idx)
            xs = frame_bodies["x_center"].clip(0, width - 1).astype(int).values
            ys = frame_bodies["y_center"].clip(0, height - 1).astype(int).values
            for x, y in zip(xs, ys):
                density_accum[y, x] += 1.0
                has_any_point = True

        if heatmap_enabled and has_any_point:
            blurred = cv2.GaussianBlur(density_accum, (blur_ksize, blur_ksize), 0)
            frame = render_heatmap(frame, blurred, args.heatmap_opacity)

        if frame_idx in body_by_frame.groups:
            draw_body_detections(frame, body_by_frame.get_group(frame_idx), body_colors, body_labels)

        if keypoints_by_frame is not None and frame_idx in keypoints_by_frame.groups:
            draw_skeleton_detections(frame, keypoints_by_frame.get_group(frame_idx), args.keypoint_conf)
        elif hand_by_frame is not None and frame_idx in hand_by_frame.groups:
            draw_hand_detections(frame, hand_by_frame.get_group(frame_idx), hand_colors, hand_labels)

        writer.write(frame)
        frame_idx += 1

    cap.release()
    writer.release()

    n_body_ids = body_df["id_persona"].nunique()
    print(f"Video de verificación generado en: {output_path}")
    print(f"Total de trayectorias de cuerpo distintas identificadas: {n_body_ids}")
    if hand_df is not None:
        n_hand_ids = hand_df["id_persona"].nunique()
        print(f"Total de trayectorias de mano distintas identificadas: {n_hand_ids}")
    if keypoints_by_frame is not None:
        print("Esqueleto completo (estilo Ultralytics) y ambas muñecas dibujados a partir de keypoints_*.csv.")
    if heatmap_enabled:
        print(f"Mapa de calor de tráfico acumulado en vivo sobre el video (opacidad {args.heatmap_opacity}).")
    print("Revisa: cada color/letra debería mantenerse igual para la misma persona en todo su recorrido.")
    print("(Las letras son solo para distinguir colores -- no representan una identificación de cliente.)")


if __name__ == "__main__":
    main()
