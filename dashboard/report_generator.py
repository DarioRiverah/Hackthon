"""
Reporte ejecutivo ampliado en PDF.

Reutiliza las métricas y textos YA CALCULADOS por el resto del proyecto
(ai_insights.py para el diagnóstico/recomendaciones por zona,
storytelling.py para el resumen narrado agregado, trends.py para la
comparación de tendencias) para generar un documento de VARIAS páginas
en lenguaje de negocio, listo para imprimir o compartir -- sin ningún
modelo de IA de pago involucrado.

Esta versión reemplaza al reporte original de una sola página (ver
docs/architecture.md): el reporte original se construyó al inicio del
proyecto y nunca se actualizó con todo lo que se agregó después
(Historia narrada, heatmap de interacción, diagrama de espagueti,
Tendencias con historial real, estructura de tiendas/cámaras). Esta
tarea es de ENSAMBLAJE Y PRESENTACIÓN -- ninguna función de negocio
(ai_insights, storytelling, trends) cambió, solo cómo se combinan y
presentan sus resultados acá.

Cada sección nueva es OPCIONAL y se omite con elegancia si no aplica
para la cámara (ej. sin historial de 2+ fechas, sin datos de manos) --
nunca se muestra una sección vacía ni un placeholder.

Uso (como módulo, desde el dashboard):
    from report_generator import generate_pdf_report
    generate_pdf_report("mi_tienda", zone_summary_df, interaction_summary_df, "reporte.pdf")
"""

import os
from datetime import datetime

from PIL import Image as PILImage
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak,
)

from ai_insights import generate_all_recommendations, generate_executive_summary
from colors import INK, COLD, SURFACE, INFO

# =============================================================================
# Notas de alcance -- texto EXACTO ya validado y visible hoy en el
# dashboard (templates/results.html, static/js/help-content.js), NO
# redactado de nuevo para este reporte. Antes vivían dispersas (una
# nota corta bajo la tabla de interacción, otra bajo Historia, otra en
# el widget de ayuda) -- acá quedan consolidadas en un solo lugar
# visible (el pie del reporte), como pide la tarea.
#
# No se incluye una afirmación explícita de "100% local" porque esa
# frase específica no existe hoy como texto de cara al usuario en
# ningún lugar del dashboard (sí en docs/architecture.md, que es
# documentación interna de desarrollo, no contenido para el dueño de
# la tienda) -- reutilizar SOLO lo ya validado significó no inventar
# esa oración nueva. Ver resumen de la tarea.
# =============================================================================
SCOPE_NOTE_IDENTIFICACION = (
    "Flujo, permanencia e interacción -- sin identificar personas. El sistema no usa "
    "reconocimiento facial ni guarda imágenes de las personas que aparecen en el video, y "
    "ni siquiera distingue de forma confiable a un cliente específico de otro cuando hay "
    "varias personas en la misma escena. Por eso las métricas se muestran siempre agregadas "
    "(por zona, por fecha), nunca por “cliente individual”."
)
SCOPE_NOTE_EVENTOS = (
    "Los eventos de este reporte (detenciones, pasos, interacciones) NO se desglosan por "
    "cliente individual. La identificación de personas usa heurísticas geométricas (posición, "
    "velocidad, dirección), confiables para una persona sola en cuadro, pero no validadas para "
    "escenas con varias personas simultáneas -- un cruce de trayectorias podría fusionar o "
    "dividir identidades por error. Por eso se narra en términos de eventos observados, no de "
    "“qué hizo cada cliente”."
)
SCOPE_NOTE_INTERACCION = (
    "Las métricas de interacción cuentan cuántas veces la mano entró al estante y por cuánto "
    "tiempo. No distinguen si el resultado fue tomar o devolver un producto -- esa distinción "
    "requiere modelos de reconocimiento de acciones fuera del alcance de este sistema."
)


