"""
Simulador "qué pasaría si" -- estima el impacto de mover producto de
una zona a otra, basándose en una extrapolación simple sobre los datos
YA OBSERVADOS, no en un modelo de predicción de machine learning.

Supuesto central (explícito, para no sobre-prometer): la TASA de
interacción por visitante del producto se mantiene igual, y lo que
cambia es la cantidad de visitas que recibiría en la nueva zona. Es
decir: "si este producto sigue generando el mismo interés relativo,
pero lo ve más gente (o menos), así cambiaría su interacción total".

Esto es honesto sobre sus límites: no considera que un producto
distinto en un contexto distinto podría comportarse diferente -- es
una proyección basada en el patrón de tráfico ya medido, presentada
como estimación, no como garantía.

100% lógica pura (sin Streamlit ni Flask) -- la presentación vive en el
backend web (ver dashboard/webapp/), que llama a estas funciones y
decide cómo mostrarlas.
"""

import pandas as pd


def simulate_move(visits_from: float, interactions_from: float, visits_to: float) -> dict | None:
    """Calcula la extrapolación. Devuelve None si no hay suficientes
    datos de interacción en la zona de origen para calcular una tasa
    (ej. cero interacciones registradas)."""
    if visits_from <= 0 or interactions_from <= 0:
        return None

    rate = interactions_from / visits_from
    simulated_interactions = rate * visits_to
    pct_change = (simulated_interactions - interactions_from) / interactions_from * 100

    return {
        "tasa_actual": rate,
        "interacciones_actuales": interactions_from,
        "interacciones_simuladas": simulated_interactions,
        "cambio_pct": pct_change,
    }


def get_zone_options(zone_summary_df: pd.DataFrame) -> dict:
    """{zone_label: zone_id} para poblar los selectores de origen/destino."""
    return dict(zip(zone_summary_df["zone_label"], zone_summary_df["zone_id"]))


def run_simulation(zone_summary_df: pd.DataFrame, interaction_summary_df: pd.DataFrame,
                    from_id: str, to_id: str) -> dict:
    """Punto de entrada único para el backend web: dados los DataFrames ya
    cargados y los IDs de zona origen/destino, hace los lookups y corre
    la extrapolación. Devuelve siempre un dict con:
      {"ok": bool, "error": str | None, "from_label": str, "to_label": str,
       "visits_from": float, "visits_to": float, "result": dict | None}
    -- nunca lanza una excepción por datos faltantes, siempre reporta el
    problema en "error" para que la interfaz lo muestre en lenguaje llano."""
    from_row = zone_summary_df[zone_summary_df["zone_id"] == from_id]
    to_row = zone_summary_df[zone_summary_df["zone_id"] == to_id]

    if from_row.empty or to_row.empty:
        return {"ok": False, "error": "No se encontraron datos de tráfico para una de las zonas seleccionadas."}

    from_label = from_row["zone_label"].iloc[0]
    to_label = to_row["zone_label"].iloc[0]
    visits_from = float(from_row["total_visits"].iloc[0])
    visits_to = float(to_row["total_visits"].iloc[0])

    interactions_from = 0.0
    if interaction_summary_df is not None and not interaction_summary_df.empty:
        interactions_from_row = interaction_summary_df[interaction_summary_df["zone_id"] == from_id]
        if not interactions_from_row.empty:
            interactions_from = float(interactions_from_row["total_interactions"].iloc[0])

    result = simulate_move(visits_from, interactions_from, visits_to)

    if result is None:
        return {
            "ok": False,
            "error": f"'{from_label}' no tiene interacciones registradas todavía, "
                     "así que no hay una tasa base para extrapolar.",
            "from_label": from_label, "to_label": to_label,
            "from_id": from_id, "to_id": to_id,
        }

    return {
        "ok": True, "error": None,
        "from_label": from_label, "to_label": to_label,
        "from_id": from_id, "to_id": to_id,
        "visits_from": visits_from, "visits_to": visits_to,
        "result": result,
    }


