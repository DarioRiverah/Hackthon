"""
Paleta de colores del proyecto -- constantes de Python puras, SIN
ninguna dependencia de Streamlit ni de Flask.

Por qué existe este archivo separado: dashboard/layout_view.py
(matplotlib) y dashboard/report_generator.py (reportlab) son lógica de
negocio pura que no debería requerir ningún framework de interfaz para
poder importarse y usarse (ej. en pruebas, en scripts de línea de
comandos, o en cualquier futuro backend). Antes importaban estos mismos
valores desde el antiguo dashboard/style.py (ahora en
_legacy_streamlit/style.py), que tenía `import streamlit as st` a
nivel de módulo -- eso significaba que ni layout_view.py ni
report_generator.py podían importarse sin tener Streamlit instalado,
aunque ninguno de los dos usa ninguna función de Streamlit. Se separó
al iniciar la migración a Flask (ver docs/architecture.md) precisamente
para poder confirmar que la lógica pura es reutilizable tal cual.

Es la MISMA paleta que usa el frontend web (static/css/main.css, sección
de variables :root) -- si cambias un color, cámbialo en AMBOS lugares
(son la misma fuente de verdad duplicada por necesidad técnica: CSS no
puede leer constantes de Python, y matplotlib/reportlab no pueden leer
variables CSS).
"""

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
