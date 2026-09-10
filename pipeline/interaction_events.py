"""
Detección de eventos de interacción física con el estante.

Reutiliza la MISMA lógica de segmentación de zoning.py (compute_dwell_events),
pero aplicada a la posición de la MANO en vez del cuerpo completo. Esto
convierte la secuencia de posiciones de muñeca en "eventos de interacción":
cada vez que la mano entra y sale de la zona del estante.

Ambas muñecas (izquierda y derecha, columna "hand_side" del CSV de manos)
se tratan como DOS puntos de contacto independientes: se segmentan por
separado (para no fragmentar espuriamente un evento cuando una mano está
dentro de la zona y la otra afuera en el mismo cuadro), y cualquiera de
las dos entrando a la zona cuenta como una interacción.

ALCANCE HONESTO (ya establecido desde el plan original del proyecto):
este script detecta y cuantifica LA INTERACCIÓN FÍSICA (frecuencia,
duración), pero NO distingue con certeza si el evento fue una "toma"
(pickup) o una "devolución" (putback) de producto -- esa distinción
requeriría reconocimiento de acciones especializado (flujo óptico,
modelos entrenados específicamente para esto), fuera del alcance de
este MVP. Se comunica como frecuencia/intensidad de interacción, no
como conteo de compras.

Cada evento se clasifica por duración en tres niveles de intensidad,
como proxy interpretable de qué tan involucrada fue la interacción:
    < 1.0s   -> "toque_breve"        (posible mirada rápida, sin tomar nada)
    1.0-4.0s -> "interaccion_media"  (consistente con tomar/inspeccionar un producto)
    > 4.0s   -> "interaccion_prolongada" (consistente con comparar productos, leer etiqueta, etc.)

Uso:
    python pipeline\\interaction_events.py --hands data\\processed\\hands_1_2_crop_stitched.csv --zones config\\zones_merl_demo.json
"""

import argparse
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(__file__))
from zoning import load_zones, assign_zones, compute_dwell_events


BREVE_MAX_SECONDS = 1.0
MEDIA_MAX_SECONDS = 4.0


def parse_args():
    parser = argparse.ArgumentParser(description="Detecta eventos de interacción física con el estante.")
    parser.add_argument("--hands", type=str, required=True,
                         help="CSV de posiciones de mano, ya con id_persona (salida de track_stitching.py)")
    parser.add_argument("--zones", type=str, required=True,
                         help="JSON de configuración de zonas (mismo que usa zoning.py)")
    parser.add_argument("--id-column", type=str, default="id_persona",
                         help="Columna de identificador de persona a usar (default: id_persona)")
    parser.add_argument("--output-prefix", type=str, default=None,
                         help="Prefijo para los archivos de salida (default: se infiere del nombre de zonas)")
    parser.add_argument("--debounce-seconds", type=float, default=0.5,
                         help="Fusiona eventos separados por menos de este tiempo, para eliminar "
                              "ruido de parpadeo en el borde de la zona (default: 0.5)")
    return parser.parse_args()


def classify_interaction_intensity(duration_seconds: float) -> str:
    if duration_seconds < BREVE_MAX_SECONDS:
        return "toque_breve"
    elif duration_seconds < MEDIA_MAX_SECONDS:
        return "interaccion_media"
    else:
        return "interaccion_prolongada"


def merge_close_events(events_df: pd.DataFrame, debounce_seconds: float) -> pd.DataFrame:
    """Fusiona eventos consecutivos de la misma persona+zona separados por
    menos de `debounce_seconds`. Esto elimina el 'parpadeo' que ocurre
    cuando la mano se queda justo en el borde del polígono de la zona y
    pequeñas fluctuaciones del keypoint la hacen entrar/salir varias veces
    en fracciones de segundo -- sin que la persona realmente haya retirado
    la mano del estante."""
    if events_df.empty:
        return events_df

    df = events_df.sort_values(["id_persona", "zone_id", "start_time"]).reset_index(drop=True)
    merged = []
    current = None

    for _, row in df.iterrows():
        row_dict = row.to_dict()
        if current is None:
            current = row_dict
            continue

        same_group = (row_dict["id_persona"] == current["id_persona"] and
                      row_dict["zone_id"] == current["zone_id"])
        gap = row_dict["start_time"] - current["end_time"]

        if same_group and gap <= debounce_seconds:
            current["end_time"] = row_dict["end_time"]
            current["duration_seconds"] = round(current["end_time"] - current["start_time"], 3)
        else:
            merged.append(current)
            current = row_dict

    if current is not None:
        merged.append(current)

    result = pd.DataFrame(merged)
    # Re-clasificar intensidad ya que la duración pudo haber cambiado al fusionar
    result["intensity"] = result["duration_seconds"].apply(classify_interaction_intensity)
    return result


