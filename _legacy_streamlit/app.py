"""
Dashboard v2 - Panel de space management para el dueño de la tienda.

Rediseño de estructura y visual sobre la v1 (ver docs/architecture.md
para el historial de decisiones del proyecto). Cambios principales:

    - Flujo centrado en TIENDA, no en un interruptor global de modo.
      La barra lateral es un panel de control persistente: eliges una
      tienda y ves su estado (calibrada / procesada / con historial)
      sin perder contexto. Antes, cambiar entre "Analizar nuevo video"
      y "Panel de resultados" perdía de vista en qué tienda estabas.
    - 6 pestañas de resultados en vez de 8 (Tabla detallada se plegó
      dentro de Recomendaciones, ya consolidada con el reporte PDF).
    - Instrucciones de calibración más explícitas, citando el error
      real que cometimos validando contra MERL (zona angosta dejó el
      37.1% de las posiciones de mano fuera de cualquier zona) como
      ejemplo concreto a evitar.
    - Identidad visual propia (dashboard/style.py + dashboard/assets/theme.css):
      tipografía Manrope + IBM Plex Sans, paleta Surface/Ink/Hot/Cold que
      reutiliza el lenguaje de "zona caliente/fría" ya usado en heatmaps y
      tarjetas (rediseño completo -- ver docs/architecture.md, sección 22).

Sigue leyendo todo de los CSV/JSON generados por el pipeline -- este
dashboard NO procesa video directamente en su propio proceso (delega a
subprocess), y respeta privacidad por diseño: nunca se cargan imágenes
de personas aquí.

Uso:
    streamlit run dashboard\\app.py
"""

import json
import os
import re
import subprocess
import sys
import textwrap

import cv2
import pandas as pd
import streamlit as st
from streamlit_image_coordinates import streamlit_image_coordinates

sys.path.insert(0, os.path.dirname(__file__))
from layout_view import classify_zones, render_layout_plot, get_legend_html, COLOR_SIN_DATOS
from ai_insights import generate_all_recommendations, generate_executive_summary
from simulator import render_simulator_tab
from storytelling import render_storytelling_tab
from trends import render_trends_tab
from report_generator import generate_pdf_report
from ai_advisor import render_ai_advisor_section
from style import inject_custom_style, status_chip, render_step_status, COLD

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "pipeline"))
from heatmap import build_density_map, render_heatmap as render_heatmap_overlay


st.set_page_config(page_title="Space Management", layout="wide")


# =============================================================================
# ESTADO DE TIENDA (nuevo en v2) -- reemplaza el interruptor global de modo
# =============================================================================

def list_all_stores() -> list:
    """Nombres de tienda conocidos por CUALQUIER motivo: ya calibradas
    (config/zones_*.json) o ya procesadas (data/output/zone_summary_*.csv).
    A diferencia de la v1, esto incluye tiendas calibradas pero aún sin
    procesar, para que no 'desaparezcan' de la lista mientras se
    completa el flujo."""
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
    from history_db import get_available_dates

    has_zones = os.path.exists(f"config/zones_{store_name}.json")
    has_results = os.path.exists(f"data/output/zone_summary_{store_name}.csv")
    n_history = len(get_available_dates(store_name)) if has_results else 0

    return {"has_zones": has_zones, "has_results": has_results, "n_history": n_history}


def render_sidebar() -> str | None:
    """Panel de control persistente: elegir o crear una tienda, con su
    estado siempre visible. Devuelve el nombre de tienda elegido, o
    None si todavía no hay ninguna seleccionada."""
    st.sidebar.markdown("## Space Management")
    st.sidebar.caption("Flujo, permanencia e interacción -- sin identificar personas.")
    st.sidebar.divider()

    existing = list_all_stores()
    options = ["+ Nueva tienda / cámara"] + existing
    choice = st.sidebar.selectbox("Tienda", options, key="store_choice")

    if choice == "+ Nueva tienda / cámara":
        store_name = st.sidebar.text_input(
            "Nombre (sin espacios)", value="", placeholder="ej. tienda_centro",
        ).strip()
    else:
        store_name = choice

    if not store_name:
        return None

    state = get_store_state(store_name)
    st.sidebar.divider()
    st.sidebar.markdown(
        status_chip("Calibrada", state["has_zones"]) + "&nbsp;&nbsp;" +
        status_chip("Procesada", state["has_results"]),
        unsafe_allow_html=True,
    )
    if state["n_history"] > 0:
        st.sidebar.markdown(
            status_chip(f"Historial: {state['n_history']} fecha(s)", True),
            unsafe_allow_html=True,
        )

    return store_name


