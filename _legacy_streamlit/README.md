# Archivo histórico -- versión Streamlit descartada

Este directorio contiene la implementación original del dashboard, hecha
con Streamlit, **reemplazada por completo** por la app Flask actual en
`dashboard/`. Nada de este código se ejecuta ni se importa desde el
proyecto activo -- se conserva únicamente como referencia histórica.

- `app.py` -- el `dashboard/app.py` original (Streamlit), antes de la
  migración a Flask.
- `style.py` -- el `dashboard/style.py` original, con los constantes de
  color y la inyección de CSS específica de Streamlit.
- `theme.css` -- el `dashboard/assets/theme.css` original, inyectado
  dinámicamente en la app de Streamlit (fuente del bug documentado en
  `docs/architecture.md`, sección 23).
- `streamlit_config/config.toml` -- el antiguo `.streamlit/config.toml`
  (tema nativo de Streamlit: colores, fuentes).

Ver `docs/architecture.md`, sección 25, para la decisión completa de
migrar a Flask y por qué.

**Pendiente de decisión del usuario**: si en algún momento se confirma
que esta carpeta ya no hace falta ni siquiera como referencia, se puede
borrar por completo sin afectar el proyecto activo.
