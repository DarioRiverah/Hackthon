"""
Costura (stitching) de tracks fragmentados.

Problema que resuelve: cuando el detector pierde momentáneamente a una
persona (ej. por pose atípica en cámara cenital, oclusión parcial al
interactuar con el estante), ByteTrack le asigna un ID nuevo al
recuperarla, aunque sea la misma persona.

Este script NO vuelve a mirar el video ni usa reconocimiento facial ni
ningún dato biométrico — solo aplica una regla geométrica simple sobre
las posiciones (x, y) y tiempos ya calculados por detect_and_track.py:

    Si el track A termina en el frame F en la posición (x, y),
    y el track B empieza poco después (dentro de un margen de tiempo)
    cerca de esa misma posición (dentro de un margen de distancia),
    se asume que A y B son la misma persona y se fusionan bajo un
    mismo id_persona.

Uso:
    python pipeline\\track_stitching.py --input data\\processed\\tracks_1_2_crop.csv
    python pipeline\\track_stitching.py --input data\\processed\\tracks_1_2_crop.csv --max-gap-seconds 2.5 --max-distance-px 80
"""

import argparse
import os
import pandas as pd


def parse_args():
    parser = argparse.ArgumentParser(description="Reconecta tracks fragmentados por proximidad espacio-temporal.")
    parser.add_argument("--input", type=str, required=True,
                         help="CSV de tracks generado por detect_and_track.py")
    parser.add_argument("--output", type=str, default=None,
                         help="CSV de salida (default: <input>_stitched.csv)")
    parser.add_argument("--max-gap-seconds", type=float, default=2.0,
                         help="Máximo tiempo (segundos) entre que un track termina y otro empieza para considerarlos la misma persona (default: 2.0)")
    parser.add_argument("--max-speed-px-per-s", type=float, default=500.0,
                         help="Velocidad máxima plausible (píxeles/segundo) para considerar que es la misma persona moviéndose, no otra distinta (default: 500.0)")
    parser.add_argument("--diagnose", action="store_true",
                         help="En vez de fusionar, imprime los gaps de tiempo/distancia/velocidad implícita entre cada par de tracks, para elegir umbrales informadamente")
    parser.add_argument("--min-detections", type=int, default=2,
                         help="Después de la costura, descarta cualquier id_persona final que quede "
                              "con menos de este número de detecciones en total (default: 2). Un "
                              "id_persona con una sola detección aislada, sin ningún candidato "
                              "razonable con quien unirse, suele ser ruido de un solo cuadro "
                              "(parpadeo de detección), no una persona real. Usa 0 para desactivar "
                              "este filtro.")
    return parser.parse_args()


def compute_direction(group_sorted: pd.DataFrame, n_points: int, from_end: bool):
    """Vector de dirección de movimiento reciente: hacia dónde iba un
    track justo antes de terminar (from_end=True), o hacia dónde arranca
    justo al empezar (from_end=False). Usa varios puntos (no solo el
    primero/último) para suavizar el ruido de detección frame a frame."""
    points = group_sorted.tail(n_points) if from_end else group_sorted.head(n_points)
    if len(points) < 2:
        return (0.0, 0.0)  # muy pocos puntos para saber dirección -- neutral
    dx = points["x_center"].iloc[-1] - points["x_center"].iloc[0]
    dy = points["y_center"].iloc[-1] - points["y_center"].iloc[0]
    return (dx, dy)


def direction_similarity(vec_a, vec_b) -> float:
    """Similitud coseno entre dos vectores de dirección: 1.0 = misma
    dirección, -1.0 = dirección opuesta, 0.0 = sin información suficiente
    o direcciones perpendiculares."""
    norm_a = (vec_a[0] ** 2 + vec_a[1] ** 2) ** 0.5
    norm_b = (vec_b[0] ** 2 + vec_b[1] ** 2) ** 0.5
    if norm_a == 0 or norm_b == 0:
        return 0.0
    dot = vec_a[0] * vec_b[0] + vec_a[1] * vec_b[1]
    return dot / (norm_a * norm_b)