# =============================================================================
# CARGA DE DATOS
# =============================================================================

def load_store_data(store_name: str):
    """Carga zone_summary + zones_config (obligatorios) e
    interaction_summary (opcional, puede no existir todavía)."""
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


# =============================================================================
# COMPONENTES DE RESULTADOS
# =============================================================================

def render_semaphore_cards(summary_df: pd.DataFrame, classifications: dict):
    """Tarjetas simples tipo semáforo, una por zona, con lenguaje llano."""
    if summary_df.empty:
        st.info("Todavía no hay datos de zonas para mostrar.")
        return

    cols = st.columns(len(summary_df))
    for col, (_, row) in zip(cols, summary_df.iterrows()):
        label, color = classifications.get(row["zone_id"], ("Sin datos", COLOR_SIN_DATOS))
        with col:
            # Fondo TINTADO (12% del color de categoría mezclado con
            # blanco vía color-mix), no el color saturado completo --
            # borde izquierdo grueso con el color saturado real (mismo
            # lenguaje visual que las tarjetas de recomendación/tendencia
            # en dashboard/assets/theme.css). Con fondo tintado, el texto
            # vuelve a ser --color-ink normal -- ya no hace falta
            # ink-on-accent, porque ya no hay un fondo saturado de por
            # medio. Contraste ink-sobre-tinte recalculado y >=13.9:1 para
            # los 5 colores de categoría (ver tabla al final de theme.css).
            card_html = textwrap.dedent(f"""\
            <div style='background:color-mix(in srgb, {color} 12%, white);
                        border-left:5px solid {color}; border-radius:6px;
                        padding:16px; color:var(--color-ink);'>
            <div style='font-family:var(--font-body); font-size:14px;'>{row['zone_label']}</div>
            <div style='font-family:var(--font-heading); font-size:20px; font-weight:700;'>{label}</div>
            <div style='font-family:var(--font-body); font-size:13px; margin-top:8px;'>
            {row['total_visits']} visitas registradas<br>
            {row['stop_rate_pct']:.0f}% se detuvieron<br>
            {row['avg_dwell_seconds']:.1f}s de permanencia promedio
            </div>
            </div>
            """)
            st.markdown(card_html, unsafe_allow_html=True)


def render_interaction_tab(interaction_df):
    """Pestaña de interacción física con el estante. Incluye una nota
    de alcance honesta: no se distingue pickup de putback."""
    if interaction_df is None or interaction_df.empty:
        st.info(
            "Todavía no hay datos de interacción para esta tienda/video. "
            "Esto pasa si el video se procesó con la opción 'Omitir detección de manos' "
            "activada. Vuelve a procesarlo desde '+ Agregar nueva grabación / recalibrar' "
            "sin esa opción marcada para obtener estos datos."
        )
        return

    with st.container(border=True, key="panel_interaccion_zonas"):
        st.markdown("#### Interacción física por zona")
        st.caption(
            "Estas métricas cuentan cuántas veces la mano entró al estante y por cuánto tiempo. "
            "No distinguen si el resultado fue tomar o devolver un producto -- esa distinción "
            "requiere modelos de reconocimiento de acciones fuera del alcance de este MVP."
        )

        cols = st.columns(len(interaction_df))
        for col, (_, row) in zip(cols, interaction_df.iterrows()):
            with col:
                # Mismo tratamiento que las tarjetas de semáforo: fondo
                # tintado (12% COLD + blanco), borde izquierdo con el
                # color saturado, texto --color-ink normal -- ver
                # render_semaphore_cards() y la tabla de contraste en
                # dashboard/assets/theme.css.
                card_html = textwrap.dedent(f"""\
                <div style='background:color-mix(in srgb, {COLD} 12%, white);
                            border-left:5px solid {COLD}; border-radius:6px;
                            padding:16px; color:var(--color-ink);'>
                <div style='font-family:var(--font-body); font-size:14px;'>{row['zone_label']}</div>
                <div style='font-family:var(--font-heading); font-size:20px; font-weight:700;'>{row['total_interactions']} interacciones</div>
                <div style='font-family:var(--font-body); font-size:13px; margin-top:8px;'>
                {row['toques_breves']} toques breves<br>
                {row['interacciones_medias']} medias<br>
                {row['interacciones_prolongadas']} prolongadas<br>
                {row['avg_duration_seconds']:.1f}s de duración promedio
                </div>
                </div>
                """)
                st.markdown(card_html, unsafe_allow_html=True)


