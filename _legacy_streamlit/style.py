"""
Identidad visual del dashboard.

El CSS en sí vive en dashboard/assets/theme.css (archivo independiente,
no un string de Python) -- este módulo solo lo lee e inyecta, y provee
las funciones que generan HTML dinámico (status_chip, render_step_status).

Los valores de color de abajo son la MISMA paleta definida como variables
CSS en theme.css (sección 1, "VARIABLES / TOKENS") -- se repiten aquí como
constantes de Python porque matplotlib (dashboard/layout_view.py) y
reportlab (dashboard/report_generator.py) no pueden consumir variables CSS,
necesitan un valor hex real. Si cambias un color, cámbialo en AMBOS lugares
(theme.css y aquí) -- son la misma fuente de verdad duplicada por necesidad
técnica, no dos paletas distintas.

Rediseño completo (paleta Surface/Ink/Hot/Cold + tipografía Manrope/IBM Plex
Sans) -- reemplaza sin mezclar el sistema anterior (Ember/Frost, Space
Grotesk/Inter). Ver docs/architecture.md para el razonamiento y la
verificación de contraste WCAG completa (también documentada al final de
theme.css).
"""

import os
import textwrap

import streamlit as st

SURFACE = "#EEF1F4"
PANEL = "#FFFFFF"
SURFACE_ALT = "#E3E8ED"
INK = "#1A2333"
INK_MUTED = "#5B6472"
INK_ON_ACCENT = "#000000"
LINE = "#D7DEE5"

HOT = "#E8543E"
HOT_TEXT = "#B93C27"
COLD = "#0EA5A0"
COLD_TEXT = "#0A736F"

ZONE_PASO = "#E8A23E"
ZONE_NICHO = "#C9793A"
ZONE_NONE = "#C7CDD3"

INFO = "#2E72C7"
SUCCESS = "#157A52"
WARNING = "#9C5F0C"
ERROR = "#C93B4E"

_THEME_CSS_PATH = os.path.join(os.path.dirname(__file__), "assets", "theme.css")


def inject_custom_style():
    """Lee dashboard/assets/theme.css e inyecta su contenido tal cual --
    este módulo no define ni un solo color/fuente por su cuenta, todo vive
    en ese archivo."""
    with open(_THEME_CSS_PATH, "r", encoding="utf-8") as f:
        css = f.read()
    st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)


def status_chip(label: str, active: bool) -> str:
    """Una 'píldora' de estado compacta para la barra lateral (ej. 'Calibrada ✓').

    Diseño: el TEXTO siempre usa var(--color-ink) (máximo contraste
    garantizado, ver verificación en theme.css) -- el estado se comunica con
    un punto de color decorativo (Cold=activo, Ink-muted=pendiente) y un
    fondo tenue, no coloreando el texto en sí. Antes el texto SÍ iba
    coloreado (Frost/gris) y no pasaba 4.5:1 de contraste -- corregido en
    este rediseño."""
    dot_color = "var(--color-cold)" if active else "var(--color-ink-muted)"
    background = "rgba(14, 165, 160, 0.10)" if active else "rgba(91, 100, 114, 0.10)"
    symbol = "●" if active else "○"
    return (
        f"<span style='display:inline-block; color:var(--color-ink); background:{background}; "
        f"font-family:var(--font-body); font-size:12px; font-weight:500; padding:3px 10px; "
        f"border-radius:12px; margin-right:8px;'>"
        f"<span style='color:{dot_color};'>{symbol}</span> {label}</span>"
    )


def render_step_status(step_num: int, total_steps: int, description: str) -> str:
    """HTML de un indicador de progreso con anillo giratorio (animación CSS
    pura, sigue girando aunque no lleguen líneas nuevas de log por un rato).
    Estilos en línea vía var(--color-x) -- siguen funcionando igual sin
    importar qué más cambie en theme.css, siempre que las variables sigan
    declaradas en :root.

    IMPORTANTE: el resultado se pasa por textwrap.dedent(...).strip() antes
    de devolverlo. Sin eso, el string (un f-string triple-comillado con el
    HTML indentado 4 espacios para que se lea bien en el código) empieza
    con 4+ espacios de indentación -- y CommonMark interpreta CUALQUIER
    línea indentada 4 espacios o más como un BLOQUE DE CÓDIGO literal, no
    como HTML, sin importar que el llamador use unsafe_allow_html=True.
    Verificado con un parser real (markdown-it-py): sin dedent, esto se
    parseaba como un solo token 'code_block' (el texto crudo visible,
    escapado, en fuente monoespaciada) en vez de 'html_block'. Es el mismo
    tipo de bug que el de theme.css (sección 22 de docs/architecture.md),
    solo que causado por indentación en vez de por una etiqueta de cierre
    prematura."""
    html = f"""
    <div style='display:flex; align-items:center; gap:12px; padding:14px 18px;
                background:var(--color-panel); border:1px solid var(--color-line);
                border-radius:8px;'>
        <div style='width:22px; height:22px; border:3px solid var(--color-line);
                    border-top-color:var(--color-hot); border-radius:50%;
                    animation:girar 0.8s linear infinite;'></div>
        <div>
            <div style='font-family:var(--font-heading); font-weight:700; color:var(--color-ink);'>
                Paso {step_num} de {total_steps}
            </div>
            <div style='font-family:var(--font-body); font-size:14px; color:var(--color-ink); opacity:0.75;'>{description}</div>
        </div>
    </div>
    <style>
    @keyframes girar {{ from {{transform:rotate(0deg);}} to {{transform:rotate(360deg);}} }}
    </style>
    """
    return textwrap.dedent(html).strip()
