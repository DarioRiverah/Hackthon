# Arranca retail-vision-mvp con Docker, eligiendo automaticamente entre la
# variante GPU (docker-compose.gpu.yml, mas rapida) y la CPU
# (docker-compose.yml, el camino soportado por defecto -- ver DOCKER.md)
# segun si esta maquina tiene una GPU NVIDIA realmente utilizable desde
# Docker. No asume nada: prueba el passthrough de verdad antes de elegir.
#
# Uso: .\docker-run.ps1
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

function Test-UsableGpu {
    # Prueba real de passthrough de GPU (no solo "nvidia-smi existe en el
    # PATH"): corre un contenedor minimo pidiendo la GPU y confirma que
    # responde -- asi se detectan tambien los casos de "hay GPU pero Docker
    # Desktop no tiene el backend WSL2/soporte de GPU activado", que son
    # indistinguibles de "no hay GPU" con cualquier chequeo mas superficial.
    if (-not (Get-Command nvidia-smi -ErrorAction SilentlyContinue)) {
        return $false
    }
    try {
        docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi *> $null
        return $LASTEXITCODE -eq 0
    } catch {
        return $false
    }
}

if (Test-UsableGpu) {
    Write-Host "GPU NVIDIA detectada y accesible desde Docker -- usando la variante GPU (docker-compose.gpu.yml)."
    Write-Host "(Mas lenta de construir la primera vez -- descarga PyTorch con CUDA, ~2GB. Ver DOCKER.md.)"
    docker compose -f docker-compose.gpu.yml up --build
} else {
    Write-Host "No se detecto una GPU NVIDIA utilizable desde Docker -- usando la imagen CPU (camino soportado por defecto)."
    docker compose -f docker-compose.yml up --build
}
