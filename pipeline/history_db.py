"""
Base de datos local (SQLite) para guardar resultados de cada corrida
del pipeline, etiquetados con una fecha -- permite comparar "hace 2
semanas" contra "hoy" sin depender de archivos sueltos que se
sobreescriben.

No agrega ninguna dependencia nueva: sqlite3 viene incluido en Python.

Cada corrida se identifica por (store_name, run_date). Si vuelves a
correr el pipeline con la misma tienda y fecha, el registro se
ACTUALIZA (no se duplica) -- así, reprocesar el mismo video mientras
ajustas parámetros no ensucia el historial.

La fecha (run_date) es una etiqueta que TÚ decides -- no tiene que ser
la fecha real de hoy. Si estás procesando un video que representa la
grabación de hace 2 semanas, pásale esa fecha explícitamente.
"""

import os
import sqlite3

DEFAULT_DB_PATH = "data/output/history.db"


def init_db(db_path: str = DEFAULT_DB_PATH):
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS zone_summary_history (
            store_name TEXT NOT NULL,
            run_date TEXT NOT NULL,
            zone_id TEXT NOT NULL,
            zone_label TEXT,
            total_visits INTEGER,
            stops INTEGER,
            pass_throughs INTEGER,
            stop_rate_pct REAL,
            avg_dwell_seconds REAL,
            max_dwell_seconds REAL,
            PRIMARY KEY (store_name, run_date, zone_id)
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS interaction_summary_history (
            store_name TEXT NOT NULL,
            run_date TEXT NOT NULL,
            zone_id TEXT NOT NULL,
            zone_label TEXT,
            total_interactions INTEGER,
            toques_breves INTEGER,
            interacciones_medias INTEGER,
            interacciones_prolongadas INTEGER,
            avg_duration_seconds REAL,
            PRIMARY KEY (store_name, run_date, zone_id)
        )
    """)
    conn.commit()
    return conn


def record_run(store_name: str, run_date: str, zone_summary_df, interaction_summary_df=None,
                db_path: str = DEFAULT_DB_PATH):
    """Guarda (o actualiza) los resultados de una corrida en la base de
    datos, bajo la fecha indicada."""
    conn = init_db(db_path)

    for _, row in zone_summary_df.iterrows():
        conn.execute("""
            INSERT OR REPLACE INTO zone_summary_history
            (store_name, run_date, zone_id, zone_label, total_visits, stops,
             pass_throughs, stop_rate_pct, avg_dwell_seconds, max_dwell_seconds)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            store_name, run_date, row["zone_id"], row["zone_label"],
            int(row["total_visits"]), int(row["stops"]), int(row["pass_throughs"]),
            float(row["stop_rate_pct"]), float(row["avg_dwell_seconds"]), float(row["max_dwell_seconds"]),
        ))

    if interaction_summary_df is not None:
        for _, row in interaction_summary_df.iterrows():
            conn.execute("""
                INSERT OR REPLACE INTO interaction_summary_history
                (store_name, run_date, zone_id, zone_label, total_interactions,
                 toques_breves, interacciones_medias, interacciones_prolongadas, avg_duration_seconds)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                store_name, run_date, row["zone_id"], row["zone_label"],
                int(row["total_interactions"]), int(row["toques_breves"]),
                int(row["interacciones_medias"]), int(row["interacciones_prolongadas"]),
                float(row["avg_duration_seconds"]),
            ))

    conn.commit()
    conn.close()


def get_available_dates(store_name: str, db_path: str = DEFAULT_DB_PATH) -> list:
    """Devuelve las fechas disponibles para una tienda, más recientes primero."""
    if not os.path.exists(db_path):
        return []
    conn = sqlite3.connect(db_path)
    rows = conn.execute("""
        SELECT DISTINCT run_date FROM zone_summary_history
        WHERE store_name = ? ORDER BY run_date DESC
    """, (store_name,)).fetchall()
    conn.close()
    return [r[0] for r in rows]


def get_zone_summary_for_date(store_name: str, run_date: str, db_path: str = DEFAULT_DB_PATH):
    """Devuelve un DataFrame con el resumen de zonas para una fecha específica."""
    import pandas as pd
    if not os.path.exists(db_path):
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("""
        SELECT * FROM zone_summary_history WHERE store_name = ? AND run_date = ?
    """, conn, params=(store_name, run_date))
    conn.close()
    return df


def get_interaction_summary_for_date(store_name: str, run_date: str, db_path: str = DEFAULT_DB_PATH):
    """Devuelve un DataFrame con el resumen de interacción para una fecha específica."""
    import pandas as pd
    if not os.path.exists(db_path):
        return pd.DataFrame()
    conn = sqlite3.connect(db_path)
    df = pd.read_sql_query("""
        SELECT * FROM interaction_summary_history WHERE store_name = ? AND run_date = ?
    """, conn, params=(store_name, run_date))
    conn.close()
    return df


def delete_run(store_name: str, run_date: str, db_path: str = DEFAULT_DB_PATH) -> None:
    """Borra los registros de una corrida (ambas tablas) para (store_name,
    run_date) -- usado al eliminar una fecha archivada (ver
    dashboard/routes/data_routes.py y pipeline/history_archive.py). No
    falla si no existía nada que borrar."""
    if not os.path.exists(db_path):
        return
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM zone_summary_history WHERE store_name = ? AND run_date = ?", (store_name, run_date))
    conn.execute("DELETE FROM interaction_summary_history WHERE store_name = ? AND run_date = ?", (store_name, run_date))
    conn.commit()
    conn.close()


def compare_dates(store_name: str, date_a: str, date_b: str, db_path: str = DEFAULT_DB_PATH):
    """Compara las métricas de zona entre dos fechas (A = antes, B = después).
    Devuelve un DataFrame con el valor en cada fecha, la diferencia, y el
    cambio porcentual, por zona y métrica."""
    import pandas as pd

    df_a = get_zone_summary_for_date(store_name, date_a, db_path)
    df_b = get_zone_summary_for_date(store_name, date_b, db_path)

    if df_a.empty or df_b.empty:
        return pd.DataFrame()

    merged = df_a.merge(df_b, on=["zone_id", "zone_label"], suffixes=("_a", "_b"))

    metrics = ["total_visits", "stop_rate_pct", "avg_dwell_seconds"]
    rows = []
    for _, row in merged.iterrows():
        for metric in metrics:
            val_a = row[f"{metric}_a"]
            val_b = row[f"{metric}_b"]
            delta = val_b - val_a
            pct_change = (delta / val_a * 100) if val_a != 0 else None
            rows.append({
                "zone_label": row["zone_label"],
                "metrica": metric,
                f"valor_{date_a}": val_a,
                f"valor_{date_b}": val_b,
                "cambio": delta,
                "cambio_pct": pct_change,
            })

    return pd.DataFrame(rows)