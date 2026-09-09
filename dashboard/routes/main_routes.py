"""
Rutas principales: selección de tienda y panel de resultados de solo
lectura (pestañas Historia, Mapas, Interacción, Tendencias, Simulador,
Recomendaciones).
"""

import os
import sys

from flask import Blueprint, render_template, request, redirect, url_for, flash

import store_service
import tienda_service
import layout_view
import ai_insights
import storytelling
import trends
import simulator
import data_management_service

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "..", "pipeline"))
import history_archive  # noqa: E402

main_bp = Blueprint("main", __name__)


def _sidebar_context(store_name, tienda_id=None):
    """Contexto común que layout.html necesita en TODAS las páginas.
    tienda_service.build_sidebar_context() resuelve sola a qué tienda
    pertenece store_name si no se le pasa tienda_id explícito -- así
    esta función sigue funcionando igual para cámaras que todavía no
    están registradas bajo ninguna tienda (ver docs/architecture.md
    sección 32)."""
    all_stores = store_service.list_all_stores()
    store_state = store_service.get_store_state(store_name) if store_name else None
    context = {
        "all_stores": all_stores,
        "current_store": store_name,
        "store_state": store_state,
    }
    context.update(tienda_service.build_sidebar_context(tienda_id=tienda_id, camara_id=store_name))
    return context


@main_bp.route("/")
def index():
    return redirect(url_for("main.tienda_home"))


@main_bp.route("/store")
def store_home():
    """Punto de entrada equivalente al main() de la versión Streamlit:
    decide entre "elige/crea una tienda", el asistente de configuración,
    o el panel de resultados, según el estado de la tienda elegida."""
    store_name = request.args.get("store", "").strip()
    if store_name == "__new__":
        store_name = ""

    if not store_name:
        return render_template("welcome.html", **_sidebar_context(None))

    state = store_service.get_store_state(store_name)

    if state["has_results"]:
        return redirect(url_for("main.results", store=store_name))
    return redirect(url_for("setup.wizard", store=store_name))


def _build_results_context(store_name, summary_df, zones_config, interaction_df,
                            heatmap_paths, video_paths, zone_events_df, interaction_events_df,
                            is_historical=False, historical_date=None):
    """Núcleo compartido por la vista EN VIVO (results()) y la vista
    HISTÓRICA de solo lectura (results_historico()) -- ver
    docs/architecture.md sección 34. Recibe los DataFrames y rutas de
    imagen/video YA RESUELTOS por el llamador (en vivo: data/output/*
    de siempre; histórico: la instantánea de data/history/<camara>/<fecha>/)
    y arma exactamente el mismo dict de contexto para results.html en
    ambos casos -- ninguna lógica de negocio se duplica ni se bifurca
    por is_historical, solo la PROCEDENCIA de los datos cambia."""
    classifications = layout_view.classify_zones(summary_df)
    kpis = store_service.compute_overview_kpis(summary_df, interaction_df)

    zone_cards = []
    for _, row in summary_df.iterrows():
        label, color = classifications.get(row["zone_id"], ("Sin datos", layout_view.COLOR_SIN_DATOS))
        zone_cards.append({
            "zone_label": row["zone_label"], "label": label, "color": color,
            "total_visits": int(row["total_visits"]), "stop_rate_pct": row["stop_rate_pct"],
            "avg_dwell_seconds": row["avg_dwell_seconds"],
        })

    interaction_cards = []
    if interaction_df is not None and not interaction_df.empty:
        for _, row in interaction_df.iterrows():
            interaction_cards.append({
                "zone_label": row["zone_label"], "total_interactions": int(row["total_interactions"]),
                "toques_breves": int(row["toques_breves"]), "interacciones_medias": int(row["interacciones_medias"]),
                "interacciones_prolongadas": int(row["interacciones_prolongadas"]),
                "avg_duration_seconds": row["avg_duration_seconds"],
            })

    available_heatmaps = {label: path for label, path in heatmap_paths.items() if os.path.exists(path)}
    missing_heatmaps = [label for label in heatmap_paths if label not in available_heatmaps]
    available_videos = {label: path for label, path in video_paths.items() if os.path.exists(path)}

    zone_labels = {z["id"]: z["label"] for z in zones_config["zones"]}
    story = storytelling.build_story(zone_events_df, interaction_events_df, zone_labels)

    recommendations = ai_insights.generate_all_recommendations(summary_df)
    exec_summary = ai_insights.generate_executive_summary(summary_df, recommendations)

    trends_data = trends.get_trends_data(store_name)
    history_series = trends.get_history_series(store_name)
    history_series_semana = trends.get_history_series_agrupada(store_name, "semana")
    history_series_mes = trends.get_history_series_agrupada(store_name, "mes")
    archived_dates = history_archive.list_archived_dates(store_name)

    display_rows = []
    for _, row in summary_df.iterrows():
        label, _ = classifications.get(row["zone_id"], ("Sin datos", ""))
        display_rows.append({
            "zone_label": row["zone_label"], "clasificacion": label,
            "total_visits": int(row["total_visits"]), "stop_rate_pct": row["stop_rate_pct"],
            "avg_dwell_seconds": row["avg_dwell_seconds"],
        })

    has_two_or_more_zones = len(summary_df) >= 2
    has_interaction_data = interaction_df is not None and not interaction_df.empty
    zone_options = (
        dict(zip(summary_df["zone_label"], summary_df["zone_id"])) if has_two_or_more_zones else {}
    )

    return {
        "kpis": kpis,
        "zone_cards": zone_cards,
        "interaction_cards": interaction_cards,
        "available_heatmaps": available_heatmaps,
        "missing_heatmaps": missing_heatmaps,
        "available_videos": available_videos,
        "story": story,
        "recommendations": recommendations,
        "exec_summary": exec_summary,
        "trends_data": trends_data,
        "history_series": history_series,
        "history_series_semana": history_series_semana,
        "history_series_mes": history_series_mes,
        "archived_dates": archived_dates,
        "display_rows": display_rows,
        "has_two_or_more_zones": has_two_or_more_zones,
        "has_interaction_data": has_interaction_data,
        "zone_options": zone_options,
        "is_historical": is_historical,
        "historical_date": historical_date,
    }


