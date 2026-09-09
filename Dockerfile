# =============================================================================
# retail-vision-mvp -- imagen CPU (camino principal, soportado y probado).
# Ver DOCKER.md y docs/architecture.md (sección Docker) para el contexto
# completo de esta decisión.
# =============================================================================
FROM python:3.13-slim

# Dependencias de sistema que requiere `opencv-python` (NO la variante
# "headless") en Debian slim -- confirmado construyendo esta imagen: sin
# libgl1 y libglib2.0-0, `import cv2` falla con
# "ImportError: libGL.so.1: cannot open shared object file". libsm6/
# libxext6/libxrender1 se agregan porque son la otra dependencia clásica de
# OpenCV con soporte de GUI/X11 parcial (algunas rutas internas de OpenCV
# las importan aunque el proceso corra sin display); no se usa ningún
# entorno gráfico real, esto es solo para que las librerías compartidas
# resuelvan sus símbolos al cargar.
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libsm6 \
        libxext6 \
        libxrender1 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Paso separado para aprovechar la cache de capas de Docker: mientras
# requirements.txt no cambie, `pip install` no se vuelve a ejecutar aunque
# cambie el código de la app.
COPY requirements.txt .

# PyTorch: se instala EXPLÍCITAMENTE la build CPU-only desde el índice
# oficial de PyTorch (no la build por defecto de PyPI, que en Linux incluye
# los binarios CUDA embebidos y agrega gigabytes al tamaño de la imagen
# aunque nunca se use GPU). ultralytics declara torch/torchvision como
# dependencia, así que se instalan ambos ANTES del resto de
# requirements.txt para que pip los encuentre ya satisfechos y no intente
# reemplazarlos por la build CUDA por defecto.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu \
        torch torchvision

RUN pip install --no-cache-dir -r requirements.txt

# Hornea los modelos YOLO usados por el pipeline en producción DENTRO de la
# imagen -- ver pipeline/detect_and_track.py (yolo26n.pt, detección de
# cuerpo) y pipeline/detect_hand_positions.py (yolov8n-pose.pt, detección
# de manos); confirmado por lectura de pipeline/run_pipeline.py (la cadena
# real que arma dashboard/job_manager.py) que estos son los ÚNICOS dos
# modelos que la ruta de producción carga -- otros scripts del repo
# (heatmap_ultralytics.py, experimental_yoloe_product_test.py) usan otros
# pesos pero no forman parte de esta cadena, así que no se hornean.
# `YOLO("nombre.pt")` descarga el peso oficial de Ultralytics la primera
# vez que se instancia si no lo encuentra en el cache local -- forzar esa
# descarga aquí, en build time, es lo que garantiza que el contenedor
# arranque 100% offline en la demo (ver docs/architecture.md).
RUN python -c "from ultralytics import YOLO; YOLO('yolo26n.pt'); YOLO('yolov8n-pose.pt')"

# Copia SOLO el script de conversión (no todo el código todavía) para que
# esta capa -- que descarga/convierte modelos, no cambia con cada edición
# del resto de la app -- siga aprovechando la cache de Docker. El resto
# del código llega con el COPY . . de más abajo.
COPY pipeline/export_openvino.py pipeline/export_openvino.py

# Convierte los modelos a formato OpenVINO (acelera inferencia en CPU) --
# ver pipeline/export_openvino.py para la RED DE SEGURIDAD completa: ese
# script SIEMPRE termina en 0 pase lo que pase, así que este RUN nunca
# puede tumbar el build. Si la conversión falla, el pipeline sigue
# funcionando con los .pt originales sin ningún cambio de comportamiento
# (ver pipeline/detect_and_track.py:load_model()).
#
# OPENVINO_EXPORT_FORMAT (ARG, default "openvino"): existe para poder
# forzar un fallo de conversión a propósito en pruebas, ej.:
#   docker build --build-arg OPENVINO_EXPORT_FORMAT=formato_invalido .
# -- ver docs/architecture.md para el resultado real de esa prueba.
ARG OPENVINO_EXPORT_FORMAT=openvino
ENV OPENVINO_EXPORT_FORMAT=${OPENVINO_EXPORT_FORMAT}
RUN python pipeline/export_openvino.py

# Código de la aplicación (ver .dockerignore: venv/, .git/, videos de
# verificación pesados, etc. quedan fuera para no inflar la imagen ni
# invalidar la cache de capas de arriba en cada cambio de código).
COPY . .

# Flask (ver dashboard/app.py) -- puerto real que usa el dev server.
EXPOSE 5000

# FLASK_HOST=0.0.0.0 es OBLIGATORIO dentro del contenedor: dashboard/app.py
# por defecto usa 127.0.0.1 (correcto para uso local fuera de Docker), que
# dentro de un contenedor solo acepta conexiones de su propio namespace de
# red -- el mapeo de puertos del host nunca lo alcanzaría sin esto.
ENV FLASK_HOST=0.0.0.0
ENV FLASK_PORT=5000

# Arranca la app tal como se arrancaría normalmente (`python dashboard/app.py`
# desde la raíz del proyecto -- ver el docstring de ese archivo, toda la
# lógica de negocio asume rutas relativas a la raíz).
CMD ["python", "dashboard/app.py"]