def compute_overview_kpis(summary_df: pd.DataFrame, interaction_df) -> dict:
    """KPIs generales para la fila superior del dashboard -- los 4 salen
    directo de zone_summary_df/interaction_summary_df ya calculados por el
    pipeline, ninguna cifra nueva ni estimada por el dashboard."""
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


def render_overview_kpis(kpis: dict):
    """Fila de 4 KPIs generales, cada uno en su propio panel -- antes de
    las tarjetas de semáforo (que dan detalle POR zona) y de las 6
    pestañas, siguiendo el patrón de un dashboard de monitoreo/analítica."""
    col1, col2, col3, col4 = st.columns(4)

    with col1, st.container(border=True, key="panel_kpi_zonas"):
        st.metric("Zonas monitoreadas", kpis["total_zones"])

    with col2, st.container(border=True, key="panel_kpi_visitas"):
        st.metric("Visitas totales", kpis["total_visits"])

    with col3, st.container(border=True, key="panel_kpi_interacciones"):
        if kpis["total_interactions"] is None:
            st.metric("Interacciones totales", "N/D")
            st.caption("No medido (video procesado sin detección de manos).")
        else:
            st.metric("Interacciones totales", kpis["total_interactions"])

    with col4, st.container(border=True, key="panel_kpi_top_zona"):
        st.metric("Zona con más tráfico", kpis["top_zone_label"])
        st.caption(f"{kpis['top_zone_visits']} visitas registradas")


