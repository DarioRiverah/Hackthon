"""
Validación formal contra las etiquetas reales de MERL (.mat).

MERL anota 5 sub-acciones por separado: Reach To Shelf, Retract From
Shelf, Hand In Shelf, Inspect Product, Inspect Shelf. Nuestro sistema
mide algo más amplio: desde que la muñeca entra a la zona del estante
hasta que sale -- lo cual normalmente abarca reach + hand-in + retract
como un solo episodio continuo.

Por eso, para una comparación justa, este script FUSIONA las 3
sub-acciones de contacto físico con el estante (índices 0, 1, 2 de
tlabs: Reach, Retract, Hand In Shelf) en "episodios de contacto"
consolidados, y compara eso contra nuestros propios eventos de
interacción ya detectados -- usando superposición temporal (IoU 1D),
no solo un conteo de sub-acciones sueltas.

Uso:
    python pipeline\\validate_merl_labels.py --label data\\raw\\1_2_label.mat --events data\\output\\interaction_events_merl_demo.csv --fps 30
"""

import argparse
import os

import pandas as pd
import scipy.io

# Índices de tlabs correspondientes a contacto físico con el estante
# (se excluyen "Inspect Product" e "Inspect Shelf", que son inspección
# visual/sostenida, no necesariamente con la mano dentro del estante).
SHELF_CONTACT_INDICES = [0, 1, 2]  # Reach To Shelf, Retract From Shelf, Hand In Shelf
ACTION_NAMES = ["Reach To Shelf", "Retract From Shelf", "Hand In Shelf",
                "Inspect Product", "Inspect Shelf"]


def parse_args():
    parser = argparse.ArgumentParser(description="Valida eventos de interacción contra etiquetas reales de MERL.")
    parser.add_argument("--label", type=str, required=True, help="Archivo .mat de etiquetas de MERL")
    parser.add_argument("--events", type=str, required=True,
                         help="CSV de interaction_events ya generado por nuestro pipeline")
    parser.add_argument("--fps", type=float, required=True, help="FPS del video (para convertir frames a segundos)")
    parser.add_argument("--merge-gap", type=float, default=1.0,
                         help="Máximo gap (segundos) para fusionar sub-acciones de MERL en un mismo episodio (default: 1.0)")
    parser.add_argument("--iou-threshold", type=float, default=0.2,
                         help="Superposición temporal mínima para considerar que un evento coincide (default: 0.2, "
                              "deliberadamente permisivo ya que los límites exactos difieren por metodología)")
    return parser.parse_args()


def load_merl_shelf_episodes(mat_path: str, fps: float, merge_gap: float):
    data = scipy.io.loadmat(mat_path)
    tlabs = data["tlabs"]

    all_intervals = []
    for idx in SHELF_CONTACT_INDICES:
        frame_pairs = tlabs[idx][0]  # array Nx2 de [frame_inicio, frame_fin]
        for start_frame, end_frame in frame_pairs:
            all_intervals.append((start_frame / fps, end_frame / fps))

    return merge_intervals(all_intervals, merge_gap)


def merge_intervals(intervals: list, max_gap: float) -> list:
    if not intervals:
        return []
    intervals = sorted(intervals)
    merged = [list(intervals[0])]
    for start, end in intervals[1:]:
        if start - merged[-1][1] <= max_gap:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def temporal_iou(a, b) -> float:
    start = max(a[0], b[0])
    end = min(a[1], b[1])
    intersection = max(0, end - start)
    union = max(a[1], b[1]) - min(a[0], b[0])
    return intersection / union if union > 0 else 0


def match_episodes(ground_truth: list, detected: list, iou_threshold: float):
    matched_detected = set()
    matches = []

    for gt in ground_truth:
        best_iou, best_j = 0, None
        for j, det in enumerate(detected):
            if j in matched_detected:
                continue
            iou = temporal_iou(gt, det)
            if iou > best_iou:
                best_iou, best_j = iou, j

        if best_iou >= iou_threshold:
            matched_detected.add(best_j)
            matches.append((gt, detected[best_j], best_iou))
        else:
            matches.append((gt, None, 0))

    unmatched_detected = [detected[j] for j in range(len(detected)) if j not in matched_detected]
    return matches, unmatched_detected


