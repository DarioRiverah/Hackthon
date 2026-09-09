"""
Lógica de la sección "Tendencias": compara los resultados de una
tienda entre dos fechas guardadas en el historial (data/output/history.db).

Requiere que las corridas se hayan procesado con --record-history en
run_pipeline.py -- si nunca se guardó ninguna fecha, el backend web
debe mostrar una guía de cómo hacerlo (usa get_available_dates() para
decidir eso).

100% lógica pura (sin Streamlit ni Flask).
"""

import datetime
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
from history_db import get_available_dates, compare_dates, get_zone_summary_for_date

# Cómo agregar cada métrica al combinar varias fechas en un mismo bucket
# (semana/mes) -- una duración/tasa promedio NO se suma entre fechas
# (sumar "18.5s de permanencia" + "22s de permanencia" no significa
# nada), pero las visitas totales sí representan una cantidad real
# acumulada en el período.
_BUCKET_AGGREGATION = {
    "total_visits": "sum",
    "stop_rate_pct": "mean",
    "avg_dwell_seconds": "mean",
}


METRIC_LABELS = {
    "total_visits": "Visitas totales",
    "stop_rate_pct": "Tasa de detención (%)",
    "avg_dwell_seconds": "Permanencia promedio (s)",
}


def get_trends_data(store_name: str, date_a: str = None, date_b: str = None) -> dict:
    """Punto de entrada único para el backend web.

    Devuelve siempre:
      {"dates": list[str], "has_enough_dates": bool,
       "date_a": str|None, "date_b": str|None,
       "same_dates": bool, "cards": list[dict]}

    "cards" trae, por zona, una lista de métricas ya con su etiqueta en
    español y el cambio porcentual formateado -- la plantilla solo
    itera y muestra, sin repetir lógica de negocio. Si no se piden
    date_a/date_b explícitas, usa las dos más recientes por defecto
    (mismo comportamiento que tenía el selector de Streamlit)."""
    dates = get_available_dates(store_name)

    if len(dates) < 2:
        return {
            "dates": dates, "has_enough_dates": False,
            "date_a": None, "date_b": None, "same_dates": False, "cards": [],
        }

    date_b = date_b or dates[0]
    date_a = date_a or dates[min(1, len(dates) - 1)]

    if date_a == date_b:
        return {
            "dates": dates, "has_enough_dates": True,
            "date_a": date_a, "date_b": date_b, "same_dates": True, "cards": [],
        }

    comparison_df = compare_dates(store_name, date_a, date_b)
    if comparison_df.empty:
        return {
            "dates": dates, "has_enough_dates": True,
            "date_a": date_a, "date_b": date_b, "same_dates": False, "cards": [],
        }

    cards = []
    for zone_label in comparison_df["zone_label"].unique():
        zone_data = comparison_df[comparison_df["zone_label"] == zone_label]
        metrics = []
        for _, row in zone_data.iterrows():
            pct = row["cambio_pct"]
            metrics.append({
                "label": METRIC_LABELS.get(row["metrica"], row["metrica"]),
                "value_b": f"{row[f'valor_{date_b}']:.1f}",
                "value_a": f"{row[f'valor_{date_a}']:.1f}",
                "delta_str": f"{pct:+.0f}%" if pct is not None else "N/A",
                "delta_positive": (pct is not None and pct > 0),
            })
        cards.append({"zone_label": zone_label, "metrics": metrics})

    return {
        "dates": dates, "has_enough_dates": True,
        "date_a": date_a, "date_b": date_b, "same_dates": False, "cards": cards,
    }


