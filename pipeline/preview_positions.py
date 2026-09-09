"""
Genera una imagen de referencia mostrando TODAS las posiciones detectadas
(puntos) superpuestas sobre un frame del video. Esto sirve para calibrar
zonas viendo exactamente dónde aparecen las personas en la escena, en vez
de adivinar mirando solo un frame estático (que puede no mostrar a nadie
en la zona de interés).

Uso:
    python pipeline\\preview_positions.py --video data\\raw\\1_2_crop.mp4 --tracks data\\processed\\tracks_1_2_crop.csv
"""

import argparse
import os
import cv2
import pandas as pd


def parse_args():
    parser = argparse.ArgumentParser(description="Visualiza todas las posiciones detectadas sobre un frame del video.")
    parser.add_argument("--video", type=str, required=True, help="Video de referencia")
    parser.add_argument("--tracks", type=str, required=True, help="CSV de tracks (detect_and_track.py)")
    parser.add_argument("--frame-number", type=int, default=0, help="Frame a usar como fondo (default: 0)")
    parser.add_argument("--output", type=str, default="data/processed/positions_preview.png",
                         help="Ruta de la imagen de salida")
    return parser.parse_args()


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
    cap.release()

    if not ret:
        print(f"ERROR: no se pudo leer el frame {args.frame_number}")
        return

    df = pd.read_csv(args.tracks)

    overlay = frame.copy()
    for _, row in df.iterrows():
        x, y = int(row["x_center"]), int(row["y_center"])
        cv2.circle(overlay, (x, y), 4, (0, 0, 255), -1)

    blended = cv2.addWeighted(overlay, 0.5, frame, 0.5, 0)

    x_min, x_max = int(df["x_center"].min()), int(df["x_center"].max())
    y_min, y_max = int(df["y_center"].min()), int(df["y_center"].max())
    cv2.rectangle(blended, (x_min, y_min), (x_max, y_max), (0, 255, 255), 2)
    cv2.putText(blended, f"Rango de posiciones: X[{x_min}-{x_max}] Y[{y_min}-{y_max}]",
                (10, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    cv2.imwrite(args.output, blended)

    print(f"Imagen de referencia guardada en: {args.output}")
    print(f"Rango real de posiciones -> X: [{x_min}, {x_max}]  Y: [{y_min}, {y_max}]")
    print("Abre esa imagen: los puntos rojos muestran TODO lugar donde se detectó a alguien.")
    print("El rectángulo amarillo marca el área total cubierta -- dibuja tu zona DENTRO de ese rango.")


if __name__ == "__main__":
    main()