def render_results_view(store_name: str):
    summary_df, zones_config, interaction_df = load_store_data(store_name)

    if summary_df is None:
        st.error(f"No se pudieron cargar los datos de '{store_name}'.")
        return

    classifications = classify_zones(summary_df)

    st.subheader("Panorama general")
    render_overview_kpis(compute_overview_kpis(summary_df, interaction_df))

    st.subheader("Resumen por zona")
    render_semaphore_cards(summary_df, classifications)
    st.markdown(get_legend_html(), unsafe_allow_html=True)
    st.divider()

    # 6 pestañas (antes 8 en la v1): Tabla detallada se plegó dentro de
    # Recomendaciones, junto al reporte PDF con el que ya comparte contexto.
    tab_historia, tab_mapas, tab_interaccion, tab_tendencias, tab_simulador, tab_recomendaciones = st.tabs(
        ["Historia", "Mapas y trayectorias", "Interacción con producto",
         "Tendencias", "Simulador", "Recomendaciones"]
    )

    with tab_historia:
        zone_labels = {z["id"]: z["label"] for z in zones_config["zones"]}
        render_storytelling_tab(store_name, zone_labels)

    with tab_mapas:
        video_ref = zones_config.get("video_reference", "")
        video_basename = os.path.splitext(os.path.basename(video_ref))[0] if video_ref else ""

        col_plano, col_heatmap = st.columns(2)

        with col_plano, st.container(border=True, key="panel_mapa_plano"):
            st.markdown("#### Plano de la tienda")
            st.pyplot(
                render_layout_plot(
                    zones_config["zones"], summary_df,
                    zones_config["frame_width"], zones_config["frame_height"]
                ),
                use_container_width=True,
            )

        with col_heatmap, st.container(border=True, key="panel_mapa_heatmap"):
            st.markdown("#### Mapas de calor y trayectorias")
            heatmap_variants = {
                "Flujo (tráfico corporal)": f"data/output/heatmap_{video_basename}.png",
                "Interacción (mano)": f"data/output/heatmap_manos_{video_basename}.png",
                "Trayectorias (espagueti)": f"data/output/spaghetti_{video_basename}.png",
            }
            available_variants = {label: path for label, path in heatmap_variants.items() if os.path.exists(path)}

            if not available_variants:
                st.info(
                    "Todavía no hay ninguna visualización generada para este video. "
                    "Procésalo desde '+ Agregar nueva grabación / recalibrar' para generarlas."
                )
            else:
                selected_label = st.radio(
                    "Tipo de visualización", list(available_variants.keys()), horizontal=True,
                )
                st.image(available_variants[selected_label], use_container_width=True)
                if selected_label == "Trayectorias (espagueti)":
                    st.caption(
                        "Todas las trayectorias se dibujan superpuestas en un único color "
                        "(verde=inicio, rojo=fin de cada recorrido) -- la intensidad de la línea "
                        "muestra qué tan común es ese recorrido, no de qué persona es: donde varios "
                        "recorridos coinciden, la línea se ve más sólida."
                    )
                missing = set(heatmap_variants.keys()) - set(available_variants.keys())
                if missing:
                    st.caption(
                        f"No disponibles todavía: {', '.join(missing)} "
                        "(se generan al procesar el video sin la opción 'Omitir detección de manos')."
                    )

        st.divider()
        with st.expander("Detalles técnicos (opcional): video de verificación de seguimiento"):
            st.caption(
                "Este video es una herramienta de control de calidad, pensada para quien "
                "construyó el sistema: sirve para confirmar que cada persona se sigue "
                "correctamente durante todo su recorrido (el mismo número/color debe "
                "acompañarla de principio a fin). No hace falta revisarlo para usar el resto "
                "del panel."
            )

            video_variants = {
                "Cuerpo": f"data/processed/tracked_preview_corregido_{video_basename}.webm",
                "Manos": f"data/processed/hands_preview_corregido_{video_basename}.webm",
            }
            available_videos = {label: path for label, path in video_variants.items() if os.path.exists(path)}

            if not available_videos:
                st.info(
                    "Todavía no hay un video de verificación para este video. "
                    "Se genera automáticamente al procesar."
                )
            else:
                selected_video_label = st.radio(
                    "Qué revisar", list(available_videos.keys()), horizontal=True, key="video_tracking_radio",
                )
                st.video(available_videos[selected_video_label])


    with tab_interaccion:
        render_interaction_tab(interaction_df)

    with tab_tendencias:
        render_trends_tab(store_name)

    with tab_simulador:
        render_simulator_tab(summary_df, interaction_df)

    with tab_recomendaciones:
        recommendations = generate_all_recommendations(summary_df)
        exec_summary = generate_executive_summary(summary_df, recommendations)

        st.info(exec_summary)

        for rec in recommendations:
            # key="rec_card_..." -- le da a estas tarjetas un tratamiento
            # visual propio (acento --color-hot) distinto de otros paneles,
            # vía dashboard/assets/theme.css: es contenido ACCIONABLE.
            with st.container(border=True, key=f"rec_card_{rec['zone_id']}"):
                st.markdown(f"#### {rec['zone_label']}")
                st.markdown(f"*Diagnóstico:* {rec['diagnostico']}")
                st.markdown(f"*Sugerencia:* {rec['sugerencia']}")

        st.divider()

        with st.container(border=True, key="panel_recomendaciones_reporte"):
            st.markdown("#### Reporte ejecutivo")
            st.caption("Genera un PDF de una página con estas métricas y recomendaciones, listo para compartir.")

            if st.button("Generar reporte PDF"):
                video_ref = zones_config.get("video_reference", "")
                video_basename = os.path.splitext(os.path.basename(video_ref))[0] if video_ref else ""
                heatmap_candidate = f"data/output/heatmap_{video_basename}.png" if video_basename else None

                report_path = f"data/output/reporte_{store_name}.pdf"
                with st.spinner("Generando PDF..."):
                    generate_pdf_report(
                        store_name, summary_df, interaction_df, report_path,
                        heatmap_path=heatmap_candidate, classifications=classifications,
                    )
                with open(report_path, "rb") as f:
                    st.download_button(
                        "Descargar reporte PDF", data=f.read(),
                        file_name=f"reporte_{store_name}.pdf", mime="application/pdf",
                    )

        with st.expander("Ver tabla completa de métricas"):
            display_df = summary_df.copy()
            display_df["clasificacion"] = display_df["zone_id"].map(
                lambda zid: classifications.get(zid, ("Sin datos", ""))[0]
            )
            st.dataframe(display_df, use_container_width=True)

        # Sección 100% opcional y aditiva: si el usuario no ingresa una
        # API key de Groq, esto no cambia nada de lo de arriba (ver
        # docs/architecture.md sección 20).
        render_ai_advisor_section(summary_df, interaction_df, recommendations, exec_summary)


# =============================================================================
# UTILIDADES DE VIDEO (sin cambios funcionales respecto a v1)
# =============================================================================

def format_seconds(seconds: float) -> str:
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}:{secs:02d}"


def get_video_duration(video_path: str) -> float:
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_count = cap.get(cv2.CAP_PROP_FRAME_COUNT)
    cap.release()
    if fps <= 0:
        return 0.0
    return frame_count / fps


def extract_frame(video_path: str, at_second: float):
    """Extrae un frame en RGB (para mostrar con st.image) en el segundo dado."""
    cap = cv2.VideoCapture(video_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    frame_idx = int(at_second * fps) if fps > 0 else 0
    cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        return None
    return cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)