def get_history_series(store_name: str) -> dict:
    """Serie histórica completa (TODAS las fechas guardadas, no solo un
    par) por zona y métrica -- a diferencia de compare_dates/get_trends_data
    (que solo comparan A vs. B), esto arma la evolución completa para
    graficarla como línea de tiempo real. Estructura pensada para
    consumirse directamente desde Chart.js en el frontend:

      {"has_data": bool, "labels": [fecha, ...] (orden cronológico ascendente),
       "metric_options": {clave_metrica: etiqueta_es},
       "series": {clave_metrica: [{"zone_label": str, "data": [valor|None, ...]}]}}

    Un valor es None cuando esa zona no tiene registro para esa fecha
    (por ejemplo, una zona calibrada después de la primera corrida
    guardada) -- Chart.js salta huecos `null` sin romper la línea."""
    dates_desc = get_available_dates(store_name)
    if len(dates_desc) < 2:
        return {"has_data": False, "labels": [], "metric_options": METRIC_LABELS, "series": {}}

    dates_asc = list(reversed(dates_desc))
    per_date_df = {d: get_zone_summary_for_date(store_name, d) for d in dates_asc}

    zone_labels = sorted({
        label
        for df in per_date_df.values()
        for label in df["zone_label"].tolist()
    })

    series = {}
    for metric in METRIC_LABELS:
        zone_series = []
        for zone_label in zone_labels:
            values = []
            for d in dates_asc:
                df = per_date_df[d]
                row = df[df["zone_label"] == zone_label]
                values.append(round(float(row.iloc[0][metric]), 2) if not row.empty else None)
            zone_series.append({"zone_label": zone_label, "data": values})
        series[metric] = zone_series

    return {
        "has_data": True, "labels": dates_asc,
        "metric_options": METRIC_LABELS, "series": series,
    }


def _bucket_key(date_str: str, agrupacion: str) -> str:
    d = datetime.date.fromisoformat(date_str)
    if agrupacion == "semana":
        iso_year, iso_week, _ = d.isocalendar()
        return f"{iso_year}-S{iso_week:02d}"
    return f"{d.year}-{d.month:02d}"  # "mes"


def get_history_series_agrupada(store_name: str, agrupacion: str = "semana") -> dict:
    """Análoga a get_history_series(), pero agrupa TODAS las fechas
    guardadas por semana ISO o por mes calendario en vez de graficar
    cada fecha suelta -- útil cuando ya se acumularon muchas corridas y
    una línea de tiempo punto-por-fecha se vuelve ilegible. Reutiliza
    get_available_dates()/get_zone_summary_for_date(), no reimplementa
    la lectura de history.db.

    Devuelve la MISMA forma que get_history_series() (para alimentar el
    mismo <canvas> de Chart.js sin lógica adicional en el frontend), más
    "has_enough_buckets": si hay menos de 2 buckets distintos, agrupar
    no aporta nada -- se devuelve has_enough_buckets=False para que la
    plantilla muestre un mensaje honesto en vez de un gráfico vacío o
    con un solo punto (que parecería un error, no falta de datos)."""
    assert agrupacion in ("semana", "mes"), f"agrupación desconocida: {agrupacion}"

    dates_desc = get_available_dates(store_name)
    if not dates_desc:
        return {
            "has_data": False, "has_enough_buckets": False, "n_buckets": 0,
            "labels": [], "metric_options": METRIC_LABELS, "series": {},
        }

    dates_asc = list(reversed(dates_desc))
    per_date_df = {d: get_zone_summary_for_date(store_name, d) for d in dates_asc}

    buckets = {}
    for d in dates_asc:
        buckets.setdefault(_bucket_key(d, agrupacion), []).append(d)
    bucket_keys = sorted(buckets.keys())

    if len(bucket_keys) < 2:
        return {
            "has_data": True, "has_enough_buckets": False, "n_buckets": len(bucket_keys),
            "labels": [], "metric_options": METRIC_LABELS, "series": {},
        }

    zone_labels = sorted({
        label for df in per_date_df.values() for label in df["zone_label"].tolist()
    })

    series = {}
    for metric, agg in _BUCKET_AGGREGATION.items():
        zone_series = []
        for zone_label in zone_labels:
            values = []
            for bkey in bucket_keys:
                vals = []
                for d in buckets[bkey]:
                    row = per_date_df[d][per_date_df[d]["zone_label"] == zone_label]
                    if not row.empty:
                        vals.append(float(row.iloc[0][metric]))
                if not vals:
                    values.append(None)
                elif agg == "sum":
                    values.append(round(sum(vals), 2))
                else:
                    values.append(round(sum(vals) / len(vals), 2))
            zone_series.append({"zone_label": zone_label, "data": values})
        series[metric] = zone_series

    return {
        "has_data": True, "has_enough_buckets": True, "n_buckets": len(bucket_keys),
        "labels": bucket_keys, "metric_options": METRIC_LABELS, "series": series,
    }
