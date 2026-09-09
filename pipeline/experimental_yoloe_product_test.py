"""
PRUEBA EXPERIMENTAL Y ACOTADA -- no es parte del pipeline de producción.

Evalúa si YOLOE-26 (detección de vocabulario abierto, sin entrenamiento)
puede distinguir "mano con producto" de "mano vacía" -- el ingrediente
que faltaría para estimar pickup vs. putback.

Extrae frames de momentos donde YA SABEMOS que hay interacción real
(según nuestro propio interaction_events_*.csv, ya validado), y corre
YOLOE-26 con un vocabulario de texto sobre esos frames específicos,
para ver si el resultado es remotemente plausible antes de invertir
más tiempo construyendo lógica encima de esto.

Uso:
    python pipeline\\experimental_yoloe_product_test.py --video data\\raw\\1_2_crop.mp4 --events data\\output\\interaction_events_merl_demo.csv
"""

import argparse
import os

import cv2
import pandas as pd
from ultralytics import YOLOE

MODEL_NAME = "yoloe-26s-seg.pt"
# Último intento: vocabulario concreto (sustantivos de objetos reales) en vez
# de categorías abstractas como "product", que dieron 0 detecciones.
VOCABULARY = ["bottle", "box", "bag", "can", "package", "person", "hand"]


def parse_args():
    parser = argparse.ArgumentParser(description="Prueba experimental de YOLOE-26 para producto en mano.")
    parser.add_argument("--video", type=str, required=True, help="Video de referencia")
    parser.add_argument("--events", type=str, required=True,
                         help="CSV de interaction_events ya generado, para saber en qué segundos mirar")
    parser.add_argument("--conf", type=float, default=0.08,
                         help="Umbral de confianza (default: 0.08, bajado tras 0 detecciones con 0.15)")
    parser.add_argument("--n-events", type=int, default=3,
                         help="Cuántos eventos de interacción probar (default: 3)")
    return parser.parse_args()


def main():
    args = parse_args()

    if not os.path.exists(args.video) or not os.path.exists(args.events):
        print("ERROR: falta el video o el CSV de eventos.")
        return

    events_df = pd.read_csv(args.events)
    if events_df.empty:
        print("ERROR: el CSV de eventos está vacío.")
        return

    # Elegir eventos de distinta intensidad para tener variedad en la prueba
    events_df = events_df.sort_values("duration_seconds", ascending=False)
    sample_events = events_df.head(args.n_events)

    model = YOLOE(MODEL_NAME)
    model.set_classes(VOCABULARY, model.get_text_pe(VOCABULARY))

    cap = cv2.VideoCapture(args.video)
    fps = cap.get(cv2.CAP_PROP_FPS)

    os.makedirs("data/processed/yoloe_test", exist_ok=True)

    for idx, row in sample_events.iterrows():
        # Miramos en la mitad del evento, momento más probable de "agarre firme"
        mid_time = (row["start_time"] + row["end_time"]) / 2
        frame_idx = int(mid_time * fps)
        cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = cap.read()
        if not ret:
            continue

        results = model.predict(frame, conf=args.conf, verbose=False)
        result = results[0]

        annotated = result.plot()
        output_path = f"data/processed/yoloe_test/evento_{idx}_t{mid_time:.1f}s.png"
        cv2.imwrite(output_path, annotated)

        n_detections = len(result.boxes) if result.boxes is not None else 0
        detected_classes = []
        if result.boxes is not None:
            for cls_id in result.boxes.cls.cpu().numpy():
                detected_classes.append(VOCABULARY[int(cls_id)])

        print(f"Evento en t={mid_time:.1f}s (duración {row['duration_seconds']:.1f}s, "
              f"clasificado como '{row.get('intensity', 'N/A')}'):")
        print(f"  Detecciones: {n_detections} -> {detected_classes}")
        print(f"  Imagen guardada en: {output_path}")
        print()

    cap.release()
    print("Prueba completa. Revisa las imágenes en data/processed/yoloe_test/ para juzgar si las")
    print("detecciones tienen sentido visual -- esto decide si vale la pena seguir por este camino.")


if __name__ == "__main__":
    main()