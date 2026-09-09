"""
Punto de entrada del backend web (Flask) -- reemplaza la versión
anterior basada en Streamlit (preservada como referencia histórica en
_legacy_streamlit/app.py, ver docs/architecture.md sección 25 para el
razonamiento completo de la migración).

Arquitectura: Flask + Jinja2 + HTML/CSS/JS propio (sin frameworks de
frontend de terceros). Mayormente SIN ESTADO en memoria -- lee/escribe
los mismos archivos que ya usa pipeline/*.py (config/zones_*.json,
data/output/*.csv, data/processed/*). Los procesos largos (el pipeline)
corren en un hilo de fondo (dashboard/job_manager.py) con polling desde
el frontend, no WebSockets.

IMPORTANTE: debe ejecutarse con el directorio de trabajo en la RAÍZ del
proyecto (igual que la versión Streamlit, que se corría con
`streamlit run dashboard\\app.py` desde ahí) -- toda la lógica de
negocio (pipeline/*.py, dashboard/store_service.py, etc.) usa rutas
relativas como "config/" y "data/output/" asumiendo esa raíz.

Uso:
    python dashboard\\app.py
"""

import os
import sys

from flask import Flask, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from routes.main_routes import main_bp
from routes.setup_routes import setup_bp
from routes.api_routes import api_bp


def create_app() -> Flask:
    app = Flask(__name__)
    # Clave de sesión: solo se usa para mensajes flash / estado transitorio
    # muy puntual -- la mayoría del estado real vive en archivos, no en
    # sesión (ver docstring del módulo). No es sensible (no guarda ninguna
    # credencial ni dato de negocio), así que un valor fijo por proceso es
    # suficiente para este alcance.
    app.secret_key = os.environ.get("FLASK_SECRET_KEY", "retail-vision-mvp-dev-key")

    # Límite generoso de subida (videos pueden pesar varias decenas de MB).
    app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2 GB

    app.register_blueprint(main_bp)
    app.register_blueprint(setup_bp)
    app.register_blueprint(api_bp)

    @app.context_processor
    def inject_partial_base():
        """Navegación sin recarga completa (pjax, ver static/js/main.js:
        navigateTo() y docs/architecture.md): si la petición viene de ahí
        (identificada por el header X-Requested-With: fetch-nav que
        navigateTo() ya manda), las plantillas de página extienden
        templates/layout_fragment.html (solo <title> + contenido + zona
        dinámica de la sidebar) en vez de templates/layout.html (documento
        completo) -- cada plantilla de página hace {% extends partial_base %}
        en vez de extender "layout.html" a secas, así el MISMO
        render_template(...) de cada vista sirve ambos casos sin que la
        vista tenga que saber nada de esto ni duplicar lógica."""
        is_fetch_nav = request.headers.get("X-Requested-With") == "fetch-nav"
        return {"partial_base": "layout_fragment.html" if is_fetch_nav else "layout.html"}

    return app


app = create_app()


if __name__ == "__main__":
    # Verifica que estamos parados en la raíz del proyecto antes de arrancar
    # -- un error aquí es silencioso y confuso si no se detecta pronto
    # (todas las tiendas se verían vacías).
    if not os.path.isdir("pipeline") or not os.path.isdir("dashboard"):
        print(
            "ERROR: corre este comando desde la RAÍZ del proyecto "
            "(donde están las carpetas pipeline/ y dashboard/), ej.:\n"
            "  python dashboard\\app.py"
        )
        sys.exit(1)

    # use_reloader=False es importante: el estado de los trabajos en
    # segundo plano (dashboard/job_manager.py) vive en un dict en memoria
    # del proceso. El reloader de Werkzeug puede reiniciar el proceso ante
    # CUALQUIER archivo que detecte "modificado" bajo el directorio del
    # proyecto -- incluyendo archivos dentro de venv/ que algunas
    # dependencias (p.ej. torch) tocan en tiempo de ejecución -- y un
    # reinicio a mitad de un "Procesar video" borraría todo el progreso
    # sin aviso. debug=True se mantiene para tracebacks útiles en desarrollo.
    #
    # host/port configurables por variable de entorno (default: igual que
    # siempre, 127.0.0.1:5000) -- necesario para Docker (ver DOCKER.md y
    # docs/architecture.md): un servidor atado a 127.0.0.1 solo acepta
    # conexiones desde DENTRO del mismo namespace de red, así que dentro de
    # un contenedor el mapeo de puertos del host nunca lo alcanzaría. El
    # Dockerfile/docker-compose.yml fijan FLASK_HOST=0.0.0.0; correrlo
    # localmente sin definir la variable se comporta exactamente igual que
    # antes.
    host = os.environ.get("FLASK_HOST", "127.0.0.1")
    port = int(os.environ.get("FLASK_PORT", "5000"))
    app.run(debug=True, use_reloader=False, host=host, port=port)
