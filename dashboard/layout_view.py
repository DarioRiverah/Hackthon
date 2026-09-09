"""
Clasificación de zonas y renderizado del plano (layout) personalizado.

Convierte las métricas crudas de zone_summary (visitas, dwell, tasa de
detención) en una clasificación de negocio en lenguaje llano, usando la
lógica de cuadrantes tráfico x permanencia que se definió para el reto:

    Alto tráfico + Alto dwell   -> "Zona Caliente"      (--color-hot)
    Alto tráfico + Bajo dwell   -> "Zona de Paso"        (--color-zone-paso)
    Bajo tráfico + Alto dwell   -> "Interés de Nicho"    (--color-zone-nicho)
    Bajo tráfico + Bajo dwell   -> "Zona Fría"           (--color-cold)

Cuando solo hay UNA zona en la tienda, no hay con qué comparar tráfico
relativo, así que se usa una clasificación simplificada basada en la
tasa de detención (stop_rate_pct) únicamente.

Los colores vienen de dashboard/colors.py (misma paleta que
dashboard/static/css/main.css) -- ver ese archivo CSS para la
verificación de contraste WCAG completa.
"""

import matplotlib
matplotlib.use("Agg")  # backend sin interfaz gráfica, seguro para cualquier entorno
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon as MplPolygon
import pandas as pd

from matplotlib.patches import Rectangle

from colors import HOT, COLD, PANEL, SURFACE, INK, INK_MUTED

COLOR_CALIENTE = HOT
COLOR_FRIA = COLD

# "Paso" y "Nicho" no tienen un color de marca equivalente -- son estados
# intermedios del semáforo (alguna señal positiva, pero no las dos a la
# vez) y se dejan deliberadamente distintos de hot/cold: forzarlos a ser
# variantes de esos dos colores reduciría las 4 categorías del semáforo a
# solo 2 tonos, rompiendo su lectura rápida.
COLOR_PASO = "#E8A23E"
COLOR_NICHO = "#C9793A"
COLOR_SIN_DATOS = "#C7CDD3"


def classify_zones(summary_df: pd.DataFrame) -> dict:
    """Devuelve {zone_id: (etiqueta, color_hex)} para cada zona del resumen."""
    if summary_df.empty:
        return {}

    classifications = {}

    if len(summary_df) == 1:
        # Caso de una sola zona: no hay tráfico relativo con qué comparar,
        # clasificamos solo por qué tan "exitosa" es la interacción.
        row = summary_df.iloc[0]
        if row["stop_rate_pct"] >= 50:
            label, color = "Zona Caliente", COLOR_CALIENTE
        else:
            label, color = "Zona de Paso", COLOR_PASO
        classifications[row["zone_id"]] = (label, color)
        return classifications

    median_visits = summary_df["total_visits"].median()
    median_dwell = summary_df["avg_dwell_seconds"].median()

    for _, row in summary_df.iterrows():
        high_traffic = row["total_visits"] >= median_visits
        high_dwell = row["avg_dwell_seconds"] >= median_dwell

        if high_traffic and high_dwell:
            label, color = "Zona Caliente", COLOR_CALIENTE
        elif high_traffic and not high_dwell:
            label, color = "Zona de Paso", COLOR_PASO
        elif not high_traffic and high_dwell:
            label, color = "Interés de Nicho", COLOR_NICHO
        else:
            label, color = "Zona Fría", COLOR_FRIA

        classifications[row["zone_id"]] = (label, color)

    return classifications


