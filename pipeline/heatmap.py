"""
Heatmap de flujo: visualiza dónde circula más/menos la gente.

A partir de las posiciones (x,y) de todas las personas detectadas a lo
largo del video, genera un mapa de calor superpuesto sobre un frame de
referencia -- esto responde directamente "zonas calientes vs frías",
la prioridad #1 definida para el reto.

No usa ninguna imagen de personas ni dato biométrico: solo las
coordenadas (x,y) ya calculadas por detect_and_track.py, agregadas
espacialmente.

Uso:
    python pipeline\\heatmap.py --video data\\raw\\1_2_crop.mp4 --tracks data\\processed\\tracks_1_2_crop.csv
    python pipeline\\heatmap.py --video data\\raw\\1_2_crop.mp4 --tracks data\\processed\\tracks_1_2_crop.csv --blur-radius 40
"""

import argparse
import json
import os
import cv2
import numpy as np
import pandas as pd


def parse_args():
    parser = argparse.ArgumentParser(description="Genera un heatmap de flujo a partir de posiciones de tracking.")
    parser.add_argument("--video", type=str, required=True, help="Video de referencia (para el frame de fondo)")
    parser.add_argument("--tracks", type=str, required=True, help="CSV de tracks (detect_and_track.py)")
    parser.add_argument("--zones", type=str, default=None,
                         help="JSON de zonas (opcional) -- si se pasa, dibuja los límites de zona sobre el heatmap")
    parser.add_argument("--frame-number", type=int, default=0, help="Frame a usar como fondo (default: 0)")
    parser.add_argument("--output", type=str, default=None,
                         help="Ruta de la imagen de salida (default: data/output/heatmap_<video>.png)")
    parser.add_argument("--blur-radius", type=int, default=35,
                         help="Radio de difuminado del heatmap en píxeles (default: 35). "
                              "Más alto = manchas de calor más suaves/amplias.")
    parser.add_argument("--opacity", type=float, default=0.6,
                         help="Opacidad del heatmap sobre el video de fondo, 0.0-1.0 (default: 0.6)")
    parser.add_argument("--no-legend", action="store_true", help="Omite la leyenda de color incrustada")
    parser.add_argument("--mode", type=str, default="flujo", choices=["flujo", "interaccion", "combinado"],
                         help="'flujo' (default): heatmap de posición corporal (tráfico/permanencia). "
                              "'interaccion': heatmap de posición de mano (qué se toca del estante) -- "
                              "usa --tracks apuntando a un CSV de manos (detect_hand_positions.py). "
                              "'combinado': color = tráfico corporal, contorno blanco = interacción de "
                              "mano -- requiere --tracks (cuerpo) y --hand-tracks (mano)")
    parser.add_argument("--hand-tracks", type=str, default=None,
                         help="CSV de posiciones de mano, requerido solo para --mode combinado")
    return parser.parse_args()


