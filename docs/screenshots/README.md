# Capturas de pantalla -- rediseño visual (Flask, ver architecture.md sección 26)

Capturas reales tomadas con Playwright + Chromium headless contra el
servidor Flask corriendo localmente, tras el rediseño de diseño
profesional (sistema de espaciado/tipografía, íconos Lucide, gráfico de
tendencias con Chart.js). Inspeccionadas visualmente una por una antes
de darse por buenas -- ver architecture.md sección 26 para el detalle
de qué se corrigió durante esa inspección.

- `01_bienvenida.png` -- pantalla inicial sin tienda seleccionada.
- `02_resultados_historia.png` a `07_resultados_recomendaciones_ia.png` -- las 6 pestañas del panel de resultados de solo lectura (datos reales de `merl_demo`).
- `05a_resultados_tendencias_sin_historial.png` -- estado vacío de Tendencias (menos de 2 fechas guardadas).
- `05b_resultados_tendencias_con_grafico.png` -- el gráfico de evolución (Chart.js) con datos de ejemplo insertados TEMPORALMENTE en `history.db` solo para esta captura, y luego eliminados -- el proyecto no tiene historial real guardado en este momento; la funcionalidad queda disponible para cuando el usuario procese videos con "Guardar en el historial" activado más de una vez.
- `08_asistente_paso1_subir.png` a `11_asistente_paso4_procesar.png` -- el asistente de configuración: subida, recorte, calibración de zonas por canvas (con una zona ya dibujada), y la sección de procesamiento con ajustes avanzados expandidos.