@main_bp.route("/store/results")
def results():
    store_name = request.args.get("store", "").strip()
    if not store_name:
        return redirect(url_for("main.store_home"))

    summary_df, zones_config, interaction_df = store_service.load_store_data(store_name)
    if summary_df is None:
        return redirect(url_for("setup.wizard", store=store_name))

    video_ref = zones_config.get("video_reference", "")
    video_basename = os.path.splitext(os.path.basename(video_ref))[0] if video_ref else ""

    heatmap_paths = {
        "Flujo (tráfico corporal)": f"data/output/heatmap_{video_basename}.png",
        "Interacción (mano)": f"data/output/heatmap_manos_{video_basename}.png",
        "Trayectorias (espagueti)": f"data/output/spaghetti_{video_basename}.png",
    }
    video_paths = {
        "Cuerpo": f"data/processed/tracked_preview_corregido_{video_basename}.webm",
        "Manos": f"data/processed/hands_preview_corregido_{video_basename}.webm",
    }
    zone_events_df, interaction_events_df = storytelling.load_events(store_name)

    context = _sidebar_context(store_name)
    context.update(_build_results_context(
        store_name, summary_df, zones_config, interaction_df,
        heatmap_paths, video_paths, zone_events_df, interaction_events_df,
    ))
    context["video_basename"] = video_basename
    return render_template("results.html", **context)


@main_bp.route("/store/datos")
def datos_camara():
    """Página de gestión de datos (Parte 2, ver docs/architecture.md
    sección 35): espacio en disco + eliminación, para una cámara
    específica."""
    store_name = request.args.get("store", "").strip()
    if not store_name or store_name not in store_service.list_all_stores():
        return redirect(url_for("main.store_home"))

    context = _sidebar_context(store_name)
    context.update({
        "raw_videos": data_management_service.get_raw_video_files(store_name),
        "processed_info": data_management_service.get_processed_output_info(store_name),
        "archived_dates": data_management_service.get_archived_dates_info(store_name),
    })
    return render_template("data_management.html", **context)


