"""
Lógica pura de calibración de zonas -- guarda config/zones_<store>.json
en el MISMO formato que ya usa pipeline/zoning.py, sin cambios.

Diseño distinto al de la versión Streamlit: ahí el polígono en progreso
vivía en st.session_state del servidor (recargando toda la página en
cada clic). Aquí el polígono en progreso vive en el propio navegador
(JavaScript, ver static/js/calibration.js) -- el backend solo recibe la
lista de zonas ya completas al presionar "Guardar todas las zonas", vía
JSON. Por eso este módulo no necesita ningún estado de sesión: solo
valida y escribe el archivo.
"""

import json
import os


def save_zones_config(store_name: str, video_path: str, frame_width: int, frame_height: int,
                       zones: list) -> str:
    """zones: lista de {"label": str, "polygon": [[x,y], ...]}. Devuelve
    la ruta del archivo escrito. Lanza ValueError si algún polígono tiene
    menos de 3 puntos (una zona real necesita al menos un triángulo)."""
    for zone in zones:
        if len(zone.get("polygon", [])) < 3:
            raise ValueError(
                f"La zona '{zone.get('label', '(sin nombre)')}' tiene menos de 3 puntos -- "
                "no se puede guardar."
            )

    config = {
        "store_name": store_name,
        "video_reference": video_path,
        "frame_width": frame_width,
        "frame_height": frame_height,
        "zones": [
            {
                "id": zone["label"],
                "label": zone["label"],
                "polygon": [[int(x), int(y)] for x, y in zone["polygon"]],
                "dwell_threshold_seconds": 2.0,
            }
            for zone in zones
        ],
    }

    zones_path = f"config/zones_{store_name}.json"
    os.makedirs("config", exist_ok=True)
    with open(zones_path, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    return zones_path


def zones_config_exists(store_name: str) -> bool:
    return os.path.exists(f"config/zones_{store_name}.json")
