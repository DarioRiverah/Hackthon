"""
Orquestador del pipeline completo.

Encadena, en un solo comando, todos los pasos de procesamiento que hasta
ahora se corrían por separado:

    1. detect_and_track.py         -> UN SOLO modelo (YOLO26-pose) que en
                                       una sola pasada entrega tanto el
                                       tracking de cuerpo como la posición
                                       de muñeca (antes eran dos llamadas
                                       a dos modelos distintos)
    2. track_stitching.py          -> corrige fragmentación de tracks de cuerpo
    3. track_stitching.py          -> corrige fragmentación de tracks de mano [omitible]
    4. render_stitched_preview.py  -> UN SOLO video de verificación con IDs
                                       ya corregidos (caja de cuerpo + punto
                                       de muñeca superpuestos)
    5. zoning.py                   -> dwell time y clasificación pasa/detiene
    6. heatmap.py (flujo)          -> mapa de calor de tráfico corporal
    7. spaghetti_diagram.py        -> diagrama de trayectorias reales
    8. interaction_events.py       -> eventos de interacción con el estante [omitible]
    9. heatmap.py (interaccion)    -> mapa de calor de interacción de mano [omitible]

Los pasos 3, 8 y 9 se omiten con --skip-hands (el paso 4 sigue corriendo,
pero solo con la caja de cuerpo, sin el punto de mano).

NOTA: el pipeline ya no genera un heatmap "combinado" (tráfico +
interacción con contorno) -- se eliminó del flujo por simplificación:
el heatmap de flujo y el de interacción, cada uno por separado, ya
comunican esa información de forma más clara que la versión combinada
(ver docs/architecture.md, sección 17). `pipeline/heatmap.py` conserva
la función `render_combined_heatmap` y el modo `--mode combinado` por
si se quiere generar manualmente, pero ya no se invoca desde aquí.

IMPORTANTE sobre el video de verificación: el video que genera
detect_and_track.py en el paso 1 (tracked_preview_*.webm) muestra los
IDs CRUDOS, antes de la costura -- es NORMAL y ESPERADO que ahí una
misma persona aparezca con IDs distintos en momentos distintos (ver
docs/architecture.md, sección 3). Ese video es solo un diagnóstico
interno del paso 1, NO la verificación final. El video que sí
representa el resultado real usado por el resto del pipeline es el que
genera render_stitched_preview.py en el paso 4 (preview_corregido_*.webm)
-- ese es el que debe mostrarse a cualquier usuario final.

NOTA sobre el formato de estos videos de verificación: se generan en
.webm (códec VP8), no .mp4 -- ver docs/architecture.md sección 19 para
el porqué (mp4v no lo reproducen los navegadores, y H.264 real no está
disponible en esta instalación de OpenCV/FFmpeg).

NO incluye calibrate_zones.py -- ese paso es manual e interactivo por
naturaleza (requiere que una persona marque las zonas con clics) y debe
correrse una sola vez por cámara/tienda, antes de usar este orquestador.

REQUISITO PREVIO: debe existir config/zones_<store_name>.json

Uso (caso general, valores conservadores por defecto):
    python pipeline\\run_pipeline.py --video data\\raw\\mi_video.mp4 --store-name mi_tienda

Uso replicando exactamente lo ya validado para el clip de MERL (1 persona):
    python pipeline\\run_pipeline.py --video data\\raw\\1_2_crop.mp4 --store-name merl_demo ^
        --body-max-gap 15 --body-max-speed 500 --hand-max-gap 60 --hand-max-speed 200

Uso omitiendo el módulo de manos (más rápido, solo flujo/dwell):
    python pipeline\\run_pipeline.py --video data\\raw\\mi_video.mp4 --store-name mi_tienda --skip-hands
"""

