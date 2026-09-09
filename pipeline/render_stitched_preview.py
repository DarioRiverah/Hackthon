"""
Genera un video de verificación usando los IDs ya "cosidos" (id_persona)
en vez de los track_ids originales fragmentados.

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

Uso:
    python pipeline\\render_stitched_preview.py --video data\\raw\\1_2_crop.mp4 --stitched-csv data\\processed\\tracks_1_2_crop_stitched.csv
"""

import argparse
import os
import string

import cv2
import pandas as pd

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
                         help="Video original correspondiente al CSV")
    parser.add_argument("--stitched-csv", type=str, required=True,
                         help="CSV generado por track_stitching.py (debe tener columna id_persona)")
    parser.add_argument("--output", type=str, default=None,
                         help="Ruta del video de salida (default: <stitched-csv>_verificacion.mp4)")
    parser.add_argument("--mode", type=str, default="auto", choices=["auto", "caja", "punto"],
                         help="'caja': dibuja rectángulo (apropiado para cuerpo completo). "
                              "'punto': dibuja círculo (apropiado para un keypoint como la muñeca). "
                              "'auto' (default): detecta según el tamaño típico de la caja en el CSV -- "
                              "las cajas de mano son mucho más pequeñas que las de cuerpo.")
    return parser.parse_args()


def detect_mode(df: pd.DataFrame) -> str:
    """Distingue automáticamente datos de CUERPO (caja grande, el
    contorno real de la persona) de datos de MANO (caja pequeña,
    generada artificialmente alrededor de un keypoint de muñeca) --
    comparando el ancho promedio de la caja contra un umbral. Una caja
    de cuerpo típica es de decenas a cientos de píxeles de ancho; una
    caja de muñeca es de unos pocos píxeles."""
    avg_width = (df["x2"] - df["x1"]).mean()
    return "punto" if avg_width < 40 else "caja"


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


def main():
    args = parse_args()

    if not os.path.exists(args.video):
        print(f"ERROR: no se encontró el video '{args.video}'")
        return
    if not os.path.exists(args.stitched_csv):
        print(f"ERROR: no se encontró el CSV '{args.stitched_csv}'")
        return

    output_path = args.output or args.stitched_csv.replace(".csv", "_verificacion.webm")

    df = pd.read_csv(args.stitched_csv)

    mode = detect_mode(df) if args.mode == "auto" else args.mode
    print(f"Modo de dibujo: {'punto (keypoint)' if mode == 'punto' else 'caja (cuerpo completo)'}")

    unique_ids = sorted(df["id_persona"].unique())
    colors = {pid: PALETTE_BGR[i % len(PALETTE_BGR)] for i, pid in enumerate(unique_ids)}
    labels = build_labels(unique_ids)

    detections_by_frame = df.groupby("frame")

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

    frame_idx = 0
    while True:
        ret, frame = cap.read()
        if not ret:
            break

        if frame_idx in detections_by_frame.groups:
            frame_detections = detections_by_frame.get_group(frame_idx)
            for _, row in frame_detections.iterrows():
                pid = row["id_persona"]
                color = colors[pid]
                label = labels[pid]
                x1, y1, x2, y2 = int(row["x1"]), int(row["y1"]), int(row["x2"]), int(row["y2"])
                cx, cy = (x1 + x2) // 2, (y1 + y2) // 2

                if mode == "punto":
                    cv2.circle(frame, (cx, cy), 8, color, -1)
                    cv2.putText(frame, label, (cx + 12, cy), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                else:
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, label, (x1, max(y1 - 8, 15)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)

        writer.write(frame)
        frame_idx += 1

    cap.release()
    writer.release()

    print(f"Video de verificación generado en: {output_path}")
    print(f"Total de trayectorias distintas identificadas: {len(unique_ids)}")
    print("Revisa: cada color/letra debería mantenerse igual para la misma persona en todo su recorrido.")
    print("(Las letras son solo para distinguir colores -- no representan una identificación de cliente.)")


if __name__ == "__main__":
    main()