def trim_video(input_path: str, output_path: str, start_sec: float, end_sec: float) -> int:
    """Recorta el video al rango [start_sec, end_sec] y lo guarda como un
    nuevo archivo. Devuelve el número de frames escritos."""
    cap = cv2.VideoCapture(input_path)
    fps = cap.get(cv2.CAP_PROP_FPS)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    start_frame = int(start_sec * fps)
    end_frame = int(end_sec * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, start_frame)

    writer = cv2.VideoWriter(output_path, cv2.VideoWriter_fourcc(*"mp4v"), fps, (width, height))

    frame_idx = start_frame
    n_written = 0
    while frame_idx < end_frame:
        ret, frame = cap.read()
        if not ret:
            break
        writer.write(frame)
        frame_idx += 1
        n_written += 1

    cap.release()
    writer.release()
    return n_written


def build_heat_preview(frame_rgb, tracks_csv_path: str, blur_radius: int = 35):
    """Genera una vista previa de calor sobre el frame de calibración,
    reutilizando la lógica de pipeline/heatmap.py."""
    df = pd.read_csv(tracks_csv_path)
    if df.empty:
        return frame_rgb

    height, width = frame_rgb.shape[:2]
    density = build_density_map(df, width, height, blur_radius)

    frame_bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)
    blended_bgr = render_heatmap_overlay(frame_bgr, density, opacity=0.5)
    return cv2.cvtColor(blended_bgr, cv2.COLOR_BGR2RGB)


