"""
Lógica de "estado de tienda" -- 100% pura (sin Streamlit ni Flask),
extraída de la versión anterior del dashboard (ahora en
_legacy_streamlit/app.py) al migrar a Flask. Lee/escribe los mismos archivos que ya usa el
pipeline (config/zones_*.json, data/output/*.csv) -- el backend web no
mantiene ningún estado propio en memoria más allá de esto.
"""

import json
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
from history_db import get_available_dates  # noqa: E402
from history_archive import get_archive_dir  # noqa: E402


def list_all_stores() -> list:
    """Nombres de tienda conocidos por CUALQUIER motivo: ya calibradas
    (config/zones_*.json) o ya procesadas (data/output/zone_summary_*.csv)
    -- así una tienda calibrada pero aún sin procesar no "desaparece" de
    la lista mientras se completa el flujo."""
    names = set()

    if os.path.exists("config"):
        for filename in os.listdir("config"):
            if filename.startswith("zones_") and filename.endswith(".json"):
                names.add(filename[len("zones_"):-len(".json")])

    if os.path.exists("data/output"):
        for filename in os.listdir("data/output"):
            if filename.startswith("zone_summary_") and filename.endswith(".csv"):
                names.add(filename[len("zone_summary_"):-len(".csv")])

    return sorted(names)


def get_store_state(store_name: str) -> dict:
    """Estado actual de una tienda: ¿tiene zonas calibradas? ¿tiene
    resultados procesados? ¿cuántas fechas hay en el historial?"""
    has_zones = os.path.exists(f"config/zones_{store_name}.json")
    has_results = os.path.exists(f"data/output/zone_summary_{store_name}.csv")
    n_history = len(get_available_dates(store_name)) if has_results else 0

    return {"has_zones": has_zones, "has_results": has_results, "n_history": n_history}


def load_store_data(store_name: str):
    """Carga zone_summary + zones_config (obligatorios) e
    interaction_summary (opcional, puede no existir todavía). Devuelve
    (summary_df, zones_config, interaction_df); los tres son None si
    faltan los archivos obligatorios."""
    summary_path = f"data/output/zone_summary_{store_name}.csv"
    zones_path = f"config/zones_{store_name}.json"
    interaction_path = f"data/output/interaction_summary_{store_name}.csv"

    if not os.path.exists(summary_path) or not os.path.exists(zones_path):
        return None, None, None

    summary_df = pd.read_csv(summary_path)
    with open(zones_path, "r", encoding="utf-8") as f:
        zones_config = json.load(f)

    interaction_df = pd.read_csv(interaction_path) if os.path.exists(interaction_path) else None

    return summary_df, zones_config, interaction_df


def load_archived_store_data(camara_id: str, run_date: str):
    """Análogo a load_store_data(), pero lee la instantánea archivada de
    una fecha (data/history/<camara_id>/<run_date>/) en vez de los
    archivos "en vivo" -- ver pipeline/history_archive.py y
    docs/architecture.md sección 34. Devuelve (summary_df, zones_config,
    interaction_df), los tres None si esa fecha no está archivada o le
    falta el resumen de zona (obligatorio, igual que en la versión en
    vivo)."""
    archive_dir = get_archive_dir(camara_id, run_date)
    summary_path = os.path.join(archive_dir, "zone_summary.csv")
    zones_path = os.path.join(archive_dir, "zones.json")
    interaction_path = os.path.join(archive_dir, "interaction_summary.csv")

    if not os.path.exists(summary_path) or not os.path.exists(zones_path):
        return None, None, None

    summary_df = pd.read_csv(summary_path)
    with open(zones_path, "r", encoding="utf-8") as f:
        zones_config = json.load(f)

    interaction_df = pd.read_csv(interaction_path) if os.path.exists(interaction_path) else None

    return summary_df, zones_config, interaction_df


def compute_overview_kpis(summary_df: pd.DataFrame, interaction_df) -> dict:
    """KPIs generales para la fila superior del panel de resultados --
    los 4 salen directo de zone_summary_df/interaction_summary_df ya
    calculados por el pipeline, ninguna cifra nueva ni estimada aquí."""
    total_zones = len(summary_df)
    total_visits = int(summary_df["total_visits"].sum()) if not summary_df.empty else 0

    if interaction_df is not None and not interaction_df.empty:
        total_interactions = int(interaction_df["total_interactions"].sum())
    else:
        total_interactions = None  # no "cero" -- simplemente no medido todavía

    if not summary_df.empty:
        top_row = summary_df.loc[summary_df["total_visits"].idxmax()]
        top_zone_label = str(top_row["zone_label"])
        top_zone_visits = int(top_row["total_visits"])
    else:
        top_zone_label, top_zone_visits = "N/D", 0

    return {
        "total_zones": total_zones,
        "total_visits": total_visits,
        "total_interactions": total_interactions,
        "top_zone_label": top_zone_label,
        "top_zone_visits": top_zone_visits,
    }