def render_layout_plot(zones_config: list, summary_df: pd.DataFrame, frame_width: int, frame_height: int):
    """Genera una figura de matplotlib con el plano simplificado de la
    tienda: cada zona dibujada como polígono coloreado según su
    clasificación, con su nombre y métrica clave visibles."""
    classifications = classify_zones(summary_df)
    summary_by_id = summary_df.set_index("zone_id").to_dict("index") if not summary_df.empty else {}

    # Recortar la vista al área que realmente ocupan las zonas (+ margen),
    # no al frame de cámara completo -- con pocas zonas calibradas en una
    # esquina de un frame grande, mostrar el frame entero deja la mayor
    # parte del plot vacía ("se ve sin terminar"). Se limita al tamaño del
    # frame original para no "hacer zoom" más allá de lo que existe.
    all_x = [p[0] for zone in zones_config for p in zone["polygon"]]
    all_y = [p[1] for zone in zones_config for p in zone["polygon"]]
    if all_x and all_y:
        margin_x = max((max(all_x) - min(all_x)) * 0.10, 24)
        margin_y = max((max(all_y) - min(all_y)) * 0.10, 24)
        view_x0 = max(min(all_x) - margin_x, 0)
        view_x1 = min(max(all_x) + margin_x, frame_width)
        view_y0 = max(min(all_y) - margin_y, 0)
        view_y1 = min(max(all_y) + margin_y, frame_height)
    else:
        view_x0, view_x1, view_y0, view_y1 = 0, frame_width, 0, frame_height

    view_width = view_x1 - view_x0
    view_height = view_y1 - view_y0

    fig, ax = plt.subplots(figsize=(9, 9 * view_height / view_width))
    fig.patch.set_facecolor(PANEL)
    # Sin esto, matplotlib reserva su margen de layout por defecto
    # (~10-12% a cada lado) ALREDEDOR de los ejes dentro de la figura,
    # sin importar qué tan ajustados estén los límites de datos de
    # arriba -- ese margen de figura (no el margen de datos) era la
    # causa real de que la zona se viera "flotando" con mucho blanco
    # alrededor. Los ejes ahora ocupan casi el 100% del lienzo (un 1%
    # de aire para no recortar el trazo del marco, dibujado justo en
    # el límite de los ejes).
    ax.set_position([0.01, 0.01, 0.98, 0.98])
    ax.set_xlim(view_x0, view_x1)
    ax.set_ylim(view_y1, view_y0)  # invertido: (0,0) es esquina superior izquierda, como en video/imagen
    ax.set_aspect("equal")
    ax.axis("off")
    # SURFACE (no PANEL/blanco) para el área de dibujo: el panel de
    # Streamlit que envuelve este plot YA es blanco (--color-panel), así
    # que si el plot también es blanco, no tiene ningún borde/fondo
    # propio que lo distinga del panel -- se ve como "una forma de color
    # flotando en espacio en blanco", sin verse como una imagen contenida.
    # SURFACE es un tono distinto (el mismo "gris pizarra" del fondo de
    # página) que sí crea un límite visual perceptible.
    ax.set_facecolor(SURFACE)

    # Marco explícito alrededor de TODA el área visible -- sin esto, con
    # axis("off") no queda ningún borde que delimite "esto es un
    # plano/mapa", solo las formas de zona sueltas. Se usa
    # --color-ink-muted (no la variante ultra-sutil --color-line que se usa
    # para bordes de paneles en CSS) porque este trazo es la ÚNICA señal
    # visual de "esto es un diagrama contenido" -- ahí sí necesita
    # notarse, a diferencia de un borde de panel que ya tiene sombra/fondo
    # ayudando.
    ax.add_patch(Rectangle((view_x0, view_y0), view_width, view_height, fill=False,
                            edgecolor=INK_MUTED, linewidth=1.5, zorder=0))

    for zone in zones_config:
        zone_id = zone["id"]
        label, color = classifications.get(zone_id, ("Sin datos", COLOR_SIN_DATOS))
        polygon_pts = zone["polygon"]

        patch = MplPolygon(polygon_pts, closed=True, facecolor=color,
                            edgecolor="white", linewidth=2, alpha=0.75)
        ax.add_patch(patch)

        cx = sum(p[0] for p in polygon_pts) / len(polygon_pts)
        cy = sum(p[1] for p in polygon_pts) / len(polygon_pts)

        metric_text = zone["label"]
        if zone_id in summary_by_id:
            visits = summary_by_id[zone_id]["total_visits"]
            dwell = summary_by_id[zone_id]["avg_dwell_seconds"]
            metric_text += f"\n{label}\n{visits} visitas | {dwell:.1f}s prom."
        else:
            metric_text += "\n(sin visitas registradas)"

        # Texto blanco sobre un recuadro semitransparente en --color-ink
        # (no negro puro -- coherente con el resto del sistema de diseño,
        # aunque matplotlib no puede usar Manrope/IBM Plex Sans: son
        # fuentes de Google Fonts que solo se cargan en el navegador vía
        # <link> en templates/layout.html, no están instaladas como fuente del
        # sistema en este entorno, y matplotlib solo puede usar fuentes
        # instaladas localmente -- limitación técnica real, no un
        # descuido. Se mantiene la fuente sans-serif por defecto de
        # matplotlib). alpha=0.55, verificado para dar >=4.5:1 de
        # contraste incluso contra el color de zona más claro (Sin
        # datos) -- con --color-ink da 5.06:1 (con negro puro daba
        # 4.26:1 a alpha=0.4, el valor original).
        ax.text(cx, cy, metric_text, ha="center", va="center",
                fontsize=9, color="white", fontweight="bold",
                bbox=dict(boxstyle="round,pad=0.4", facecolor=INK, alpha=0.55, edgecolor="none"))

    plt.tight_layout()
    return fig


def get_legend_html() -> str:
    """HTML simple de leyenda de colores (no usado actualmente por
    templates/results.html, que arma su propia leyenda inline -- se deja
    disponible como utilidad reutilizable)."""
    items = [
        (COLOR_CALIENTE, "Zona Caliente (alto tráfico + se detienen)"),
        (COLOR_PASO, "Zona de Paso (alto tráfico, no se detienen)"),
        (COLOR_NICHO, "Interés de Nicho (poco tráfico, sí se detienen)"),
        (COLOR_FRIA, "Zona Fría (poco tráfico)"),
    ]
    html = "<div style='display:flex; flex-wrap:wrap; gap:16px;'>"
    for color, text in items:
        html += (
            f"<div style='display:flex; align-items:center; gap:6px;'>"
            f"<div style='width:16px; height:16px; background:{color}; border-radius:3px;'></div>"
            f"<span style='font-size:13px; color:var(--color-ink);'>{text}</span></div>"
        )
    html += "</div>"
    return html