import argparse
import os
import subprocess
import sys
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse_args():
    parser = argparse.ArgumentParser(description="Corre el pipeline completo de análisis sobre un video.")
    parser.add_argument("--video", type=str, required=True, help="Ruta del video a procesar")
    parser.add_argument("--store-name", type=str, required=True,
                         help="Nombre de la tienda/cámara (debe coincidir con config/zones_<store_name>.json)")

    parser.add_argument("--body-max-gap", type=float, default=2.0,
                         help="Costura de cuerpo: gap máximo en segundos (default: 2.0, conservador)")
    parser.add_argument("--body-max-speed", type=float, default=500.0,
                         help="Costura de cuerpo: velocidad máxima px/s (default: 500.0)")

    parser.add_argument("--hand-max-gap", type=float, default=5.0,
                         help="Costura de mano: gap máximo en segundos (default: 5.0, conservador)")
    parser.add_argument("--hand-max-speed", type=float, default=300.0,
                         help="Costura de mano: velocidad máxima px/s (default: 300.0)")

    parser.add_argument("--debounce-seconds", type=float, default=0.5,
                         help="Fusiona eventos de interacción muy cercanos entre sí (default: 0.5)")
    parser.add_argument("--conf", type=float, default=0.2,
                         help="Umbral de confianza de detección (default: 0.2)")
    parser.add_argument("--skip-hands", action="store_true",
                         help="Omite costura/interacción de manos (solo flujo + dwell time)")
    parser.add_argument("--spaghetti-min-distance", type=float, default=30.0,
                         help="Umbral de simplificación del diagrama de espagueti, en píxeles "
                              "(default: 30.0 -- funcionó bien para escenas de interacción de cerca; "
                              "para escenas de circulación amplia, un valor más bajo como 15 puede "
                              "conservar más detalle del recorrido)")
    parser.add_argument("--record-history", action="store_true",
                         help="Guarda los resultados de esta corrida en la base de datos histórica "
                              "(data/output/history.db), para poder compararlos más adelante contra "
                              "otra fecha. Por defecto NO se graba, para no ensuciar el historial "
                              "mientras se ajustan parámetros de prueba.")
    parser.add_argument("--run-date", type=str, default=None,
                         help="Fecha (YYYY-MM-DD) a asociar con esta corrida en el historial -- no "
                              "tiene que ser hoy, puede representar cuándo se grabó el video "
                              "(default: fecha de hoy si se omite)")
    parser.add_argument("--device", type=str, default="auto", choices=["auto", "cpu", "gpu"],
                         help="Dispositivo de procesamiento a forzar en el paso de detección "
                              "(default: %(default)s). 'auto' deja que Ultralytics elija GPU si hay "
                              "disponible o CPU si no, igual que siempre.")

    return parser.parse_args()


def run_step(step_num: int, total_steps: int, description: str, args_list: list,
             retry_env: dict = None) -> float:
    """Corre un paso del pipeline como subproceso, mostrando su salida en
    vivo. Detiene todo el orquestador si el paso falla, para no seguir
    encadenando sobre datos rotos.

    `retry_env`: red de seguridad de OpenVINO (ver pipeline/export_openvino.py
    y docs/architecture.md). El paso de detección (1) pasa
    {"DISABLE_OPENVINO": "1"} acá -- si el intento normal falla con
    CUALQUIER código de salida distinto de cero, se reintenta UNA vez con
    esa variable de entorno, que le indica a detect_and_track.py que use
    el modelo .pt original en vez del optimizado a OpenVINO. Esto es
    deliberadamente un reintento a nivel de PROCESO (no un try/except
    adentro del script) porque un fallo real de OpenVINO puede
    manifestarse como una caída nativa del proceso (segfault) que ningún
    try/except de Python puede atrapar -- confirmado de la forma difícil
    probando esto en desarrollo, ver docs/architecture.md."""
    print(f"\n{'=' * 70}")
    print(f"[{step_num}/{total_steps}] {description}")
    print(f"{'=' * 70}")

    command = [sys.executable] + args_list
    start = time.time()
    result = subprocess.run(command, cwd=PROJECT_ROOT)
    elapsed = time.time() - start

    if result.returncode != 0 and retry_env:
        print(f"\nAVISO: '{description}' falló (código {result.returncode}), posiblemente por el "
              f"modelo optimizado OpenVINO -- reintentando UNA vez con el modelo original (sin OpenVINO)...")
        env = {**os.environ, **retry_env}
        start = time.time()
        result = subprocess.run(command, cwd=PROJECT_ROOT, env=env)
        elapsed = time.time() - start

    if result.returncode != 0:
        print(f"\nERROR: el paso '{description}' falló (código de salida {result.returncode}).")
        print("Deteniendo el pipeline -- revisa el mensaje de error de arriba.")
        sys.exit(1)

    print(f"[{step_num}/{total_steps}] completado en {elapsed:.1f}s")
    return elapsed