def recommend_best_destination(zone_summary_df: pd.DataFrame, interaction_summary_df: pd.DataFrame,
                                from_id: str) -> dict:
    """Prueba la zona de origen contra CADA otra zona disponible como
    posible destino -- reutilizando run_simulation() sin cambios -- y
    devuelve la que da el mayor cambio_pct. No sugiere un destino que
    empeore las cosas: si ninguna candidata mejora la interacción
    actual, lo reporta explícitamente (ok=False, no_improvement=True)
    en vez de forzar la "menos mala" como si fuera una recomendación."""
    candidate_ids = [zid for zid in zone_summary_df["zone_id"].tolist() if zid != from_id]
    if not candidate_ids:
        return {"ok": False, "error": "No hay otra zona disponible para comparar como destino."}

    resultados = [run_simulation(zone_summary_df, interaction_summary_df, from_id, cid) for cid in candidate_ids]

    # Si el origen no tiene interacciones registradas, TODAS las corridas
    # fallan por la misma razón (independiente del destino) -- alcanza
    # con propagar el primer error, ya viene con el mensaje explicando por qué.
    exitosas = [r for r in resultados if r.get("ok")]
    if not exitosas:
        return resultados[0]

    mejor = max(exitosas, key=lambda r: r["result"]["cambio_pct"])
    if mejor["result"]["cambio_pct"] <= 0:
        return {
            "ok": False,
            "no_improvement": True,
            "from_label": mejor["from_label"],
            "error": f"Esta zona ya parece estar bien ubicada -- comparamos contra {len(exitosas)} zona(s) "
                     "candidata(s) y no encontramos un destino que mejore su interacción actual.",
        }

    mejor["n_candidatos_evaluados"] = len(exitosas)
    mejor["recomendado"] = True
    return mejor


# =============================================================================
# Variantes MULTI-CÁMARA (vista combinada de tienda, ver
# dashboard/tienda_service.py) -- simulate_move() NO cambia, la única
# diferencia real es que las zonas candidatas vienen de un DataFrame
# COMBINADO de varias cámaras, así que zone_id por sí solo ya no
# alcanza para identificar una fila sin ambigüedad (dos cámaras
# distintas podrían haber calibrado una zona con el mismo id) -- se usa
# una clave compuesta "camara_id::zone_id" en su lugar.
# =============================================================================

def _clave_compuesta(camara_id, zone_id) -> str:
    return f"{camara_id}::{zone_id}"


def _parsear_clave_compuesta(clave: str):
    camara_id, zone_id = clave.split("::", 1)
    return camara_id, zone_id


def get_zone_options_multi(zone_summary_combinado: pd.DataFrame) -> dict:
    """Análogo a get_zone_options(), pero para el DataFrame combinado de
    varias cámaras -- la etiqueta incluye la cámara de origen para que
    el usuario elija sin ambigüedad (ej. "Snacks (Cámara: tienda_centro_entrada)")."""
    options = {}
    for _, row in zone_summary_combinado.iterrows():
        etiqueta = f"{row['zone_label']} (Cámara: {row['camara_origen']})"
        options[etiqueta] = _clave_compuesta(row["camara_origen"], row["zone_id"])
    return options