def diagnose_gaps(df: pd.DataFrame):
    """Para cada track, muestra el candidato de reconexión más cercano en el tiempo
    (el siguiente track que empieza después de que este termina), con su gap de
    tiempo, distancia, y VELOCIDAD IMPLÍCITA (distancia/tiempo).

    La velocidad implícita es la señal más importante: si da un valor absurdamente
    alto (ej. miles de px/s), significa que esa "reconexión" requeriría que la
    persona se teletransportara -- es decir, casi seguro son dos personas
    DISTINTAS que coincidieron en tiempo, no la misma persona perdida y recuperada.
    """
    summaries = []
    for track_id, group in df.groupby("track_id"):
        group_sorted = group.sort_values("frame")
        first_row = group_sorted.iloc[0]
        last_row = group_sorted.iloc[-1]
        summaries.append({
            "track_id": track_id,
            "start_time": first_row["timestamp"],
            "end_time": last_row["timestamp"],
            "start_x": first_row["x_center"],
            "start_y": first_row["y_center"],
            "end_x": last_row["x_center"],
            "end_y": last_row["y_center"],
        })
    summaries_df = pd.DataFrame(summaries).sort_values("start_time").reset_index(drop=True)

    rows = summaries_df.to_dict("records")
    candidates = []
    for ended in rows:
        best = None
        for started in rows:
            if ended["track_id"] == started["track_id"]:
                continue
            gap = started["start_time"] - ended["end_time"]
            if gap < 0:
                continue
            dist = ((ended["end_x"] - started["start_x"]) ** 2 +
                     (ended["end_y"] - started["start_y"]) ** 2) ** 0.5
            if best is None or gap < best[2]:
                best = (ended["track_id"], started["track_id"], gap, dist)
        if best:
            candidates.append(best)

    # Ordenar por velocidad implícita DESCENDENTE -> los casos más sospechosos primero
    def implied_speed(c):
        _, _, gap, dist = c
        return dist / max(gap, 0.03)  # 0.03s ~ evita división por cero

    candidates.sort(key=implied_speed, reverse=True)

    print(f"{'Termina':>8} | {'Empieza':>8} | {'Gap (s)':>8} | {'Dist (px)':>10} | {'Vel. implícita (px/s)':>22}")
    print("-" * 68)
    for ended_id, started_id, gap, dist in candidates:
        speed = implied_speed((ended_id, started_id, gap, dist))
        flag = "  <-- SOSPECHOSO (imposible físicamente)" if speed > 800 else ""
        print(f"{ended_id:>8} | {started_id:>8} | {gap:>8.2f} | {dist:>10.1f} | {speed:>22.1f}{flag}")

    print("\nGuía: la velocidad de una persona caminando rápido en video suele ser")
    print("bastante menor a 400-600 px/s (depende de la resolución/distancia de la")
    print("cámara). Valores muy por encima de eso casi seguro son personas distintas,")
    print("no la misma persona reapareciendo.")


