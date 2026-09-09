"""
Heatmap usando el módulo OFICIAL de Ultralytics (solutions.Heatmap),
para comparar contra nuestra implementación casera (pipeline/heatmap.py).

Referencia: https://docs.ultralytics.com/guides/heatmaps

Este script existe para comparación/validación (Fase 2 de la
reestructuración) -- no reemplaza heatmap.py a menos que la comparación
muestre que es claramente mejor.

Uso:
    python pipeline\\heatmap_ultralytics.py --video data\\raw\\1_2_crop.mp4
"""

import argparse
import os

import cv2
from ultralytics import solutions

MODEL_NAME = "yolo26s.pt"


def parse_args():
    parser = argparse.ArgumentParser(description="Heatmap usando el módulo oficial de Ultralytics.")
    parser.add_argument("--video", type=str, required=True, help="Video a procesar")
    parser.add_argument("--output", type=str, default=None,
                         help="Ruta de la imagen final de heatmap (default: data/output/heatmap_ultralytics_<video>.png)")
    parser.add_argument("--conf", type=float, default=0.2, help="Umbral de confianza (default: 0.2)")
    parser.add_argument("--tracker", type=str, default="pipeline/custom_bytetrack.yaml",
                         help="Tracker a usar (default: nuestra config personalizada, afinada para vista "
                              "cenital -- tanto botsort.yaml como bytetrack.yaml genéricos dieron "
                              "'No tracks found' en nuestras pruebas con este video)")
    return parser.parse_args()


def main():
    args = parse_args()

    if not os.path.exists(args.video):
        print(f"ERROR: no se encontró el video '{args.video}'")
        return

    video_basename = os.path.splitext(os.path.basename(args.video))[0]
    output_path = args.output or f"data/output/heatmap_ultralytics_{video_basename}.png"
    os.makedirs("data/output", exist_ok=True)

    cap = cv2.VideoCapture(args.video)
    if not cap.isOpened():
        print(f"ERROR: no se pudo abrir el video '{args.video}'")
        return

    heatmap = solutions.Heatmap(
        model=MODEL_NAME,
        classes=[0],  # solo personas
        conf=args.conf,
        tracker=args.tracker,
        colormap=cv2.COLORMAP_JET,
        show=False,
    )

    last_frame = None
    n_frames = 0

    while True:
        ret, frame = cap.read()
        if not ret:
            break
        results = heatmap.process(frame)
        last_frame = results.plot_im
        n_frames += 1

    cap.release()

    if last_frame is None:
        print("ERROR: no se procesó ningún frame del video.")
        return

    cv2.imwrite(output_path, last_frame)
    print(f"Heatmap oficial de Ultralytics generado a partir de {n_frames} frames.")
    print(f"Guardado en: {output_path}")
    print(f"Compáralo visualmente contra: data/output/heatmap_{video_basename}.png (nuestra versión casera)")


if __name__ == "__main__":
    main()