def main():
    args = parse_args()

    zones_rel_path = f"config/zones_{args.store_name}.json"
    zones_abs_path = os.path.join(PROJECT_ROOT, zones_rel_path)

    if not os.path.exists(zones_abs_path):
        print(f"ERROR: no existe '{zones_rel_path}'.")
        print("Antes de correr el pipeline, calibra las zonas una vez con:")
        print(f"    python pipeline\\calibrate_zones.py --video {args.video} --store-name {args.store_name}")
        sys.exit(1)

    video_abs_path = os.path.join(PROJECT_ROOT, args.video)
    if not os.path.exists(video_abs_path):
        print(f"ERROR: no se encontró el video '{args.video}'")
        sys.exit(1)

    # El reintento automático sin OpenVINO (ver docstring de run_step) solo
    # tiene sentido para 'auto'/'cpu' -- OpenVINO ya se omite por completo
    # cuando se fuerza GPU (ver detect_and_track.py:load_model), así que
    # reintentar con DISABLE_OPENVINO=1 ahí no cambiaría nada y solo
    # duplicaría un fallo real de GPU (ej. no detectada) sin aportar nada.
    detection_retry_env = None if args.device == "gpu" else {"DISABLE_OPENVINO": "1"}

    video_basename = os.path.splitext(os.path.basename(args.video))[0]

    body_tracks_csv = f"data/processed/tracks_{video_basename}.csv"
    body_tracks_stitched_csv = f"data/processed/tracks_{video_basename}_stitched.csv"
    hand_tracks_csv = f"data/processed/hands_{video_basename}.csv"
    hand_tracks_stitched_csv = f"data/processed/hands_{video_basename}_stitched.csv"
    preview_corregido = f"data/processed/preview_corregido_{video_basename}.webm"

    total_start = time.time()
    timings = {}
    total_steps = 6 if args.skip_hands else 9
    step = 0

    step += 1
    timings["1_deteccion"] = run_step(
        step, total_steps, "Detección y tracking (YOLO26-pose: cuerpo + mano en una sola pasada)",
        ["pipeline/detect_and_track.py", "--video", args.video, "--conf", str(args.conf),
         "--device", args.device],
        retry_env=detection_retry_env,
    )

    step += 1
    timings["2_costura_cuerpo"] = run_step(
        step, total_steps, "Costura de tracks de cuerpo",
        ["pipeline/track_stitching.py", "--input", body_tracks_csv,
         "--max-gap-seconds", str(args.body_max_gap),
         "--max-speed-px-per-s", str(args.body_max_speed)],
    )

    if not args.skip_hands:
        step += 1
        timings["3_costura_manos"] = run_step(
            step, total_steps, "Costura de tracks de mano",
            ["pipeline/track_stitching.py", "--input", hand_tracks_csv,
             "--max-gap-seconds", str(args.hand_max_gap),
             "--max-speed-px-per-s", str(args.hand_max_speed)],
        )

    step += 1
    render_args = ["pipeline/render_stitched_preview.py", "--video", args.video,
                   "--body-csv", body_tracks_stitched_csv, "--output", preview_corregido]
    if not args.skip_hands:
        render_args += ["--hand-csv", hand_tracks_stitched_csv]
    timings["4_verificacion"] = run_step(
        step, total_steps, "Video de verificación (IDs corregidos: cuerpo + mano)", render_args,
    )

    step += 1
    timings["5_zonificacion"] = run_step(
        step, total_steps, "Zonificación y cálculo de dwell time",
        ["pipeline/zoning.py", "--tracks", body_tracks_stitched_csv,
         "--zones", zones_rel_path, "--output-prefix", args.store_name],
    )

    step += 1
    timings["6_heatmap_flujo"] = run_step(
        step, total_steps, "Heatmap de flujo (tráfico corporal)",
        ["pipeline/heatmap.py", "--video", args.video, "--tracks", body_tracks_csv,
         "--zones", zones_rel_path, "--mode", "flujo"],
    )

    step += 1
    timings["7_diagrama_espagueti"] = run_step(
        step, total_steps, "Diagrama de espagueti (trayectorias)",
        ["pipeline/spaghetti_diagram.py", "--video", args.video, "--tracks", body_tracks_stitched_csv,
         "--zones", zones_rel_path, "--min-distance", str(args.spaghetti_min_distance)],
    )

    if not args.skip_hands:
        step += 1
        timings["8_interaccion"] = run_step(
            step, total_steps, "Detección de eventos de interacción",
            ["pipeline/interaction_events.py", "--hands", hand_tracks_stitched_csv,
             "--zones", zones_rel_path, "--output-prefix", args.store_name,
             "--debounce-seconds", str(args.debounce_seconds)],
        )

        step += 1
        timings["9_heatmap_interaccion"] = run_step(
            step, total_steps, "Heatmap de interacción (mano)",
            ["pipeline/heatmap.py", "--video", args.video, "--tracks", hand_tracks_stitched_csv,
             "--zones", zones_rel_path, "--mode", "interaccion"],
        )

    if args.record_history:
        import datetime
        import pandas as pd
        sys.path.insert(0, PROJECT_ROOT)
        from pipeline.history_db import record_run
        from pipeline.history_archive import archive_run

        run_date = args.run_date or datetime.date.today().isoformat()
        zone_summary_path = os.path.join(PROJECT_ROOT, f"data/output/zone_summary_{args.store_name}.csv")
        interaction_summary_path = os.path.join(
            PROJECT_ROOT, f"data/output/interaction_summary_{args.store_name}.csv"
        )

        zone_summary_df = pd.read_csv(zone_summary_path) if os.path.exists(zone_summary_path) else None
        interaction_summary_df = (
            pd.read_csv(interaction_summary_path) if os.path.exists(interaction_summary_path) else None
        )

        if zone_summary_df is not None:
            record_run(args.store_name, run_date, zone_summary_df, interaction_summary_df)
            print(f"\nResultados guardados en el historial bajo la fecha '{run_date}'.")

            copied = archive_run(args.store_name, run_date, video_reference=args.video)
            print(f"Instantánea completa archivada en data/history/{args.store_name}/{run_date}/ "
                  f"({len(copied)} archivo(s); NO incluye video de verificación, ver docs/architecture.md sección 34).")
        else:
            print("\nAVISO: no se pudo guardar en el historial (no se encontró zone_summary).")

    total_elapsed = time.time() - total_start

    print(f"\n{'=' * 70}")
    print("PIPELINE COMPLETO")
    print(f"{'=' * 70}")
    for step_name, duration in timings.items():
        print(f"  {step_name}: {duration:.1f}s")
    print(f"  TOTAL: {total_elapsed:.1f}s ({total_elapsed / 60:.1f} min)")
    print(f"\nResultados guardados en data/output/ con prefijo '{args.store_name}'.")
    print("Para verlos, abre el dashboard:")
    print("    streamlit run dashboard\\app.py")


if __name__ == "__main__":
    main()