def stitch_tracks(df: pd.DataFrame, max_gap_seconds: float, max_speed_px_per_s: float,
                   direction_points: int = 3, min_detections: int = 2, verbose: bool = True) -> pd.DataFrame:
    # Resumen de cada track: primer y último punto (tiempo y posición),
    # más su vector de dirección de entrada/salida para desempatar
    # candidatos ambiguos por consistencia de movimiento, no solo velocidad.
    summaries = []
    track_groups = {}
    for track_id, group in df.groupby("track_id"):
        group_sorted = group.sort_values("frame")
        track_groups[track_id] = group_sorted
        first_row = group_sorted.iloc[0]
        last_row = group_sorted.iloc[-1]
        summaries.append({
            "track_id": track_id,
            "start_time": first_row["timestamp"],
            "end_time": last_row["timestamp"],
            "start_x": first_row["x_center"],
            "start_y": first_row["y_center"],
            "end_x": last_row["x_center"],
            "end_y": last_row["y_center"],
            "exit_direction": compute_direction(group_sorted, direction_points, from_end=True),
            "entry_direction": compute_direction(group_sorted, direction_points, from_end=False),
        })
    summaries_df = pd.DataFrame(summaries).sort_values("start_time").reset_index(drop=True)

    # Union-Find simple para agrupar ids que se deben fusionar
    parent = {tid: tid for tid in summaries_df["track_id"]}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    records = summaries_df.to_dict("records")
    ambiguous_cases = []

    # Para cada track que termina, buscar TODOS los candidatos FÍSICAMENTE
    # PLAUSIBLES (velocidad implícita por debajo del máximo humano razonable)
    for ended in records:
        candidates = []
        for started in records:
            if ended["track_id"] == started["track_id"]:
                continue
            gap = started["start_time"] - ended["end_time"]
            if gap < 0 or gap > max_gap_seconds:
                continue
            dist = ((ended["end_x"] - started["start_x"]) ** 2 +
                     (ended["end_y"] - started["start_y"]) ** 2) ** 0.5
            speed = dist / max(gap, 0.03)  # evita división por cero en gaps ~0

            if speed <= max_speed_px_per_s:
                dir_sim = direction_similarity(ended["exit_direction"], started["entry_direction"])
                candidates.append((started["track_id"], gap, dist, speed, dir_sim))

        if not candidates:
            continue

        # Desempate: prioriza CONSISTENCIA DE DIRECCIÓN (una persona real
        # tiende a mantener su dirección de movimiento tras una pérdida
        # breve de detección; dos personas distintas cruzándose no tienen
        # por qué coincidir en dirección), y solo usa la velocidad más baja
        # como criterio secundario si la dirección no distingue el caso.
        candidates.sort(key=lambda c: (-c[4], c[3]))

        if len(candidates) > 1:
            ambiguous_cases.append({
                "ended_track": ended["track_id"],
                "candidates": candidates,
            })

        best_match = candidates[0][0]
        union(ended["track_id"], best_match)

    if verbose and ambiguous_cases:
        print("\nADVERTENCIA: se encontraron casos ambiguos (más de un candidato posible).")
        print("Se fusionó con el de mayor consistencia de dirección (y menor velocidad como desempate), revisa si tiene sentido:\n")
        for case in ambiguous_cases:
            print(f"  Track {case['ended_track']} termina -> candidatos posibles:")
            for cand_id, gap, dist, speed, dir_sim in case["candidates"]:
                marker = " <- elegido" if cand_id == case["candidates"][0][0] else ""
                print(f"      track {cand_id}: gap={gap:.2f}s, dist={dist:.1f}px, vel={speed:.1f}px/s, "
                      f"direccion={dir_sim:+.2f}{marker}")
        print()

    # Mapear cada track_id original a su id_persona final (el representante del grupo)
    id_map = {tid: find(tid) for tid in parent}
    df = df.copy()
    df["id_persona"] = df["track_id"].map(id_map)

    if min_detections > 0:
        df = filter_isolated_noise(df, min_detections, verbose)

    return df


def filter_isolated_noise(df: pd.DataFrame, min_detections: int, verbose: bool = True) -> pd.DataFrame:
    """Descarta cualquier id_persona final que quede con menos de
    min_detections detecciones en total -- típicamente un parpadeo de
    detección de un solo cuadro que no encontró ningún candidato
    razonable con quien unirse durante la costura (ver
    docs/architecture.md sección 15 para el caso real que motivó esto:
    una detección aislada de 1 cuadro, sin relación con el resto del
    video, que quedaba como una 'persona' separada)."""
    counts = df["id_persona"].value_counts()
    dropped_ids = counts[counts < min_detections].index.tolist()

    if dropped_ids and verbose:
        print(f"\nSe descartaron {len(dropped_ids)} id_persona con menos de {min_detections} "
              f"detección(es) (ruido de un solo cuadro, no personas reales):")
        for pid in dropped_ids:
            print(f"  id_persona {pid}: {counts[pid]} detección(es)")

    return df[~df["id_persona"].isin(dropped_ids)].copy()


def main():
    args = parse_args()

    if not os.path.exists(args.input):
        print(f"ERROR: no se encontró el archivo '{args.input}'")
        return

    df = pd.read_csv(args.input)

    if args.diagnose:
        diagnose_gaps(df)
        return

    output_path = args.output or args.input.replace(".csv", "_stitched.csv")
    n_ids_before = df["track_id"].nunique()

    stitched = stitch_tracks(df, args.max_gap_seconds, args.max_speed_px_per_s,
                              min_detections=args.min_detections)
    n_ids_after = stitched["id_persona"].nunique()

    stitched.to_csv(output_path, index=False)

    print("Costura de tracks completa.")
    print(f"IDs originales (fragmentados): {n_ids_before}")
    print(f"IDs finales (después de costura): {n_ids_after}")
    print(f"Archivo guardado en: {output_path}")


if __name__ == "__main__":
    main()