"""
Diagrama de espagueti: dibuja la trayectoria REAL de todas las personas
(línea conectando sus posiciones cuadro a cuadro), a diferencia del
heatmap que muestra densidad acumulada por permanencia. Responde una
pregunta distinta: no "dónde se concentra la gente", sino "qué caminos
se recorren" -- útil para ver patrones de circulación (¿todos entran y
giran a la derecha? ¿hay una ruta que casi nadie usa?).

Todas las trayectorias se dibujan en un ÚNICO color, con transparencia
baja por trayectoria individual (overlay + cv2.addWeighted). Donde
varias personas siguen un recorrido parecido, la superposición de
líneas semitransparentes se ve más intensa/sólida -- ese es el efecto
buscado: revelar la TENDENCIA de circulación agregada, sin necesidad de
distinguir quién es quién. Antes se coloreaba cada id_persona con un
color distinto y una etiqueta ("Trayectoria A/B/C..."); se cambió a
este esquema agregado por la misma razón documentada en
docs/architecture.md sección 14 (y su continuación, sección 18): la
identificación de personas de este sistema no está validada para
escenas con varias personas simultáneas, así que distinguir
visualmente "la trayectoria de tal persona" sugeriría una certeza de
identificación que no podemos garantizar en el caso general.

Requiere un CSV de tracks ya cosidos (track_stitching.py), con columna
id_persona -- sin la costura, una sola persona podría verse como varias
trayectorias fragmentadas y confusas.

Uso:
    python pipeline\\spaghetti_diagram.py --video data\\raw\\1_2_crop.mp4 --tracks data\\processed\\tracks_1_2_crop_stitched.csv --zones config\\zones_merl_demo.json
"""

import argparse
import os

import cv2
import numpy as np
import pandas as pd

from heatmap import draw_zone_boundaries

# Único color para todas las trayectorias (BGR) -- un azul/celeste que se
# distingue bien tanto sobre el fondo atenuado como sobre los límites de
# zona (blancos) ya dibujados por heatmap.draw_zone_boundaries.
TRAJECTORY_COLOR = (214, 119, 40)

# Opacidad con la que cada trayectoria individual se combina con el
# overlay acumulado -- baja a propósito (0.30-0.40): así una sola
# trayectoria se ve tenue, pero donde varias coinciden en el mismo
# trayecto, blends sucesivos acercan esa zona al color pleno, dando el
# efecto de "más intenso = más común".
LINE_ALPHA = 0.35


def simplify_trajectory(points: list, min_distance: float) -> list:
    """Colapsa puntos consecutivos que están muy cerca entre sí en uno
    solo. Un diagrama de espagueti busca mostrar CIRCULACIÓN general, no
    cada micro-movimiento -- una persona parada frente al estante,
    moviendo la mano/cuerpo unos pocos píxeles repetidamente, genera un
    garabato denso e ilegible que no aporta nada a esa pregunta. Esto
    conserva el movimiento real (relocaciones genuinas) y descarta el
    ruido de estar prácticamente quieto."""
    if not points:
        return points
    simplified = [points[0]]
    for p in points[1:]:
        last = simplified[-1]
        dist = ((p[0] - last[0]) ** 2 + (p[1] - last[1]) ** 2) ** 0.5
        if dist >= min_distance:
            simplified.append(p)
    return simplified


def draw_trajectory_overlay(base: np.ndarray, trajectories: list, color: tuple,
                             line_thickness: int, line_alpha: float) -> np.ndarray:
    """Compone todas las trayectorias sobre `base` en un único color,
    combinando cada una con opacidad baja (`cv2.addWeighted`). Como cada
    trayectoria se funde con el resultado acumulado de las anteriores
    (no con la imagen original), un trayecto recorrido por varias
    personas queda notablemente más sólido que uno recorrido por una
    sola -- ese contraste es la señal visual de "recorrido común"."""
    composite = base.copy()
    for points in trajectories:
        if len(points) < 2:
            continue
        line_layer = composite.copy()
        for j in range(1, len(points)):
            cv2.line(line_layer, points[j - 1], points[j], color, line_thickness, lineType=cv2.LINE_AA)
        composite = cv2.addWeighted(line_layer, line_alpha, composite, 1 - line_alpha, 0)
    return composite