def draw_zone_boundaries(image: np.ndarray, zones_path: str) -> np.ndarray:
    """Superpone los límites de zona (desde un JSON de calibración) sobre
    el heatmap ya renderizado, con el nombre de cada zona visible -- así
    se ve de un vistazo qué zona corresponde a cada mancha de calor."""
    if not os.path.exists(zones_path):
        print(f"AVISO: no se encontró '{zones_path}', se omiten los límites de zona.")
        return image

    with open(zones_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    result = image.copy()
    for zone in config.get("zones", []):
        polygon = np.array(zone["polygon"], dtype=np.int32).reshape((-1, 1, 2))
        cv2.polylines(result, [polygon], isClosed=True, color=(255, 255, 255), thickness=2)

        pts = zone["polygon"]
        cx = int(sum(p[0] for p in pts) / len(pts))
        cy = int(sum(p[1] for p in pts) / len(pts))
        label = zone.get("label", zone.get("id", ""))
        # Fondo oscuro detrás del texto para que se lea bien sobre cualquier color del heatmap
        (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.6, 2)
        cv2.rectangle(result, (cx - 4, cy - text_h - 8), (cx + text_w + 4, cy + 4), (0, 0, 0), -1)
        cv2.putText(result, label, (cx, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)

    return result


def draw_legend(image: np.ndarray, subtitle: str = "Tiempo/trafico acumulado") -> np.ndarray:
    """Dibuja una leyenda de color incrustada directamente en la imagen
    (barra de gradiente azul->rojo con etiquetas), para que el
    significado de los colores no dependa de leer la consola aparte."""
    result = image.copy()
    h, w = result.shape[:2]

    bar_width = 200
    bar_height = 20
    margin = 15
    x0 = w - bar_width - margin
    y0 = h - bar_height - margin - 20  # espacio extra para el texto de abajo

    # Gradiente horizontal de la misma paleta usada en el heatmap (JET)
    gradient = np.linspace(0, 255, bar_width, dtype=np.uint8).reshape(1, -1)
    gradient = np.repeat(gradient, bar_height, axis=0)
    gradient_color = cv2.applyColorMap(gradient, cv2.COLORMAP_JET)

    # Medir el ancho real del subtítulo para dimensionar el fondo correctamente
    # y evitar que el texto se corte contra el borde de la imagen.
    (subtitle_w, _), _ = cv2.getTextSize(subtitle, cv2.FONT_HERSHEY_SIMPLEX, 0.4, 1)
    box_width = max(bar_width, subtitle_w) + 20
    x0 = w - box_width - margin + 10  # realinear la barra dentro de la caja más ancha si hace falta

    # Fondo oscuro semi-transparente detrás de toda la leyenda para que se lea bien
    overlay = result.copy()
    cv2.rectangle(overlay, (x0 - 10, y0 - 25), (x0 - 10 + box_width, y0 + bar_height + 15), (0, 0, 0), -1)
    result = cv2.addWeighted(overlay, 0.55, result, 0.45, 0)

    result[y0:y0 + bar_height, x0:x0 + bar_width] = gradient_color

    cv2.putText(result, "Frio", (x0, y0 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    cv2.putText(result, "Caliente", (x0 + bar_width - 65, y0 - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 255), 1)
    cv2.putText(result, subtitle, (x0 - 5, y0 + bar_height + 12),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4, (255, 255, 255), 1)

    return result


def render_combined_heatmap(frame: np.ndarray, body_density: np.ndarray, hand_density: np.ndarray,
                             opacity: float, interaction_threshold_pct: float = 0.6) -> np.ndarray:
    """Combina ambas señales en una sola imagen usando dos lenguajes
    visuales distintos, en vez de mezclar colores (que se vería
    confuso): el color de fondo (azul->rojo) sigue representando
    tráfico/permanencia corporal, y un CONTORNO blanco grueso marca las
    zonas de interacción de mano más intensas. Así se distingue "por
    dónde circula la gente" de "qué parte exacta del estante se toca"
    en una sola imagen."""
    base = render_heatmap(frame, body_density, opacity)

    hand_normalized = hand_density.copy()
    max_val = hand_normalized.max()
    if max_val > 0:
        hand_normalized = (hand_normalized / max_val * 255).astype(np.uint8)
    else:
        hand_normalized = hand_normalized.astype(np.uint8)

    threshold_value = int(255 * interaction_threshold_pct)
    _, mask = cv2.threshold(hand_normalized, threshold_value, 255, cv2.THRESH_BINARY)
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)

    result = base.copy()
    cv2.drawContours(result, contours, -1, (255, 255, 255), 3)

    # Etiqueta junto al contorno más grande, para dejar explícito qué representa
    if contours:
        largest = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(largest)
        label = "Interaccion de mano"
        (text_w, text_h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
        label_x, label_y = x, max(y - 10, text_h + 5)
        cv2.rectangle(result, (label_x - 3, label_y - text_h - 4), (label_x + text_w + 3, label_y + 4), (0, 0, 0), -1)
        cv2.putText(result, label, (label_x, label_y), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    return result


def build_density_map(df: pd.DataFrame, width: int, height: int, blur_radius: int) -> np.ndarray:
    """Construye un mapa de densidad 2D a partir de las posiciones, usando
    un acumulador simple + desenfoque gaussiano (equivalente a un KDE
    aproximado, mucho más barato de calcular)."""
    density = np.zeros((height, width), dtype=np.float32)

    xs = df["x_center"].clip(0, width - 1).astype(int).values
    ys = df["y_center"].clip(0, height - 1).astype(int).values

    for x, y in zip(xs, ys):
        density[y, x] += 1.0

    # El desenfoque gaussiano convierte los puntos individuales en "manchas"
    # de calor continuas -- así es como se ve un heatmap real, no solo puntos.
    ksize = blur_radius * 2 + 1  # debe ser impar
    density = cv2.GaussianBlur(density, (ksize, ksize), 0)

    return density


def render_heatmap(frame: np.ndarray, density: np.ndarray, opacity: float) -> np.ndarray:
    # Normalizar densidad a 0-255 para poder aplicar un colormap
    normalized = density.copy()
    max_val = normalized.max()
    if max_val > 0:
        normalized = (normalized / max_val * 255).astype(np.uint8)
    else:
        normalized = normalized.astype(np.uint8)

    # JET: azul (frío/poco tráfico) -> rojo (caliente/mucho tráfico)
    color_map = cv2.applyColorMap(normalized, cv2.COLORMAP_JET)

    # Solo mezclar donde realmente hay densidad (para no pintar de azul
    # sólido zonas donde nunca pasó nadie -- eso ensuciaría el video)
    mask = (normalized > 10).astype(np.float32)
    mask_3ch = cv2.merge([mask, mask, mask])

    blended = frame.astype(np.float32) * (1 - mask_3ch * opacity) + \
              color_map.astype(np.float32) * (mask_3ch * opacity)

    return blended.astype(np.uint8)


def main():
    args = parse_args()

    if not os.path.exists(args.video):
        print(f"ERROR: no se encontró el video '{args.video}'")
        return
    if not os.path.exists(args.tracks):
        print(f"ERROR: no se encontró el CSV '{args.tracks}'")
        return

    cap = cv2.VideoCapture(args.video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, args.frame_number)
    ret, frame = cap.read()
    height, width = frame.shape[:2]
    cap.release()

    if not ret:
        print(f"ERROR: no se pudo leer el frame {args.frame_number}")
        return

    df = pd.read_csv(args.tracks)
    if df.empty:
        print("ERROR: el CSV de tracks está vacío, no hay nada que graficar.")
        return

    print(f"Generando heatmap a partir de {len(df)} detecciones...")

    density = build_density_map(df, width, height, args.blur_radius)

    if args.mode == "combinado":
        if not args.hand_tracks:
            print("ERROR: --mode combinado requiere también --hand-tracks <csv_de_manos>")
            return
        if not os.path.exists(args.hand_tracks):
            print(f"ERROR: no se encontró el CSV de manos '{args.hand_tracks}'")
            return
        hand_df = pd.read_csv(args.hand_tracks)
        if hand_df.empty:
            print("ERROR: el CSV de manos está vacío.")
            return
        hand_density = build_density_map(hand_df, width, height, args.blur_radius)
        heatmap_img = render_combined_heatmap(frame, density, hand_density, args.opacity)
    else:
        heatmap_img = render_heatmap(frame, density, args.opacity)

    if args.zones:
        heatmap_img = draw_zone_boundaries(heatmap_img, args.zones)

    if not args.no_legend:
        if args.mode == "interaccion":
            subtitle = "Interaccion fisica (mano en estante)"
        elif args.mode == "combinado":
            subtitle = "Color=trafico corporal, contorno=interaccion de mano"
        else:
            subtitle = "Tiempo/trafico acumulado"
        heatmap_img = draw_legend(heatmap_img, subtitle=subtitle)

    video_basename = os.path.splitext(os.path.basename(args.video))[0]
    if args.mode == "interaccion":
        default_name = f"heatmap_manos_{video_basename}.png"
    elif args.mode == "combinado":
        default_name = f"heatmap_combinado_{video_basename}.png"
    else:
        default_name = f"heatmap_{video_basename}.png"
    output_path = args.output or f"data/output/{default_name}"
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    cv2.imwrite(output_path, heatmap_img)

    print(f"Heatmap guardado en: {output_path}")
    if args.mode == "interaccion":
        print("Interpretación: rojo = zona de alta interacción física con el estante, "
              "azul = poca interacción, sin color = nunca se tocó.")
    elif args.mode == "combinado":
        print("Interpretación: color de fondo = tráfico/permanencia corporal (azul frío -> rojo caliente). "
              "Contorno blanco = zona de mayor concentración de interacción de mano.")
    else:
        print("Interpretación: rojo = zona caliente (mucho tráfico/permanencia), "
              "azul = zona fría (poco tráfico), sin color = nunca visitada.")


if __name__ == "__main__":
    main()