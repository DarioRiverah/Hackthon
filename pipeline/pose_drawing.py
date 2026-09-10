"""
Utilidades compartidas para dibujar poses estilo Ultralytics (caja +
esqueleto COCO-17 con huesos de color por grupo anatómico) y para
serializar/leer los 17 keypoints por detección en CSV.

Usado por detect_and_track.py (donde SÍ existe un objeto Results real de
Ultralytics, así que además se puede llamar result.plot() directamente
para el video crudo) y por render_stitched_preview.py (donde ya NO hay
objeto Results -- solo CSVs post-costura de IDs -- así que el esqueleto
se redibuja a mano con estas funciones, reutilizando el mismo esquema de
colores/huesos).
"""

import cv2
import numpy as np

NUM_KEYPOINTS = 17

# Índices de keypoints COCO-pose (formato estándar de Ultralytics)
LEFT_WRIST = 9
RIGHT_WRIST = 10

# Huesos del esqueleto COCO-17 estándar (índices base-0, equivalente al
# `skeleton` que usa Ultralytics internamente en Annotator.kpts, restando
# 1 a cada índice porque esa lista de referencia es base-1).
SKELETON_BONES = [
    (15, 13), (13, 11), (16, 14), (14, 12), (11, 12),
    (5, 11), (6, 12), (5, 6),
    (3, 5), (4, 6),
    (0, 1), (0, 2), (1, 2), (1, 3), (2, 4),
    (5, 7), (7, 9), (6, 8), (8, 10),
    (11, 13), (13, 15), (12, 14), (14, 16),
]

# Agrupación anatómica para el color (cabeza/cara, torso, extremidades),
# tal como pidió el reto -- no es exactamente la paleta interna de
# Ultralytics (que no vale la pena replicar de memoria pixel a pixel),
# pero sí el mismo lenguaje visual: huesos y puntos coloreados por zona
# del cuerpo, sobre caja + confianza.
HEAD_BONES = {(0, 1), (0, 2), (1, 2), (1, 3), (2, 4)}
TORSO_BONES = {(5, 6), (5, 11), (6, 12), (11, 12), (3, 5), (4, 6)}
# Todo lo demás en SKELETON_BONES (brazos y piernas) se colorea como extremidad.

HEAD_KEYPOINTS = {0, 1, 2, 3, 4}
TORSO_KEYPOINTS = {5, 6, 11, 12}
# El resto (7,8,9,10,13,14,15,16) son extremidades.

COLOR_HEAD = (0, 215, 255)    # BGR: amarillo/dorado
COLOR_TORSO = (255, 200, 0)   # BGR: celeste
COLOR_LIMB = (0, 140, 255)    # BGR: naranja
COLOR_WRIST = (255, 0, 255)   # BGR: magenta -- resalta AMBAS muñecas


def _bone_color(a, b):
    if (a, b) in HEAD_BONES:
        return COLOR_HEAD
    if (a, b) in TORSO_BONES:
        return COLOR_TORSO
    return COLOR_LIMB


def _keypoint_color(idx):
    if idx in HEAD_KEYPOINTS:
        return COLOR_HEAD
    if idx in TORSO_KEYPOINTS:
        return COLOR_TORSO
    return COLOR_LIMB


def _is_visible(kpts_xy, kpts_conf, idx, conf_threshold):
    x, y = kpts_xy[idx]
    conf = kpts_conf[idx] if kpts_conf is not None else 1.0
    return conf >= conf_threshold and (x > 0 or y > 0)