@main_bp.route("/store/results/historico")
def results_historico():
    """Vista de solo lectura de una fecha ARCHIVADA (ver Parte 1,
    docs/architecture.md sección 34) -- reusa el mismo template y la
    misma lógica de _build_results_context() que la vista en vivo,
    alimentada desde data/history/<camara>/<fecha>/ en vez de
    data/output/. No hay video de verificación disponible (deliberadamente
    no se archiva, ver pipeline/history_archive.py)."""
    store_name = request.args.get("store", "").strip()
    run_date = request.args.get("fecha", "").strip()
    if not store_name or not run_date:
        return redirect(url_for("main.results", store=store_name))

    summary_df, zones_config, interaction_df = store_service.load_archived_store_data(store_name, run_date)
    if summary_df is None:
        flash(f"No se encontró una instantánea archivada para '{store_name}' en la fecha '{run_date}'.")
        return redirect(url_for("main.results", store=store_name))

    archive_dir = history_archive.get_archive_dir(store_name, run_date)
    heatmap_paths = {
        "Flujo (tráfico corporal)": os.path.join(archive_dir, "heatmap_flujo.png"),
        "Interacción (mano)": os.path.join(archive_dir, "heatmap_manos.png"),
        "Trayectorias (espagueti)": os.path.join(archive_dir, "spaghetti.png"),
    }
    zone_events_df, interaction_events_df = storytelling.load_events_from_paths(
        os.path.join(archive_dir, "zone_events.csv"), os.path.join(archive_dir, "interaction_events.csv"),
    )

    context = _sidebar_context(store_name)
    context.update(_build_results_context(
        store_name, summary_df, zones_config, interaction_df,
        heatmap_paths, {}, zone_events_df, interaction_events_df,
        is_historical=True, historical_date=run_date,
    ))
    return render_template("results.html", **context)


# =============================================================================
# TIENDA -> CÁMARAS (ver docs/architecture.md sección 32). Estas rutas
# son la entrada PRINCIPAL nueva del sidebar; /store y /store/results de
# arriba siguen existiendo sin cambios (una cámara vieja sin tienda
# asignada, o un enlace directo, los sigue usando tal cual).
# =============================================================================

@main_bp.route("/tienda")
def tienda_home():
    """Punto de entrada de tienda: elegir/crear una tienda, y luego
    decidir la vista según cuántas cámaras tiene (0 -> estado vacío,
    1 -> directo a esa cámara sin selector de modo, 2+ -> combinada)."""
    tienda_id = request.args.get("tienda", "").strip()
    if tienda_id == "__new__":
        tienda_id = ""

    if not tienda_id:
        return render_template("tienda_welcome.html", **_sidebar_context(None))

    tienda = tienda_service.get_tienda(tienda_id)
    if tienda is None:
        # El usuario escribió un nombre nuevo en el form de "crear
        # tienda" -- se crea acá mismo y se redirige a su propio id.
        try:
            nuevo_id = tienda_service.create_tienda(tienda_id)
        except ValueError as e:
            flash(str(e))
            return redirect(url_for("main.tienda_home"))
        return redirect(url_for("main.tienda_home", tienda=nuevo_id))

    camaras = tienda_service.get_camaras_de_tienda(tienda_id)
    if not camaras:
        return render_template("tienda_empty.html", **_sidebar_context(None, tienda_id=tienda_id))
    if len(camaras) == 1:
        # Con una sola cámara, "combinada" y "por cámara" muestran lo
        # mismo -- se salta el selector de modo para no obligar a elegir
        # entre dos vistas idénticas (ver resumen final de la tarea).
        return redirect(url_for("main.results", store=camaras[0]))
    return redirect(url_for("main.tienda_combinada", tienda_id=tienda_id))


