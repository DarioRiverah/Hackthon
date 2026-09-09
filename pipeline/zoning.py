"""
Zonificación y cálculo de dwell time.

Cruza las posiciones (x, y) de cada persona -- ya con id_persona corregido
por track_stitching.py -- contra las zonas/góndolas definidas en
calibrate_zones.py, para responder:

    - ¿En qué zona estuvo cada persona en cada momento?
    - ¿Cuánto tiempo permaneció en cada zona (dwell time)?
    - ¿Fue una "detención" real o solo "pasó de largo"?
      (según el dwell_threshold_seconds configurado por zona)

IMPORTANTE (privacidad por diseño): la salida de este script son
EVENTOS AGREGADOS (zona, duración, timestamps) por id_persona efímero.
No se guarda ninguna imagen, recorte de video, ni dato biométrico --
solo números.

Salidas:
    data/output/zone_events_<nombre>.csv   -> un evento por cada visita
                                                de una persona a una zona
    data/output/zone_summary_<nombre>.csv  -> métricas agregadas por zona

Uso:
    python pipeline\\zoning.py --tracks data\\processed\\tracks_1_2_crop_stitched.csv --zones config\\zones_merl_demo.json
"""

import argparse
import json
import os
import cv2
import pandas as pd


def parse_args():
    parser = argparse.ArgumentParser(description="Zonificación y cálculo de dwell time.")
    parser.add_argument("--tracks", type=str, required=True,
                         help="CSV de tracks con columna id_persona (salida de track_stitching.py)")
    parser.add_argument("--zones", type=str, required=True,
                         help="JSON de configuración de zonas (salida de calibrate_zones.py)")
    parser.add_argument("--id-column", type=str, default="id_persona",
                         help="Nombre de la columna de identificador de persona a usar (default: id_persona)")
    parser.add_argument("--output-prefix", type=str, default=None,
                         help="Prefijo para los archivos de salida (default: se infiere del nombre de zonas)")
    return parser.parse_args()


def load_zones(zones_path):
    try:
        with open(zones_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"ERROR: el archivo '{zones_path}' no es un JSON válido ({e}). "
            f"¿Se corrompió o quedó vacío? Vuelve a correr calibrate_zones.py."
        )
    if "zones" not in config or not config["zones"]:
        raise SystemExit(
            f"ERROR: el archivo '{zones_path}' no tiene ninguna zona definida. "
            f"Vuelve a correr calibrate_zones.py y asegúrate de presionar 'n' "
            f"para cerrar al menos una zona antes de guardar con 's'."
        )
    zones = []
    for zone in config["zones"]:
        polygon = [(int(x), int(y)) for x, y in zone["polygon"]]
        zones.append({
            "id": zone["id"],
            "label": zone["label"],
            "polygon": polygon,
            "dwell_threshold_seconds": zone.get("dwell_threshold_seconds", 2.0),
        })
    return config.get("store_name", "tienda"), zones


def find_zone_for_point(x, y, zones):
    """Devuelve el id de la primera zona que contiene el punto (x,y), o None."""
    point = (float(x), float(y))
    for zone in zones:
        polygon = zone["polygon"]
        result = cv2.pointPolygonTest(
            _polygon_to_contour(polygon), point, measureDist=False
        )
        if result >= 0:  # dentro o justo en el borde
            return zone["id"]
    return None


def _polygon_to_contour(polygon):
    import numpy as np
    return np.array(polygon, dtype="int32").reshape((-1, 1, 2))


def assign_zones(df: pd.DataFrame, zones, id_column: str) -> pd.DataFrame:
    df = df.copy()
    df["zone_id"] = df.apply(
        lambda row: find_zone_for_point(row["x_center"], row["y_center"], zones),
        axis=1,
    )
    return df


def _same_zone(a, b):
    """Compara dos valores de zona tratando correctamente el caso 'fuera de
    cualquier zona' (representado como None/NaN), ya que NaN != NaN es
    siempre True en Python y fragmentaría erróneamente esos segmentos."""
    a_is_none = a is None or (isinstance(a, float) and pd.isna(a))
    b_is_none = b is None or (isinstance(b, float) and pd.isna(b))
    if a_is_none and b_is_none:
        return True
    return a == b


