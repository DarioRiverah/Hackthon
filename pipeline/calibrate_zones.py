"""
Herramienta de calibración de zonas.

Permite definir, con clics del mouse sobre un frame del video, los
polígonos de las zonas/góndolas de una tienda. El resultado se guarda
en un archivo JSON reutilizable por el resto del pipeline (zonificación,
heatmap, dwell time, layout personalizado).

Esto es lo que hace que el sistema sea escalable a cualquier tienda:
cambiar de video/cámara solo requiere volver a correr esta calibración,
sin tocar ni una línea de código del pipeline.

Controles:
    - Clic izquierdo: agregar un punto al polígono de la zona actual
    - Tecla 'n': cerrar la zona actual (mínimo 3 puntos) y empezar una nueva
    - Tecla 'z': deshacer el último punto agregado
    - Tecla 's': guardar todas las zonas definidas hasta ahora y salir
    - Tecla 'q': salir sin guardar

Uso:
    python pipeline\\calibrate_zones.py --video data\\raw\\1_2_crop.mp4 --store-name tienda_amigo
    python pipeline\\calibrate_zones.py --video data\\raw\\1_2_crop.mp4 --frame-number 50
"""

import argparse
import json
import os
import cv2


def parse_args():
    parser = argparse.ArgumentParser(description="Calibración interactiva de zonas sobre un frame del video.")
    parser.add_argument("--video", type=str, required=True,
                         help="Ruta del video sobre el que se van a definir las zonas")
    parser.add_argument("--frame-number", type=int, default=0,
                         help="Número de frame a usar como referencia visual (default: 0, el primero)")
    parser.add_argument("--store-name", type=str, default="tienda_sin_nombre",
                         help="Nombre identificador de la tienda/cámara (default: tienda_sin_nombre)")
    parser.add_argument("--output", type=str, default=None,
                         help="Ruta del JSON de salida (default: config/zones_<store-name>.json)")
    parser.add_argument("--dwell-threshold", type=float, default=2.0,
                         help="Umbral por defecto (segundos) para considerar 'se detiene' en cada zona (default: 2.0)")
    return parser.parse_args()


class ZoneCalibrator:
    def __init__(self, frame, dwell_threshold):
        self.original_frame = frame.copy()
        self.dwell_threshold = dwell_threshold
        self.zones = []
        self.current_points = []
        self.zone_counter = 0

    def redraw(self):
        display = self.original_frame.copy()

        for zone in self.zones:
            pts = zone["points"]
            for i in range(len(pts)):
                cv2.line(display, pts[i], pts[(i + 1) % len(pts)], (0, 255, 0), 2)
            cx = sum(p[0] for p in pts) // len(pts)
            cy = sum(p[1] for p in pts) // len(pts)
            cv2.putText(display, zone["label"], (cx - 20, cy),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

        for i, pt in enumerate(self.current_points):
            cv2.circle(display, pt, 4, (0, 0, 255), -1)
            if i > 0:
                cv2.line(display, self.current_points[i - 1], pt, (0, 0, 255), 2)
        if len(self.current_points) > 2:
            cv2.line(display, self.current_points[-1], self.current_points[0], (0, 0, 255), 1)

        instructions = [
            "Click izq: agregar punto | 'n': cerrar zona | 'z': deshacer | 's': guardar | 'q': salir",
            f"Zonas definidas: {len(self.zones)} | Puntos actuales: {len(self.current_points)}"
        ]
        for i, text in enumerate(instructions):
            cv2.putText(display, text, (10, 25 + i * 22),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 0), 1)

        return display

    def on_click(self, event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN:
            self.current_points.append((x, y))

    def close_current_zone(self):
        if len(self.current_points) < 3:
            print("Necesitas al menos 3 puntos para cerrar una zona.")
            return
        self.zone_counter += 1
        label = f"zona_{self.zone_counter}"
        self.zones.append({"points": self.current_points.copy(), "label": label})
        print(f"Zona '{label}' cerrada con {len(self.current_points)} puntos.")
        self.current_points = []

    def undo_last_point(self):
        if self.current_points:
            self.current_points.pop()

    def to_config_dict(self, store_name, video_path, frame_width, frame_height):
        zones_out = []
        for zone in self.zones:
            zones_out.append({
                "id": zone["label"],
                "label": zone["label"],
                "polygon": [[int(x), int(y)] for x, y in zone["points"]],
                "dwell_threshold_seconds": self.dwell_threshold,
            })
        return {
            "store_name": store_name,
            "video_reference": video_path,
            "frame_width": frame_width,
            "frame_height": frame_height,
            "zones": zones_out,
        }


def main():
    args = parse_args()

    if not os.path.exists(args.video):
        print(f"ERROR: no se encontró el video '{args.video}'")
        return

    cap = cv2.VideoCapture(args.video)
    cap.set(cv2.CAP_PROP_POS_FRAMES, args.frame_number)
    ret, frame = cap.read()
    frame_height, frame_width = frame.shape[:2]
    cap.release()

    if not ret:
        print(f"ERROR: no se pudo leer el frame {args.frame_number} del video.")
        return

    calibrator = ZoneCalibrator(frame, args.dwell_threshold)

    window_name = "Calibracion de zonas - " + args.store_name
    cv2.namedWindow(window_name)
    cv2.setMouseCallback(window_name, calibrator.on_click)

    print("=" * 60)
    print("CALIBRACIÓN DE ZONAS")
    print("=" * 60)
    print("Click izquierdo: agregar punto")
    print("'n': cerrar zona actual (mínimo 3 puntos) y empezar otra")
    print("'z': deshacer último punto")
    print("'s': guardar todas las zonas y salir")
    print("'q': salir SIN guardar")
    print("=" * 60)

    while True:
        display = calibrator.redraw()
        cv2.imshow(window_name, display)
        key = cv2.waitKey(20) & 0xFF

        if key == ord('n'):
            calibrator.close_current_zone()
        elif key == ord('z'):
            calibrator.undo_last_point()
        elif key == ord('s'):
            break
        elif key == ord('q'):
            print("Saliendo sin guardar.")
            cv2.destroyAllWindows()
            return

    cv2.destroyAllWindows()

    if not calibrator.zones:
        print("No se definió ninguna zona. No se guardó ningún archivo.")
        return

    output_path = args.output or f"config/zones_{args.store_name}.json"
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)

    config = calibrator.to_config_dict(args.store_name, args.video, frame_width, frame_height)
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"\nConfiguración guardada en: {output_path}")
    print(f"Total de zonas definidas: {len(calibrator.zones)}")
    for zone in calibrator.zones:
        print(f"  - {zone['label']}: {len(zone['points'])} puntos")


if __name__ == "__main__":
    main()