def coverage_recall(ground_truth: list, detected: list) -> tuple:
    """Métrica complementaria, menos estricta que el emparejamiento uno-a-uno:
    para cada episodio real, calcula qué % de SU DURACIÓN cae dentro de
    ALGUNO de los eventos detectados (sin importar si el evento detectado
    es mucho más ancho). Responde "¿estábamos presentes durante ese
    momento real?", en vez de exigir que los límites coincidan casi
    exactamente. Útil para diagnosticar si un score bajo en el
    emparejamiento estricto se debe a un problema real de detección, o
    solo a una diferencia de granularidad (eventos nuestros más anchos
    que contienen varios episodios reales adentro)."""
    per_episode_coverage = []
    total_gt_duration = 0
    total_covered_duration = 0

    for gt_start, gt_end in ground_truth:
        gt_duration = gt_end - gt_start
        covered = 0
        for det_start, det_end in detected:
            overlap_start = max(gt_start, det_start)
            overlap_end = min(gt_end, det_end)
            covered += max(0, overlap_end - overlap_start)
        covered = min(covered, gt_duration)  # no contar doble si se solapan varios detectados
        pct = covered / gt_duration if gt_duration > 0 else 0
        per_episode_coverage.append(((gt_start, gt_end), pct))
        total_gt_duration += gt_duration
        total_covered_duration += covered

    overall_pct = total_covered_duration / total_gt_duration if total_gt_duration > 0 else 0
    return per_episode_coverage, overall_pct


def main():
    args = parse_args()

    if not os.path.exists(args.label):
        print(f"ERROR: no se encontró '{args.label}'")
        return
    if not os.path.exists(args.events):
        print(f"ERROR: no se encontró '{args.events}'")
        return

    ground_truth = load_merl_shelf_episodes(args.label, args.fps, args.merge_gap)
    events_df = pd.read_csv(args.events)
    detected = list(zip(events_df["start_time"], events_df["end_time"]))

    print(f"Episodios reales de MERL (fusionados): {len(ground_truth)}")
    print(f"Eventos detectados por nuestro sistema: {len(detected)}")
    print()

    matches, unmatched_detected = match_episodes(ground_truth, detected, args.iou_threshold)

    tp = sum(1 for _, det, _ in matches if det is not None)
    fn = sum(1 for _, det, _ in matches if det is None)
    fp = len(unmatched_detected)

    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    print("=" * 70)
    print("DETALLE POR EPISODIO REAL (MERL) -- emparejamiento estricto uno-a-uno")
    print("=" * 70)
    for gt, det, iou in matches:
        gt_str = f"[{gt[0]:.1f}s - {gt[1]:.1f}s]"
        if det is not None:
            det_str = f"[{det[0]:.1f}s - {det[1]:.1f}s]"
            print(f"  MERL {gt_str} <-> Detectado {det_str}  (superposición: {iou:.2f})")
        else:
            print(f"  MERL {gt_str} <-> SIN COINCIDENCIA (evento no detectado)")

    if unmatched_detected:
        print("\nEventos detectados por nosotros SIN respaldo en las etiquetas de MERL:")
        for det in unmatched_detected:
            print(f"  Detectado [{det[0]:.1f}s - {det[1]:.1f}s]  <-> sin episodio real correspondiente")

    print()
    print("=" * 70)
    print("RESULTADO (emparejamiento estricto uno-a-uno)")
    print("=" * 70)
    print(f"TP={tp}  FP={fp}  FN={fn}")
    print(f"Precisión: {precision:.1%}   Recall: {recall:.1%}   F1: {f1:.1%}")

    # --- Métrica complementaria: cobertura temporal ---
    per_episode_coverage, overall_coverage = coverage_recall(ground_truth, detected)

    print()
    print("=" * 70)
    print("MÉTRICA COMPLEMENTARIA: cobertura temporal (menos estricta)")
    print("=" * 70)
    print("¿Qué % de la DURACIÓN de cada episodio real cae dentro de algún evento")
    print("detectado, sin importar si el evento detectado es más ancho?\n")
    for (start, end), pct in per_episode_coverage:
        print(f"  MERL [{start:.1f}s - {end:.1f}s]: {pct:.0%} cubierto")

    print()
    print(f"COBERTURA TEMPORAL GLOBAL: {overall_coverage:.1%}")
    print("(% del tiempo total de interacción real que cae dentro de algún evento detectado)")


if __name__ == "__main__":
    main()