def draw_skeleton(frame, kpts_xy, kpts_conf, conf_threshold=0.3):
    """Dibuja el esqueleto completo (huesos + puntos, coloreados por zona
    del cuerpo) de UNA persona. `kpts_xy`: array (17,2). `kpts_conf`:
    array (17,) o None (si no hay confianza por-keypoint, se asume
    visible)."""
    for a, b in SKELETON_BONES:
        if _is_visible(kpts_xy, kpts_conf, a, conf_threshold) and \
           _is_visible(kpts_xy, kpts_conf, b, conf_threshold):
            pt_a = (int(kpts_xy[a][0]), int(kpts_xy[a][1]))
            pt_b = (int(kpts_xy[b][0]), int(kpts_xy[b][1]))
            cv2.line(frame, pt_a, pt_b, _bone_color(a, b), 2, cv2.LINE_AA)

    for idx in range(len(kpts_xy)):
        if _is_visible(kpts_xy, kpts_conf, idx, conf_threshold):
            x, y = kpts_xy[idx]
            cv2.circle(frame, (int(x), int(y)), 3, _keypoint_color(idx), -1, cv2.LINE_AA)


def draw_wrist_markers(frame, kpts_xy, kpts_conf, conf_threshold=0.3, radius=8):
    """Dibuja un punto grande y bien visible sobre CADA muñeca detectada
    (izquierda y derecha, por separado) -- ambas son puntos de contacto
    relevantes para la interacción con el estante, no solo una."""
    for idx in (LEFT_WRIST, RIGHT_WRIST):
        if _is_visible(kpts_xy, kpts_conf, idx, conf_threshold):
            x, y = kpts_xy[idx]
            center = (int(x), int(y))
            cv2.circle(frame, center, radius, COLOR_WRIST, -1, cv2.LINE_AA)
            cv2.circle(frame, center, radius, (0, 0, 0), 1, cv2.LINE_AA)


def draw_box_with_label(frame, x1, y1, x2, y2, color, label):
    """Caja delimitadora + etiqueta con fondo de color, estilo Ultralytics
    (el mismo lenguaje visual que results.plot(), pero dibujado a mano
    porque acá ya no existe un objeto Results de Ultralytics)."""
    x1, y1, x2, y2 = int(x1), int(y1), int(x2), int(y2)
    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2, cv2.LINE_AA)

    (text_w, text_h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 2)
    label_y0 = max(y1 - text_h - baseline - 4, 0)
    cv2.rectangle(frame, (x1, label_y0), (x1 + text_w + 6, label_y0 + text_h + baseline + 4), color, -1)
    cv2.putText(frame, label, (x1 + 3, label_y0 + text_h + 2),
                cv2.FONT_HERSHEY_SIMPLEX, 0.55, (255, 255, 255), 2, cv2.LINE_AA)


def keypoint_field_names():
    """Nombres de columna para los 17 keypoints en el CSV (kp0_x, kp0_y,
    kp0_conf, kp1_x, ...)."""
    cols = []
    for i in range(NUM_KEYPOINTS):
        cols += [f"kp{i}_x", f"kp{i}_y", f"kp{i}_conf"]
    return cols


def keypoints_to_row(kpts_xy_person, kpts_conf_person):
    """Aplana los keypoints (17,2) + (17,) de UNA persona a un dict listo
    para csv.DictWriter."""
    row = {}
    for i in range(NUM_KEYPOINTS):
        x, y = kpts_xy_person[i]
        conf = kpts_conf_person[i] if kpts_conf_person is not None else 1.0
        row[f"kp{i}_x"] = round(float(x), 1)
        row[f"kp{i}_y"] = round(float(y), 1)
        row[f"kp{i}_conf"] = round(float(conf), 3)
    return row


def row_to_keypoints(row):
    """Reconstruye (kpts_xy, kpts_conf) como arrays numpy (17,2) y (17,)
    a partir de una fila del CSV de keypoints (dict o pandas.Series)."""
    kpts_xy = np.zeros((NUM_KEYPOINTS, 2), dtype=np.float32)
    kpts_conf = np.zeros(NUM_KEYPOINTS, dtype=np.float32)
    for i in range(NUM_KEYPOINTS):
        kpts_xy[i, 0] = row[f"kp{i}_x"]
        kpts_xy[i, 1] = row[f"kp{i}_y"]
        kpts_conf[i] = row[f"kp{i}_conf"]
    return kpts_xy, kpts_conf