def compute_interaction_summary(events_df: pd.DataFrame, zones) -> pd.DataFrame:
    labels = {z["id"]: z["label"] for z in zones}
    summary_rows = []

    if events_df.empty:
        return pd.DataFrame(columns=[
            "zone_id", "zone_label", "total_interactions", "toques_breves",
            "interacciones_medias", "interacciones_prolongadas", "avg_duration_seconds"
        ])

    for zone_id, group in events_df.groupby("zone_id"):
        total = len(group)
        breves = (group["intensity"] == "toque_breve").sum()
        medias = (group["intensity"] == "interaccion_media").sum()
        prolongadas = (group["intensity"] == "interaccion_prolongada").sum()
        avg_duration = group["duration_seconds"].mean()

        summary_rows.append({
            "zone_id": zone_id,
            "zone_label": labels.get(zone_id, zone_id),
            "total_interactions": total,
            "toques_breves": int(breves),
            "interacciones_medias": int(medias),
            "interacciones_prolongadas": int(prolongadas),
            "avg_duration_seconds": round(avg_duration, 2),
        })

    return pd.DataFrame(summary_rows).sort_values("total_interactions", ascending=False)


def main():
    args = parse_args()

    if not os.path.exists(args.hands):
        print(f"ERROR: no se encontró el CSV de manos '{args.hands}'")
        return
    if not os.path.exists(args.zones):
        print(f"ERROR: no se encontró el archivo de zonas '{args.zones}'")
        return

    store_name, zones = load_zones(args.zones)
    df = pd.read_csv(args.hands)

    if args.id_column not in df.columns:
        print(f"ERROR: la columna '{args.id_column}' no existe en el CSV.")
        print(f"Columnas disponibles: {list(df.columns)}")
        return

    print(f"Detectando interacciones a partir de {len(df)} posiciones de mano...")

    df_zoned = assign_zones(df, zones, args.id_column)
    n_outside = df_zoned["zone_id"].isna().sum()
    print(f"Posiciones de mano fuera de cualquier zona: {n_outside}/{len(df_zoned)} "
          f"({n_outside/len(df_zoned)*100:.1f}%)")

    # Si el CSV trae ambas muñecas por separado (columna hand_side), se
    # segmenta cada mano de forma INDEPENDIENTE -- de lo contrario, una
    # persona con una mano dentro de la zona y la otra afuera en el mismo
    # cuadro generaría un "entra/sale" espurio en cada cuadro, en vez de
    # reflejar que cualquiera de las dos manos ya cuenta como interacción.
    has_hand_side = "hand_side" in df_zoned.columns
    if has_hand_side:
        df_zoned["_dwell_id"] = (
            df_zoned[args.id_column].astype(str) + "::" + df_zoned["hand_side"].astype(str)
        )
        dwell_id_column = "_dwell_id"
    else:
        dwell_id_column = args.id_column

    # Reutilizamos la MISMA función de segmentación que zoning.py -- la
    # lógica de "entra y sale de una zona" es idéntica sea el punto de
    # referencia el cuerpo completo o la mano.
    events_df = compute_dwell_events(df_zoned, zones, dwell_id_column)

    if has_hand_side and not events_df.empty:
        split = events_df[dwell_id_column].str.split("::", n=1, expand=True)
        events_df[args.id_column] = split[0]
        events_df["hand_side"] = split[1]
        events_df = events_df.drop(columns=[dwell_id_column])

    if not events_df.empty:
        events_df["intensity"] = events_df["duration_seconds"].apply(classify_interaction_intensity)
        events_df = events_df.rename(columns={"classification": "clasificacion_dwell_no_aplica"})
        events_df = events_df.drop(columns=["clasificacion_dwell_no_aplica"])

    n_before_debounce = len(events_df)
    events_df = merge_close_events(events_df, args.debounce_seconds)
    n_after_debounce = len(events_df)
    print(f"Eventos antes de debounce: {n_before_debounce} -> después de debounce "
          f"({args.debounce_seconds}s): {n_after_debounce}")

    summary_df = compute_interaction_summary(events_df, zones)

    prefix = args.output_prefix or store_name
    os.makedirs("data/output", exist_ok=True)
    events_path = f"data/output/interaction_events_{prefix}.csv"
    summary_path = f"data/output/interaction_summary_{prefix}.csv"

    events_df.to_csv(events_path, index=False)
    summary_df.to_csv(summary_path, index=False)

    print(f"\nEventos de interacción guardados en: {events_path} ({len(events_df)} eventos)")
    print(f"Resumen guardado en: {summary_path}")
    print("\n--- RESUMEN DE INTERACCIÓN POR ZONA ---")
    if not summary_df.empty:
        print(summary_df.to_string(index=False))
        print("\nNota: 'interacciones' = veces que la mano entró a la zona del estante.")
        print("No se distingue si el resultado fue tomar o devolver un producto.")
    else:
        print("No se detectaron interacciones (revisa que la zona cubra donde se mueve la mano).")


if __name__ == "__main__":
    main()