@main_bp.route("/tienda/<tienda_id>/combinada")
def tienda_combinada(tienda_id):
    tienda = tienda_service.get_tienda(tienda_id)
    if tienda is None:
        return redirect(url_for("main.tienda_home"))

    camaras = tienda_service.get_camaras_de_tienda(tienda_id)
    if not camaras:
        return render_template("tienda_empty.html", **_sidebar_context(None, tienda_id=tienda_id))

    zone_summary_combinado, referencias = tienda_service.get_zone_summary_combinado(tienda_id)
    interaction_combinado = tienda_service.get_interaction_summary_combinado(tienda_id)
    kpis = tienda_service.compute_tienda_kpis(tienda_id, zone_summary_combinado, interaction_combinado)

    zone_rows = []
    if not zone_summary_combinado.empty:
        classifications_por_camara = {}
        for camara_id in camaras:
            summary_df, _, _ = store_service.load_store_data(camara_id)
            if summary_df is not None:
                classifications_por_camara[camara_id] = layout_view.classify_zones(summary_df)

        for _, row in zone_summary_combinado.iterrows():
            classif = classifications_por_camara.get(row["camara_origen"], {})
            label, color = classif.get(row["zone_id"], ("Sin datos", layout_view.COLOR_SIN_DATOS))
            zone_rows.append({
                "zone_label": row["zone_label"], "camara_origen": row["camara_origen"],
                "clasificacion": label, "color": color,
                "total_visits": int(row["total_visits"]), "stop_rate_pct": row["stop_rate_pct"],
                "avg_dwell_seconds": row["avg_dwell_seconds"],
                "fecha_referencia": row["fecha_referencia"], "duracion_referencia": row["duracion_referencia"],
            })

    # Las cámaras distintas casi siempre tienen fecha/duración de
    # referencia distinta -- la advertencia de comparabilidad es
    # obligatoria en cuanto hay 2+ cámaras con resultados (ver
    # docs/architecture.md sección 32), no solo si los valores difieren
    # literalmente (una coincidencia de fecha no la vuelve una
    # comparación justa por sí sola).
    mostrar_advertencia = kpis["camaras_con_resultados"] >= 2

    has_two_or_more_zone_options = len(zone_summary_combinado) >= 2
    zone_options_multi = (
        simulator.get_zone_options_multi(zone_summary_combinado) if has_two_or_more_zone_options else {}
    )
    has_interaction_data = interaction_combinado is not None and not interaction_combinado.empty

    context = _sidebar_context(None, tienda_id=tienda_id)
    context.update({
        "kpis": kpis,
        "zone_rows": zone_rows,
        "referencias": referencias,
        "mostrar_advertencia_comparabilidad": mostrar_advertencia,
        "has_two_or_more_zone_options": has_two_or_more_zone_options,
        "zone_options_multi": zone_options_multi,
        "has_interaction_data": has_interaction_data,
    })
    return render_template("tienda_combinada.html", **context)


@main_bp.route("/tienda/<tienda_id>/nueva-camara", methods=["GET", "POST"])
def tienda_nueva_camara(tienda_id):
    """Formulario para agregar una cámara a una tienda -- una NUEVA (vía
    el asistente de configuración ya existente, sin cambios) o una que
    YA EXISTE en el sistema pero todavía no está asignada a ninguna
    tienda."""
    tienda = tienda_service.get_tienda(tienda_id)
    if tienda is None:
        return redirect(url_for("main.tienda_home"))

    if request.method == "POST":
        accion = request.form.get("accion")

        if accion == "nueva":
            camara_id = request.form.get("camara_id", "").strip()
            if not camara_id:
                flash("Ingresa un identificador para la nueva cámara.")
                return redirect(url_for("main.tienda_nueva_camara", tienda_id=tienda_id))
            if camara_id in store_service.list_all_stores():
                flash(f"Ya existe una cámara con el identificador '{camara_id}' -- elige otro, o vincúlala como cámara existente si es la misma.")
                return redirect(url_for("main.tienda_nueva_camara", tienda_id=tienda_id))
            try:
                tienda_service.add_camara_a_tienda(tienda_id, camara_id)
            except ValueError as e:
                flash(str(e))
                return redirect(url_for("main.tienda_nueva_camara", tienda_id=tienda_id))
            return redirect(url_for("setup.wizard", store=camara_id))

        if accion == "vincular":
            camara_id = request.form.get("camara_existente", "").strip()
            if not camara_id:
                flash("Elige una cámara existente para vincular.")
                return redirect(url_for("main.tienda_nueva_camara", tienda_id=tienda_id))
            try:
                tienda_service.add_camara_a_tienda(tienda_id, camara_id)
            except ValueError as e:
                flash(str(e))
                return redirect(url_for("main.tienda_nueva_camara", tienda_id=tienda_id))
            return redirect(url_for("main.results", store=camara_id))

        return redirect(url_for("main.tienda_nueva_camara", tienda_id=tienda_id))

    context = _sidebar_context(None, tienda_id=tienda_id)
    context.update({"camaras_sin_asignar": tienda_service.get_camaras_sin_asignar()})
    return render_template("tienda_nueva_camara.html", **context)