def _build_styles():
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle", parent=styles["Title"], fontSize=20, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="ReportSubtitle", parent=styles["Normal"], fontSize=11,
        textColor=colors.grey, spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="SectionHeading", parent=styles["Heading2"], spaceBefore=14, spaceAfter=6,
    ))
    styles.add(ParagraphStyle(
        name="ImageCaption", parent=styles["Normal"], fontSize=9,
        textColor=colors.grey, spaceBefore=4, spaceAfter=14, alignment=1,  # centrado
    ))
    styles.add(ParagraphStyle(
        name="ScopeNote", parent=styles["Normal"], fontSize=8,
        textColor=colors.grey, spaceAfter=8, leading=11,
    ))
    return styles


def _build_zone_table(zone_summary_df, classifications: dict):
    header = ["Zona", "Clasificación", "Visitas", "% se detiene", "Permanencia prom."]
    rows = [header]

    for _, row in zone_summary_df.iterrows():
        label, _ = classifications.get(row["zone_id"], ("Sin datos", ""))
        rows.append([
            row["zone_label"],
            label,
            f"{row['total_visits']:.0f}",
            f"{row['stop_rate_pct']:.0f}%",
            f"{row['avg_dwell_seconds']:.1f}s",
        ])

    table = Table(rows, hAlign="LEFT", colWidths=[3.2 * cm, 3.5 * cm, 2.2 * cm, 2.8 * cm, 3.2 * cm])
    table.setStyle(TableStyle([
        # INK (Tinta): la tabla de métricas generales usa el color
        # "estructural" del sistema de diseño, no un color de acento --
        # es la tabla principal, no está atada a un concepto caliente/frío.
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(INK)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(SURFACE)]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _build_interaction_table(interaction_summary_df):
    header = ["Zona", "Interacciones", "Breves", "Medias", "Prolongadas", "Duración prom."]
    rows = [header]

    for _, row in interaction_summary_df.iterrows():
        rows.append([
            row["zone_label"],
            f"{row['total_interactions']:.0f}",
            f"{row['toques_breves']:.0f}",
            f"{row['interacciones_medias']:.0f}",
            f"{row['interacciones_prolongadas']:.0f}",
            f"{row['avg_duration_seconds']:.1f}s",
        ])

    table = Table(rows, hAlign="LEFT",
                  colWidths=[3.0 * cm, 2.5 * cm, 2.0 * cm, 2.0 * cm, 2.5 * cm, 2.5 * cm])
    table.setStyle(TableStyle([
        # COLD: mismo color que ya usan las tarjetas de interacción en el
        # dashboard -- la tabla de interacción del PDF usa el mismo
        # acento que su equivalente en pantalla. Texto en negro
        # (colors.black), no blanco: blanco sobre COLD da 3.04:1 de
        # contraste (falla AA); negro da 6.91:1.
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(COLD)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(SURFACE)]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _build_trend_table(trends_data: dict):
    """Tabla de comparación de 2 fechas (las 2 más recientes por
    defecto), reutilizando EXACTAMENTE la misma estructura de
    "cards"/"metrics" que ya arma trends.get_trends_data() para la
    pestaña Tendencias del dashboard -- no se recalcula nada acá, solo
    se tabula. Un gráfico de líneas (como el de Chart.js en pantalla)
    no se incrusta directamente en un PDF; se evaluó generar una imagen
    estática equivalente con matplotlib, pero se optó por esta tabla
    porque reutiliza tal cual una estructura de datos YA validada y
    mostrada en el dashboard (la propia sección "Comparación detallada"
    de Tendencias), en vez de construir un renderizador nuevo solo para
    este caso -- ver el resumen final de la tarea."""
    date_a, date_b = trends_data["date_a"], trends_data["date_b"]
    header = ["Zona", "Métrica", date_a, date_b, "Cambio"]
    rows = [header]
    for card in trends_data["cards"]:
        for i, m in enumerate(card["metrics"]):
            rows.append([
                card["zone_label"] if i == 0 else "",
                m["label"], m["value_a"], m["value_b"], m["delta_str"],
            ])

    table = Table(rows, hAlign="LEFT", colWidths=[3.2 * cm, 4.0 * cm, 2.3 * cm, 2.3 * cm, 2.3 * cm])
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(INFO)),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor(SURFACE)]),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _fitted_image(path: str, max_width: float, max_height: float):
    """Escala una imagen al PDF preservando su proporción REAL (leída
    con Pillow) -- la versión anterior asumía 16:9 a ciegas, lo que
    distorsiona cualquier heatmap/diagrama que no tenga exactamente esa
    proporción (la mayoría no la tiene: siguen la relación de aspecto
    del video/plano original)."""
    with PILImage.open(path) as im:
        iw, ih = im.size
    ratio = iw / ih if ih else 1
    width, height = max_width, max_width / ratio
    if height > max_height:
        height = max_height
        width = height * ratio
    return Image(path, width=width, height=height)


def generate_pdf_report(store_name: str, zone_summary_df, interaction_summary_df,
                         output_path: str, heatmap_paths: dict = None,
                         classifications: dict = None, narrative: str = None,
                         tienda_context: dict = None, trends_data: dict = None,
                         fecha_referencia: str = None) -> str:
    """Genera el PDF y devuelve la ruta del archivo creado.

    Parámetros nuevos respecto a la versión anterior (todos opcionales,
    cada sección que alimentan se omite con elegancia si no se pasan):
      heatmap_paths: dict {etiqueta: ruta}, YA filtrado a los que
          existen en disco -- ej. {"Flujo (tráfico corporal)": "...",
          "Interacción (mano)": "...", "Trayectorias (espagueti)": "..."}
          (antes: heatmap_path, un solo string).
      narrative: el resumen narrado agregado de
          storytelling.generate_aggregate_narrative(), o None si esta
          cámara no tiene eventos de zona registrados.
      tienda_context: {"tienda_label": str, "n_camaras": int} si esta
          cámara pertenece a una tienda con más de una cámara, si no None.
      trends_data: la salida de trends.get_trends_data(store_name), o
          None/sin "has_enough_dates" si esta cámara tiene menos de 2
          fechas archivadas.
      fecha_referencia: fecha de referencia de la grabación analizada
          (aproximada -- ver tienda_service.get_camara_referencia()),
          o None si no se pudo determinar.
    """
    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    styles = _build_styles()
    story = []

    if classifications is None:
        classifications = {}
    if heatmap_paths is None:
        heatmap_paths = {}

    # =========================================================================
    # 1. Portada / encabezado
    # =========================================================================
    story.append(Paragraph("Reporte Ejecutivo de Space Management", styles["ReportTitle"]))

    subtitle = f"Cámara: <b>{store_name}</b>"
    if tienda_context:
        subtitle += (f" &nbsp;&nbsp;|&nbsp;&nbsp; Tienda: <b>{tienda_context['tienda_label']}</b> "
                     f"(1 de {tienda_context['n_camaras']} cámaras)")
    story.append(Paragraph(subtitle, styles["ReportSubtitle"]))

    fecha_generacion = datetime.now().strftime("%d/%m/%Y %H:%M")
    story.append(Paragraph(f"Generado: {fecha_generacion}", styles["ReportSubtitle"]))
    if fecha_referencia:
        story.append(Paragraph(f"Datos analizados: grabación de referencia del {fecha_referencia}",
                                styles["ReportSubtitle"]))
    story.append(Spacer(1, 8))

    # =========================================================================
    # 2. Resumen ejecutivo -- KPIs generales + resumen narrado agregado
    #    (storytelling) + el párrafo del motor de reglas (ai_insights),
    #    exactamente igual que antes.
    # =========================================================================
    recommendations = generate_all_recommendations(zone_summary_df)
    exec_summary = generate_executive_summary(zone_summary_df, recommendations)

    story.append(Paragraph("Resumen ejecutivo", styles["SectionHeading"]))

    total_visits = int(zone_summary_df["total_visits"].sum()) if not zone_summary_df.empty else 0
    total_interactions = (
        int(interaction_summary_df["total_interactions"].sum())
        if interaction_summary_df is not None and not interaction_summary_df.empty else None
    )
    kpi_line = f"<b>{len(zone_summary_df)}</b> zona(s) monitoreada(s) &nbsp;&nbsp;|&nbsp;&nbsp; <b>{total_visits}</b> visita(s) totales"
    if total_interactions is not None:
        kpi_line += f" &nbsp;&nbsp;|&nbsp;&nbsp; <b>{total_interactions}</b> interacción(es) física(s) con el estante"
    story.append(Paragraph(kpi_line, styles["Normal"]))
    story.append(Spacer(1, 6))

    story.append(Paragraph(exec_summary, styles["Normal"]))
    if narrative:
        story.append(Spacer(1, 6))
        story.append(Paragraph(narrative, styles["Normal"]))

    # =========================================================================
    # 3. Resumen por zona
    # =========================================================================
    story.append(Paragraph("Resumen por zona", styles["SectionHeading"]))
    story.append(_build_zone_table(zone_summary_df, classifications))

    # =========================================================================
    # 4. Mapas de calor y trayectorias (todos los que existan para esta
    #    cámara -- flujo, interacción de mano, espagueti). Cada imagen
    #    con su propia etiqueta como leyenda (la MISMA que ya usa el
    #    selector de la pestaña Mapas del dashboard, no una nueva).
    # =========================================================================
    available_heatmaps = {label: path for label, path in heatmap_paths.items() if os.path.exists(path)}
    if available_heatmaps:
        story.append(PageBreak())
        story.append(Paragraph("Mapas de calor y trayectorias", styles["SectionHeading"]))
        for label, path in available_heatmaps.items():
            story.append(_fitted_image(path, max_width=16 * cm, max_height=16 * cm))
            story.append(Paragraph(label, styles["ImageCaption"]))

    # =========================================================================
    # 5. Interacción con producto
    # =========================================================================
    if interaction_summary_df is not None and not interaction_summary_df.empty:
        story.append(Paragraph("Interacción con producto", styles["SectionHeading"]))
        story.append(_build_interaction_table(interaction_summary_df))

    # =========================================================================
    # 6. Tendencia -- solo si hay 2+ fechas archivadas para esta cámara.
    #    Se omite la sección entera (sin placeholder) si no aplica.
    # =========================================================================
    if trends_data and trends_data.get("has_enough_dates") and not trends_data.get("same_dates") and trends_data.get("cards"):
        story.append(Paragraph("Tendencia (comparación entre 2 fechas guardadas)", styles["SectionHeading"]))
        story.append(_build_trend_table(trends_data))

    # =========================================================================
    # 7. Diagnóstico y recomendaciones -- mismo contenido de siempre,
    #    solo reubicado dentro del documento ampliado.
    # =========================================================================
    story.append(PageBreak())
    story.append(Paragraph("Diagnóstico y recomendaciones", styles["SectionHeading"]))
    for rec in recommendations:
        story.append(Paragraph(f"<b>{rec['zone_label']}</b>", styles["Normal"]))
        story.append(Paragraph(f"Diagnóstico: {rec['diagnostico']}", styles["Normal"]))
        story.append(Paragraph(f"Sugerencia: {rec['sugerencia']}", styles["Normal"]))
        story.append(Spacer(1, 8))

    # =========================================================================
    # 8. Notas de alcance -- consolidadas en un solo lugar visible, con
    #    el texto EXACTO ya validado en el dashboard (ver constantes al
    #    principio de este archivo), no redactado de nuevo.
    # =========================================================================
    story.append(Spacer(1, 10))
    story.append(Paragraph("Notas de alcance", styles["SectionHeading"]))
    story.append(Paragraph(SCOPE_NOTE_IDENTIFICACION, styles["ScopeNote"]))
    story.append(Paragraph(SCOPE_NOTE_EVENTOS, styles["ScopeNote"]))
    if interaction_summary_df is not None and not interaction_summary_df.empty:
        story.append(Paragraph(SCOPE_NOTE_INTERACCION, styles["ScopeNote"]))

    doc = SimpleDocTemplate(
        output_path, pagesize=letter,
        topMargin=1.5 * cm, bottomMargin=1.5 * cm, leftMargin=1.8 * cm, rightMargin=1.8 * cm,
    )
    doc.build(story)

    return output_path