def parse_args():
    parser = argparse.ArgumentParser(description="Genera un diagrama de espagueti de trayectorias.")
    parser.add_argument("--video", type=str, required=True, help="Video de referencia")
    parser.add_argument("--tracks", type=str, required=True,
                         help="CSV de tracks YA COSIDOS (track_stitching.py), con columna id_persona")
    parser.add_argument("--zones", type=str, default=None, help="JSON de zonas (opcional, dibuja límites)")
    parser.add_argument("--id-column", type=str, default="id_persona",
                         help="Columna de identificador de persona (default: id_persona)")
    parser.add_argument("--frame-number", type=int, default=0, help="Frame a usar como fondo (default: 0)")
    parser.add_argument("--output", type=str, default=None, help="Ruta de salida")
    parser.add_argument("--line-thickness", type=int, default=2, help="Grosor de las líneas (default: 2)")
    parser.add_argument("--line-alpha", type=float, default=LINE_ALPHA,
                         help=f"Opacidad de cada trayectoria individual al combinarla con el overlay "
                              f"acumulado (default: {LINE_ALPHA}). Más bajo = hace falta que coincidan más "
                              f"personas en un mismo trayecto para que se vea sólido; más alto = una sola "
                              f"trayectoria ya se ve casi opaca.")
    parser.add_argument("--max-people", type=int, default=None,
                         help="Límite de personas a dibujar (default: todas). Útil si hay demasiadas "
                              "y el diagrama se vuelve ilegible -- dibuja las de trayectoria más larga.")
    parser.add_argument("--min-distance", type=float, default=15.0,
                         help="Distancia mínima en píxeles para considerar un movimiento real, en vez de "
                              "jitter mientras la persona está parada en un mismo lugar (default: 15.0). "
                              "Súbelo si el diagrama sigue viéndose enredado, bájalo si se ve demasiado "
                              "simplificado.")
    return parser.parse_args()


def main():
    args = parse_args()

    if not os.path.exists(args.video):
        print(f"ERROR: no se encontró el video '{args.video}'")
        return
    if not os.path.exists(args.tracks):
        print(f"ERROR: no se encontró el CSV '{args.tracks}'")
        return

    df = pd.read_csv(args.tracks)
    if args.id_column not in df.columns:
        print(f"ERROR: la columna '{args.id_column}' no existe en el CSV.")
        print(f"Columnas disponibles: {list(df.columns)}")
        print("Sugerencia: corre track_stitching.py primero si aún no lo hiciste.")
        return

    cap = cv2.VideoCapture(args.video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, args.frame_number)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        print(f"ERROR: no se pudo leer el frame {args.frame_number} del video.")
        return

    # Atenuar el frame de fondo para que las líneas resalten mejor
    dimmed = cv2.addWeighted(frame, 0.4, np.full_like(frame, 255), 0.6, 0)

    person_groups = list(df.groupby(args.id_column))

    if args.max_people:
        # Priorizar a las personas con trayectorias más largas (más informativas)
        person_groups.sort(key=lambda g: len(g[1]), reverse=True)
        person_groups = person_groups[:args.max_people]

    print(f"Dibujando trayectorias de {len(person_groups)} persona(s)...")

    trajectories = []
    total_raw, total_simplified = 0, 0
    for person_id, group in person_groups:
        group_sorted = group.sort_values("frame")
        raw_points = list(zip(group_sorted["x_center"].astype(int), group_sorted["y_center"].astype(int)))
        points = simplify_trajectory(raw_points, args.min_distance)
        total_raw += len(raw_points)
        total_simplified += len(points)
        trajectories.append(points)

    result = draw_trajectory_overlay(dimmed, trajectories, TRAJECTORY_COLOR,
                                      args.line_thickness, args.line_alpha)

    # Marcadores de inicio/fin de cada trayectoria, dibujados aparte (no a
    # través del overlay semitransparente) para que queden siempre nítidos
    # -- muestran de dónde entra y sale la gente en general, sin atribuir
    # ningún marcador a una persona identificada por nombre/letra.
    for points in trajectories:
        if not points:
            continue
        cv2.circle(result, points[0], 8, (0, 200, 0), -1)   # inicio: verde
        cv2.circle(result, points[-1], 8, (0, 0, 200), -1)  # fin: rojo

    if args.zones:
        result = draw_zone_boundaries(result, args.zones)

    cv2.putText(result, "Verde = inicio de recorridos, Rojo = fin -- mas intenso = recorrido mas comun",
                (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

    video_basename = os.path.splitext(os.path.basename(args.video))[0]
    output_path = args.output or f"data/output/spaghetti_{video_basename}.png"
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    cv2.imwrite(output_path, result)

    print(f"Diagrama guardado en: {output_path}")
    if total_raw > 0:
        pct_reduced = (1 - total_simplified / total_raw) * 100
        print(f"Puntos simplificados: {total_raw} -> {total_simplified} ({pct_reduced:.0f}% de reducción, "
              f"umbral de {args.min_distance}px)")


if __name__ == "__main__":
    main()
