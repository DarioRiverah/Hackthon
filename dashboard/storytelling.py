"""
Storytelling: convierte los eventos ya detectados (zonificación +
interacción) en una historia legible para el dueño de la tienda.

DECISIÓN DE DISEÑO IMPORTANTE (v2): la narrativa es 100% AGREGADA, sin
atribuir eventos a un "cliente" o id_persona específico.

Por qué: la identificación de personas (track_id -> id_persona, vía
track_stitching.py) se basa en heurísticas geométricas (velocidad
implícita, consistencia de dirección) sobre posiciones, no en
reconocimiento facial ni ningún dato biométrico -- por diseño de
privacidad. Esto es confiable para UNA persona en el cuadro sin nadie
más con quien confundirla (como en nuestro caso de validación con
MERL), pero no está validado para escenas reales con VARIAS personas
simultáneas, donde un cruce de trayectorias podría fusionar o dividir
identidades por error (ver los "casos ambiguos" que ya observamos en
pipeline/track_stitching.py).

Presentar un desglose "el Cliente 3 hizo esto" implicaría una certeza
de identificación que no podemos garantizar en el caso general. En
cambio, se narra en términos de EVENTOS observados (cuántas detenciones
hubo, cuánta interacción, en qué momento) sin afirmar que pertenecen a
una persona específica -- exactamente el mismo principio que ya usan
las métricas agregadas por zona en el resto del dashboard.
"""

import os

import pandas as pd


def load_events_from_paths(zone_events_path: str, interaction_events_path: str):
    """Carga los eventos crudos desde rutas explícitas -- núcleo
    reutilizable tanto por load_events() (rutas "en vivo") como por la
    vista histórica archivada (dashboard/history_service.py), que lee
    los mismos CSV pero desde data/history/<camara>/<fecha>/. Devuelve
    (zone_events_df, interaction_events_df), cualquiera puede ser None
    si no existe."""
    zone_events_df = pd.read_csv(zone_events_path) if os.path.exists(zone_events_path) else None
    interaction_events_df = (
        pd.read_csv(interaction_events_path) if os.path.exists(interaction_events_path) else None
    )
    return zone_events_df, interaction_events_df


def load_events(store_name: str):
    """Carga los eventos crudos (no los resúmenes) de zonificación e
    interacción de la corrida EN VIVO de una cámara, si existen."""
    return load_events_from_paths(
        f"data/output/zone_events_{store_name}.csv",
        f"data/output/interaction_events_{store_name}.csv",
    )


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f} segundos"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes} min {secs}s"


def _format_timestamp(seconds: float) -> str:
    """Formatea un PUNTO en el tiempo (ej. 'a los 1:05'), distinto de
    _format_duration que formatea una DURACIÓN (ej. '1 min 5s')."""
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def generate_aggregate_narrative(zone_events_df: pd.DataFrame, interaction_events_df: pd.DataFrame,
                                  zone_labels: dict) -> str:
    """Narrativa en prosa, agregada por zona -- NUNCA por persona. Cuenta
    la historia de 'qué pasó en este video' en términos de eventos
    observados, sin afirmar que se identificó correctamente a cada
    individuo."""
    if zone_events_df is None or zone_events_df.empty:
        return "No se registraron eventos de zona para este video."

    total_events = len(zone_events_df)
    stops = zone_events_df[zone_events_df["classification"] == "se_detiene"]
    pass_throughs = zone_events_df[zone_events_df["classification"] == "pasa_de_largo"]

    parts = []
    parts.append(
        f"Se registraron {total_events} evento(s) de zona en total "
        f"(cada uno representa una detención o un paso por una zona, no necesariamente "
        f"personas distintas -- ver nota de alcance más abajo)."
    )

    if not stops.empty:
        avg_stop_duration = stops["duration_seconds"].mean()
        parts.append(
            f"De estos, {len(stops)} fueron detenciones genuinas "
            f"({_format_duration(avg_stop_duration)} de permanencia promedio)."
        )
    if not pass_throughs.empty:
        parts.append(f"{len(pass_throughs)} fueron pasos rápidos, sin detenerse.")

    if interaction_events_df is not None and not interaction_events_df.empty:
        n_total = len(interaction_events_df)
        n_prolonged = (interaction_events_df["intensity"] == "interaccion_prolongada").sum()
        parts.append(
            f"Se detectaron {n_total} interacción(es) física(s) con el estante en total, "
            f"de las cuales {n_prolonged} fueron prolongadas."
        )

    return " ".join(parts)


def build_full_timeline(zone_events_df: pd.DataFrame, interaction_events_df: pd.DataFrame,
                         zone_labels: dict) -> list:
    """Línea de tiempo de TODOS los eventos observados, en orden
    cronológico -- descritos por lo que ocurrió (detención, paso,
    interacción) y en qué zona, sin atribuirlos a un 'cliente' o
    identidad de persona específica."""
    timeline = []

    if zone_events_df is not None:
        for _, row in zone_events_df.iterrows():
            zone_name = zone_labels.get(row["zone_id"], row["zone_id"])
            verb = "Detención en" if row["classification"] == "se_detiene" else "Paso por"
            timeline.append({
                "start_time": row["start_time"],
                "icon_type": "stop" if row["classification"] == "se_detiene" else "walk",
                "description": f"{verb} '{zone_name}' ({_format_duration(row['duration_seconds'])})",
            })

    if interaction_events_df is not None:
        for _, row in interaction_events_df.iterrows():
            zone_name = zone_labels.get(row["zone_id"], row["zone_id"])
            intensity_label = {
                "toque_breve": "Toque breve",
                "interaccion_media": "Interacción media",
                "interaccion_prolongada": "Interacción prolongada",
            }.get(row["intensity"], row["intensity"])
            timeline.append({
                "start_time": row["start_time"],
                "icon_type": "hand",
                "description": f"{intensity_label} con el estante en '{zone_name}' "
                                f"({_format_duration(row['duration_seconds'])})",
            })

    timeline.sort(key=lambda e: e["start_time"])
    return timeline


def build_story(zone_events_df, interaction_events_df, zone_labels: dict) -> dict:
    """Núcleo reutilizable de get_story_data(): arma la narrativa y la
    línea de tiempo a partir de DataFrames YA CARGADOS (en vivo o
    archivados, a este punto da igual el origen). Devuelve
    {"has_data": bool, "narrative": str, "timeline": list}."""
    if zone_events_df is None or zone_events_df.empty:
        return {"has_data": False, "narrative": "", "timeline": []}

    narrative = generate_aggregate_narrative(zone_events_df, interaction_events_df, zone_labels)
    raw_timeline = build_full_timeline(zone_events_df, interaction_events_df, zone_labels)
    timeline = [
        {
            "time_label": _format_timestamp(event["start_time"]),
            "icon_type": event["icon_type"],
            "description": event["description"],
        }
        for event in raw_timeline
    ]

    return {"has_data": True, "narrative": narrative, "timeline": timeline}


def get_story_data(store_name: str, zone_labels: dict) -> dict:
    """Punto de entrada único para el backend web (vista EN VIVO): carga
    los eventos de la corrida actual y delega en build_story(). La
    plantilla solo necesita mostrar estos campos, sin repetir ninguna
    lógica de negocio."""
    zone_events_df, interaction_events_df = load_events(store_name)
    return build_story(zone_events_df, interaction_events_df, zone_labels)