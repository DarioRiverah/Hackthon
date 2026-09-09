#!/usr/bin/env bash
# Arranca retail-vision-mvp con Docker, eligiendo automáticamente entre la
# variante GPU (docker-compose.gpu.yml, más rápida) y la CPU
# (docker-compose.yml, el camino soportado por defecto -- ver DOCKER.md)
# según si esta máquina tiene una GPU NVIDIA realmente utilizable desde
# Docker. No asume nada: prueba el passthrough de verdad antes de elegir.
#
# Uso: ./docker-run.sh
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PROJECT_ROOT"

# Prueba real de passthrough de GPU (no solo "existe nvidia-smi en el
# PATH"): corre un contenedor mínimo pidiendo la GPU y confirma que
# responde -- así se detectan también los casos de "hay GPU pero Docker
# Desktop no tiene el backend WSL2/soporte de GPU activado", que son
# indistinguibles de "no hay GPU" con cualquier chequeo más superficial.
has_usable_gpu() {
    command -v nvidia-smi >/dev/null 2>&1 || return 1
    docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi >/dev/null 2>&1
}

if has_usable_gpu; then
    echo "GPU NVIDIA detectada y accesible desde Docker -- usando la variante GPU (docker-compose.gpu.yml)."
    echo "(Más lenta de construir la primera vez -- descarga PyTorch con CUDA, ~2GB. Ver DOCKER.md.)"
    exec docker compose -f docker-compose.gpu.yml up --build
else
    echo "No se detectó una GPU NVIDIA utilizable desde Docker -- usando la imagen CPU (camino soportado por defecto)."
    exec docker compose -f docker-compose.yml up --build
fi