def compute_dwell_events(df: pd.DataFrame, zones, id_column: str) -> pd.DataFrame:
    """Convierte la secuencia frame-a-frame en 'eventos' de permanencia:
    cada vez que una persona entra y sale de una zona (o cambia a otra),
    se genera un evento con su duración total.

    Los segmentos donde la persona está FUERA de cualquier zona (zone_id=None,
    ej. caminando por el pasillo central) se agrupan igual que cualquier otro
    segmento para evitar fragmentación espuria, pero se EXCLUYEN del resultado
    final porque no representan una visita a una góndola -- son simplemente
    tránsito general, que ya se refleja en el heatmap de flujo."""
    zone_thresholds = {z["id"]: z["dwell_threshold_seconds"] for z in zones}

    events = []
    for person_id, group in df.groupby(id_column):
        group_sorted = group.sort_values("frame")
        current_zone = None
        segment_start_time = None
        has_open_segment = False
        last_time = None

        for _, row in group_sorted.iterrows():
            zone = row["zone_id"]
            t = row["timestamp"]

            if not has_open_segment:
                current_zone = zone
                segment_start_time = t
                has_open_segment = True
            elif not _same_zone(zone, current_zone):
                duration = last_time - segment_start_time
                threshold = zone_thresholds.get(current_zone, 2.0)
                events.append({
                    id_column: person_id,
                    "zone_id": current_zone,
                    "start_time": round(segment_start_time, 3),
                    "end_time": round(last_time, 3),
                    "duration_seconds": round(duration, 3),
                    "classification": "se_detiene" if duration >= threshold else "pasa_de_largo",
                })
                current_zone = zone
                segment_start_time = t

            last_time = t

        # Cerrar el último segmento abierto al terminar el track de esta persona
        if has_open_segment:
            duration = last_time - segment_start_time
            threshold = zone_thresholds.get(current_zone, 2.0)
            events.append({
                id_column: person_id,
                "zone_id": current_zone,
                "start_time": round(segment_start_time, 3),
                "end_time": round(last_time, 3),
                "duration_seconds": round(duration, 3),
                "classification": "se_detiene" if duration >= threshold else "pasa_de_largo",
            })

    events_df = pd.DataFrame(events)

    # Excluir segmentos "fuera de zona" (zone_id None/NaN) del resultado final
    if not events_df.empty:
        events_df = events_df[events_df["zone_id"].notna()].reset_index(drop=True)

    return events_df


def compute_zone_summary(events_df: pd.DataFrame, zones) -> pd.DataFrame:
    """Métricas agregadas por zona: visitas totales, detenciones, tasa de
    detención, dwell promedio -- justo lo que alimenta el dashboard."""
    labels = {z["id"]: z["label"] for z in zones}
    summary_rows = []

    if events_df.empty:
        return pd.DataFrame(columns=[
            "zone_id", "zone_label", "total_visits", "stops", "pass_throughs",
            "stop_rate_pct", "avg_dwell_seconds", "max_dwell_seconds"
        ])

    for zone_id, group in events_df.groupby("zone_id"):
        total_visits = len(group)
        stops = (group["classification"] == "se_detiene").sum()
        pass_throughs = total_visits - stops
        stop_rate = (stops / total_visits * 100) if total_visits > 0 else 0
        avg_dwell = group["duration_seconds"].mean()
        max_dwell = group["duration_seconds"].max()

        summary_rows.append({
            "zone_id": zone_id,
            "zone_label": labels.get(zone_id, zone_id),
            "total_visits": total_visits,
            "stops": int(stops),
            "pass_throughs": int(pass_throughs),
            "stop_rate_pct": round(stop_rate, 1),
            "avg_dwell_seconds": round(avg_dwell, 2),
            "max_dwell_seconds": round(max_dwell, 2),
        })

    return pd.DataFrame(summary_rows).sort_values("total_visits", ascending=False)


def main():
    args = parse_args()

    if not os.path.exists(args.tracks):
        print(f"ERROR: no se encontró el CSV de tracks '{args.tracks}'")
        return
    if not os.path.exists(args.zones):
        print(f"ERROR: no se encontró el archivo de zonas '{args.zones}'")
        return

    store_name, zones = load_zones(args.zones)
    df = pd.read_csv(args.tracks)

    if args.id_column not in df.columns:
        print(f"ERROR: la columna '{args.id_column}' no existe en el CSV de tracks.")
        print(f"Columnas disponibles: {list(df.columns)}")
        print("Sugerencia: si tu CSV no pasó por track_stitching.py, usa --id-column track_id")
        return

    print(f"Zonificando {len(df)} detecciones contra {len(zones)} zonas de '{store_name}'...")

    df_zoned = assign_zones(df, zones, args.id_column)

    n_outside = (df_zoned["zone_id"].isna()).sum()
    n_total = len(df_zoned)
    print(f"Puntos fuera de cualquier zona: {n_outside}/{n_total} ({n_outside/n_total*100:.1f}%)")

    events_df = compute_dwell_events(df_zoned, zones, args.id_column)
    summary_df = compute_zone_summary(events_df, zones)

    prefix = args.output_prefix or store_name
    os.makedirs("data/output", exist_ok=True)
    events_path = f"data/output/zone_events_{prefix}.csv"
    summary_path = f"data/output/zone_summary_{prefix}.csv"

    events_df.to_csv(events_path, index=False)
    summary_df.to_csv(summary_path, index=False)

    print(f"\nEventos de zona guardados en: {events_path} ({len(events_df)} eventos)")
    print(f"Resumen por zona guardado en: {summary_path}")
    print("\n--- RESUMEN POR ZONA ---")
    if not summary_df.empty:
        print(summary_df.to_string(index=False))
    else:
        print("No se generaron eventos (revisa que las zonas cubran las posiciones del video).")


if __name__ == "__main__":
    main()