def draw_calibration_overlay(frame_rgb, completed_zones: list, current_points: list):
    """Dibuja las zonas ya cerradas (verde) y el polígono en progreso (rojo)."""
    display = frame_rgb.copy()

    for zone in completed_zones:
        pts = zone["points"]
        for i in range(len(pts)):
            cv2.line(display, pts[i], pts[(i + 1) % len(pts)], (0, 255, 0), 2)
        cx = sum(p[0] for p in pts) // len(pts)
        cy = sum(p[1] for p in pts) // len(pts)
        cv2.putText(display, zone["label"], (cx - 20, cy),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

    for i, pt in enumerate(current_points):
        cv2.circle(display, pt, 5, (255, 0, 0), -1)
        if i > 0:
            cv2.line(display, current_points[i - 1], pt, (255, 0, 0), 2)

    return display


# =============================================================================
# CALIBRACIÓN (lógica sin cambios; instrucciones más explícitas en v2)
# =============================================================================

def render_zone_calibration_clasica(video_path: str, store_name: str, start_sec: float,
                                     tracks_csv_path: str = None) -> bool:
    """Calibración de zonas dentro del navegador: clic por clic.

    Si se provee tracks_csv_path (de un procesamiento previo del mismo
    video), se muestra un heatmap de referencia sobre el frame de
    calibración -- esto previene el problema real que documentamos: una
    zona calibrada sin ver antes dónde se concentra la actividad puede
    dejar fuera secciones enteras donde sí hay interacción, o -- el
    error concreto que cometimos validando este mismo proyecto --
    calibrar sobre el ESTANTE en vez del PISO donde la persona se para
    (ver docs/architecture.md, sección 12).

    Devuelve True si las zonas ya están guardadas y listas para procesar.
    """
    zones_path = f"config/zones_{store_name}.json"

    if os.path.exists(zones_path):
        st.success(f"Ya existen zonas calibradas para '{store_name}'.")
        if not st.checkbox("Recalibrar de todos modos"):
            return True

    points_key = f"calib_points_{store_name}"
    zones_key = f"calib_zones_{store_name}"
    counter_key = f"calib_click_counter_{store_name}"

    if points_key not in st.session_state:
        st.session_state[points_key] = []
    if zones_key not in st.session_state:
        st.session_state[zones_key] = []
    if counter_key not in st.session_state:
        st.session_state[counter_key] = 0

    frame_cache_key = f"calib_frame_{store_name}"
    frame_source_key = f"calib_frame_source_{store_name}"
    current_source = (video_path, start_sec, tracks_csv_path)

    if (frame_cache_key not in st.session_state or
            st.session_state.get(frame_source_key) != current_source):
        frame_rgb = extract_frame(video_path, start_sec)
        if frame_rgb is not None and tracks_csv_path and os.path.exists(tracks_csv_path):
            frame_rgb = build_heat_preview(frame_rgb, tracks_csv_path)
        st.session_state[frame_cache_key] = frame_rgb
        st.session_state[frame_source_key] = current_source
    else:
        frame_rgb = st.session_state[frame_cache_key]

    if frame_rgb is None:
        st.error("No se pudo leer un frame del video para calibrar.")
        return False

    # Instrucciones explícitas -- citando el error real que ya cometimos,
    # para que quien calibre no lo repita.
    if tracks_csv_path and os.path.exists(tracks_csv_path):
        st.warning(
            "**Dibuja sobre el PISO frente al estante (donde la persona se para), "
            "no sobre el estante mismo.** El fondo muestra un mapa de calor de referencia: "
            "asegúrate de que tu zona cubra bien las manchas de color, no los productos. "
            "Una zona mal ubicada puede dejar fuera interacción real que sí ocurrió "
            "-- en una prueba nuestra, casi 4 de cada 10 posiciones de mano quedaron "
            "fuera de cualquier zona por este motivo."
        )
    else:
        st.info(
            "Dibuja sobre el PISO frente al estante (donde la persona se para para "
            "interactuar), no sobre el estante mismo donde están los productos."
        )

    overlay = draw_calibration_overlay(
        frame_rgb, st.session_state[zones_key], st.session_state[points_key]
    )

    st.caption(
        "Haz clic sobre la imagen para ir marcando las esquinas de una góndola "
        "(mínimo 3 puntos). Cuando termines esa zona, presiona 'Cerrar zona'."
    )

    click = streamlit_image_coordinates(
        overlay, key=f"coords_{store_name}_{st.session_state[counter_key]}"
    )

    if click is not None:
        st.session_state[points_key].append((click["x"], click["y"]))
        st.session_state[counter_key] += 1
        st.rerun()

    n_next = len(st.session_state[zones_key]) + 1
    zone_name_input = st.text_input(
        "Nombre de esta góndola/zona (para la que estás marcando ahora)",
        value="",
        placeholder=f"Ej: Lácteos, Pasillo {n_next}, Snacks...",
        key=f"zone_name_{store_name}_{n_next}",
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("Deshacer último punto"):
            if st.session_state[points_key]:
                st.session_state[points_key].pop()
                st.rerun()
    with col2:
        if st.button("Cerrar zona actual"):
            if len(st.session_state[points_key]) < 3:
                st.warning("Necesitas al menos 3 puntos para cerrar una zona.")
            else:
                n = len(st.session_state[zones_key]) + 1
                final_name = zone_name_input.strip() if zone_name_input.strip() else f"zona_{n}"
                st.session_state[zones_key].append({
                    "label": final_name,
                    "points": st.session_state[points_key].copy(),
                })
                st.session_state[points_key] = []
                st.rerun()
    with col3:
        save_disabled = len(st.session_state[zones_key]) == 0
        if st.button("Guardar todas las zonas", disabled=save_disabled, type="primary"):
            height, width = frame_rgb.shape[:2]
            config = {
                "store_name": store_name,
                "video_reference": video_path,
                "frame_width": width,
                "frame_height": height,
                "zones": [
                    {
                        "id": z["label"],
                        "label": z["label"],
                        "polygon": [[int(x), int(y)] for x, y in z["points"]],
                        "dwell_threshold_seconds": 2.0,
                    }
                    for z in st.session_state[zones_key]
                ],
            }
            os.makedirs("config", exist_ok=True)
            with open(zones_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2, ensure_ascii=False)
            st.success(f"¡Zonas guardadas! ({len(st.session_state[zones_key])} zona(s))")
            st.session_state[zones_key] = []
            st.session_state[points_key] = []
            st.rerun()

    if st.session_state[zones_key]:
        st.caption(f"Zonas cerradas hasta ahora: {len(st.session_state[zones_key])}")

    return os.path.exists(zones_path)


def render_zone_calibration(video_path: str, store_name: str, start_sec: float,
                             tracks_csv_path: str = None) -> bool:
    """Punto de entrada de calibración: modo clásico (clic por clic),
    único soportado (el modo canvas fue evaluado y descartado -- ver
    docs/architecture.md, sección 10)."""
    return render_zone_calibration_clasica(video_path, store_name, start_sec, tracks_csv_path)


# =============================================================================
# ASISTENTE DE CONFIGURACIÓN (antes "render_processing_view", ahora
# parametrizado por una tienda ya elegida en la barra lateral -- se
# elimina el paso redundante de escribir el nombre de la tienda)
# =============================================================================

def render_setup_wizard(store_name: str):
    st.caption(
        f"Configurando **{store_name}**: sube tu grabación, marca el rango de interés, "
        "y deja que el sistema procese el resto."
    )

    os.makedirs("data/raw", exist_ok=True)

    st.markdown("#### 1. Sube tu video")
    uploaded_file = st.file_uploader("Archivo de video (MP4)", type=["mp4", "avi", "mov"])

    if uploaded_file is None:
        st.info("Sube un video para continuar.")
        return

    raw_video_path = os.path.join("data/raw", uploaded_file.name)
    with open(raw_video_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    duration = get_video_duration(raw_video_path)
    if duration <= 0:
        st.error("No se pudo leer la duración del video. ¿Es un archivo de video válido?")
        return

    st.video(raw_video_path)

    st.markdown("#### 2. (Opcional) Elige un rango a analizar")
    want_trim = st.checkbox(
        "Quiero recortar el video (por ejemplo, para evitar horas de tienda cerrada)",
        value=False,
    )

    video_to_use = raw_video_path
    calibration_reference_sec = 0.0

    if want_trim:
        st.caption("Mira el video de arriba y elige desde/hasta qué segundo analizar.")
        start_sec, end_sec = st.slider(
            "Rango a analizar (segundos)",
            min_value=0.0, max_value=float(duration),
            value=(0.0, float(duration)),
        )
        calibration_reference_sec = start_sec

        st.caption(
            f"Seleccionado: **{format_seconds(start_sec)}** a **{format_seconds(end_sec)}** "
            f"(duración: {format_seconds(end_sec - start_sec)})"
        )

        col_start, col_end = st.columns(2)
        with col_start:
            st.caption(f"Inicio ({format_seconds(start_sec)})")
            start_frame_img = extract_frame(raw_video_path, start_sec)
            if start_frame_img is not None:
                st.image(start_frame_img, use_container_width=True)
        with col_end:
            st.caption(f"Fin ({format_seconds(end_sec)})")
            end_frame_img = extract_frame(raw_video_path, max(end_sec - 0.2, 0))
            if end_frame_img is not None:
                st.image(end_frame_img, use_container_width=True)

        trimmed_name = f"{os.path.splitext(uploaded_file.name)[0]}_recortado.mp4"
        trimmed_path = os.path.join("data/raw", trimmed_name)

        if st.button("Recortar video con el rango elegido"):
            with st.spinner("Recortando video..."):
                n_frames = trim_video(raw_video_path, trimmed_path, start_sec, end_sec)
            st.success(f"Video recortado guardado ({n_frames} frames).")

        if os.path.exists(trimmed_path):
            video_to_use = trimmed_path
        else:
            st.info("Presiona 'Recortar video' para aplicar el rango elegido antes de continuar.")
    else:
        st.caption("Se analizará el video completo, sin recortar.")

    st.markdown("#### 3. Marca tus góndolas")

    video_basename = os.path.splitext(os.path.basename(video_to_use))[0]
    tracks_csv_path = f"data/processed/tracks_{video_basename}.csv"

    if os.path.exists(tracks_csv_path):
        st.success("Hay una vista previa de calor disponible (de un procesamiento anterior) para guiar la calibración.")
    else:
        st.info(
            "Todavía no hay una vista previa de calor para este video. Sin ella, es fácil "
            "calibrar una zona mal ubicada y perder interacción real (ver la advertencia "
            "que aparece más abajo una vez generada)."
        )
        if st.button("Generar vista previa de calor (recomendado, toma unos minutos)"):
            command = [sys.executable, "pipeline/detect_and_track.py", "--video", video_to_use]
            st.caption("Analizando el video para generar la vista previa...")
            log_expander = st.expander("Ver registro detallado")
            log_placeholder = log_expander.empty()
            log_lines = []
            # PYTHONUNBUFFERED=1: sin esto, en Windows Python a veces acumula
            # toda la salida en un búfer interno cuando detecta que no está
            # escribiendo a una terminal interactiva (sino a esta tubería),
            # y no suelta nada hasta que el proceso termina -- dando la
            # sensación de que "no pasa nada" mientras en realidad procesa
            # de fondo. Esto fuerza a que cada línea se envíe de inmediato.
            env = {**os.environ, "PYTHONUNBUFFERED": "1"}
            process = subprocess.Popen(
                command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, env=env,
            )
            for line in process.stdout:
                log_lines.append(line)
                log_placeholder.code("".join(log_lines[-20:]))
            process.wait()
            if process.returncode == 0:
                st.success("Vista previa generada. Continúa marcando tus góndolas abajo.")
                st.rerun()
            else:
                st.warning("No se pudo generar la vista previa -- puedes calibrar igual sin ella.")

    zones_exist = render_zone_calibration(
        video_to_use, store_name, calibration_reference_sec,
        tracks_csv_path=tracks_csv_path if os.path.exists(tracks_csv_path) else None,
    )

    st.markdown("#### 4. Procesar")
    if not zones_exist:
        st.info("Calibra las zonas (paso anterior) antes de procesar.")
        return

    skip_hands = st.checkbox(
        "Omitir detección de manos/interacción (procesa más rápido, pero no tendrás "
        "datos de interacción con el producto)",
        value=False,
    )

    record_history = st.checkbox(
        "Guardar este resultado en el historial de tendencias (para poder comparar "
        "esta fecha contra otra más adelante, en la pestaña 'Tendencias')",
        value=False,
    )
    run_date = None
    if record_history:
        run_date_value = st.date_input(
            "Fecha a asociar con esta grabación",
            help="No tiene que ser hoy -- usa la fecha en la que se grabó el video.",
        )
        run_date = run_date_value.strftime("%Y-%m-%d") if run_date_value else None

    with st.expander("Ajustes técnicos avanzados (no hace falta tocar esto en la mayoría de los casos)"):
        st.caption(
            "Estos valores afinan el algoritmo interno que sigue a cada persona en el video. "
            "Los valores por defecto ya funcionan bien para la mayoría de los videos -- solo "
            "considera cambiarlos si notas que el sistema pierde o confunde el seguimiento de "
            "una persona."
        )
        col1, col2 = st.columns(2)
        with col1:
            body_max_gap = st.number_input("Cuerpo: segundos máximos de \"desaparición\" tolerados", value=2.0)
            body_max_speed = st.number_input("Cuerpo: velocidad máxima plausible (px/s)", value=500.0)
        with col2:
            hand_max_gap = st.number_input("Mano: segundos máximos de \"desaparición\" tolerados", value=5.0)
            hand_max_speed = st.number_input("Mano: velocidad máxima plausible (px/s)", value=300.0)

    if st.button("Procesar video", type="primary"):
        command = [
            sys.executable, "pipeline/run_pipeline.py",
            "--video", video_to_use, "--store-name", store_name,
            "--body-max-gap", str(body_max_gap), "--body-max-speed", str(body_max_speed),
            "--hand-max-gap", str(hand_max_gap), "--hand-max-speed", str(hand_max_speed),
        ]
        if skip_hands:
            command.append("--skip-hands")
        if record_history:
            command.append("--record-history")
            if run_date:
                command.extend(["--run-date", run_date])

        total_steps_estimate = 6 if skip_hands else 11
        status_placeholder = st.empty()
        status_placeholder.markdown(
            render_step_status(0, total_steps_estimate, "Preparando..."), unsafe_allow_html=True,
        )
        log_expander = st.expander("Ver registro detallado")
        log_placeholder = log_expander.empty()
        log_lines = []

        # Detecta líneas como "[3/10] Descripción" (inicio de paso) para
        # actualizar el indicador visual -- el resto del texto crudo del
        # pipeline se sigue guardando abajo, en el expander plegado.
        step_start_pattern = re.compile(r"^\[(\d+)/(\d+)\]\s+(?!completado)(.+)$")

        # PYTHONUNBUFFERED=1: en Windows, Python a veces acumula toda la
        # salida en un búfer interno cuando detecta que no está escribiendo
        # a una terminal interactiva (sino a esta tubería), y no suelta
        # nada hasta que el proceso termina -- esto fuerza a que cada
        # línea se envíe de inmediato.
        env = {**os.environ, "PYTHONUNBUFFERED": "1"}
        process = subprocess.Popen(
            command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1, env=env,
        )
        for line in process.stdout:
            log_lines.append(line)
            log_placeholder.code("".join(log_lines[-40:]))

            step_match = step_start_pattern.match(line.strip())
            if step_match:
                step_num, total_steps, description = step_match.groups()
                status_placeholder.markdown(
                    render_step_status(int(step_num), int(total_steps), description),
                    unsafe_allow_html=True,
                )
        process.wait()

        if process.returncode == 0:
            status_placeholder.empty()
            st.success(f"¡Procesamiento completo! Los resultados de '{store_name}' ya están listos abajo.")
            st.rerun()
        else:
            status_placeholder.empty()
            st.error(
                "El procesamiento no se pudo completar. Abre 'Ver registro detallado' arriba "
                "para ver el detalle técnico del error -- puede ser útil compartirlo con quien "
                "te dio soporte con esta herramienta."
            )


# =============================================================================
# PUNTO DE ENTRADA
# =============================================================================

def main():
    inject_custom_style()

    store_name = render_sidebar()
    if not store_name:
        st.title("Space Management")
        st.info("Elige o crea una tienda en la barra lateral para comenzar.")
        return

    state = get_store_state(store_name)

    st.title(f"{store_name}")

    if state["has_results"]:
        with st.expander("+ Agregar nueva grabación / recalibrar"):
            render_setup_wizard(store_name)
        render_results_view(store_name)
    else:
        render_setup_wizard(store_name)


if __name__ == "__main__":
    main()