def run_simulation_multi(zone_summary_combinado: pd.DataFrame, interaction_summary_combinado: pd.DataFrame,
                          from_key: str, to_key: str) -> dict:
    """Igual que run_simulation(), pero recibe las claves compuestas de
    get_zone_options_multi() -- reutiliza simulate_move() sin cambios,
    solo cambia cómo se ubican las filas de origen/destino (por
    camara_origen + zone_id en vez de solo zone_id). Además de lo que ya
    devuelve run_simulation(), incluye same_camara (bool) y la fecha/
    duración de referencia de cada cámara, para que la interfaz pueda
    mostrar la advertencia de comparabilidad cuando corresponda (ver
    docs/architecture.md sección 32) -- ESA decisión de cuándo mostrar
    la advertencia vive en la plantilla/ruta, no acá: esta función solo
    aporta los datos necesarios para tomarla."""
    from_camara, from_zone_id = _parsear_clave_compuesta(from_key)
    to_camara, to_zone_id = _parsear_clave_compuesta(to_key)

    from_row = zone_summary_combinado[
        (zone_summary_combinado["camara_origen"] == from_camara) & (zone_summary_combinado["zone_id"] == from_zone_id)
    ]
    to_row = zone_summary_combinado[
        (zone_summary_combinado["camara_origen"] == to_camara) & (zone_summary_combinado["zone_id"] == to_zone_id)
    ]

    if from_row.empty or to_row.empty:
        return {"ok": False, "error": "No se encontraron datos de tráfico para una de las zonas seleccionadas."}

    from_label = from_row["zone_label"].iloc[0]
    to_label = to_row["zone_label"].iloc[0]
    visits_from = float(from_row["total_visits"].iloc[0])
    visits_to = float(to_row["total_visits"].iloc[0])

    interactions_from = 0.0
    if interaction_summary_combinado is not None and not interaction_summary_combinado.empty:
        irow = interaction_summary_combinado[
            (interaction_summary_combinado["camara_origen"] == from_camara)
            & (interaction_summary_combinado["zone_id"] == from_zone_id)
        ]
        if not irow.empty:
            interactions_from = float(irow["total_interactions"].iloc[0])

    result = simulate_move(visits_from, interactions_from, visits_to)

    base = {
        "from_label": from_label, "to_label": to_label,
        "from_key": from_key, "to_key": to_key,
        "from_camara": from_camara, "to_camara": to_camara,
        "same_camara": from_camara == to_camara,
        "from_fecha_referencia": from_row["fecha_referencia"].iloc[0],
        "to_fecha_referencia": to_row["fecha_referencia"].iloc[0],
        "from_duracion_referencia": from_row["duracion_referencia"].iloc[0],
        "to_duracion_referencia": to_row["duracion_referencia"].iloc[0],
    }

    if result is None:
        return {
            "ok": False,
            "error": f"'{from_label}' no tiene interacciones registradas todavía, "
                     "así que no hay una tasa base para extrapolar.",
            **base,
        }

    return {"ok": True, "error": None, "visits_from": visits_from, "visits_to": visits_to, "result": result, **base}


def recommend_best_destination_multi(zone_summary_combinado: pd.DataFrame, interaction_summary_combinado: pd.DataFrame,
                                       from_key: str) -> dict:
    """Análogo a recommend_best_destination(), pero para la vista
    combinada de tienda -- las candidatas recorren TODAS las zonas de
    TODAS las cámaras de la tienda (vía run_simulation_multi(), sin
    reimplementarla), así que el destino recomendado puede terminar en
    una cámara distinta a la de origen. El resultado ya trae
    same_camara/fecha-duración de referencia (heredado de
    run_simulation_multi) para que la interfaz pueda mostrar la
    advertencia de comparabilidad si corresponde."""
    candidate_keys = [
        _clave_compuesta(row["camara_origen"], row["zone_id"])
        for _, row in zone_summary_combinado.iterrows()
    ]
    candidate_keys = [k for k in candidate_keys if k != from_key]
    if not candidate_keys:
        return {"ok": False, "error": "No hay otra zona disponible para comparar como destino."}

    resultados = [
        run_simulation_multi(zone_summary_combinado, interaction_summary_combinado, from_key, k)
        for k in candidate_keys
    ]

    exitosas = [r for r in resultados if r.get("ok")]
    if not exitosas:
        return resultados[0]

    mejor = max(exitosas, key=lambda r: r["result"]["cambio_pct"])
    if mejor["result"]["cambio_pct"] <= 0:
        return {
            "ok": False,
            "no_improvement": True,
            "from_label": mejor["from_label"],
            "from_camara": mejor["from_camara"],
            "error": f"Esta zona ya parece estar bien ubicada -- comparamos contra {len(exitosas)} zona(s) "
                     "candidata(s) (en esta y otras cámaras de la tienda) y no encontramos un destino que "
                     "mejore su interacción actual.",
        }

    mejor["n_candidatos_evaluados"] = len(exitosas)
    mejor["recomendado"] = True
    return mejor
