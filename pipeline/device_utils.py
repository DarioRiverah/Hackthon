"""
Detección y resolución del dispositivo de procesamiento (CPU/GPU) para
los modelos de Ultralytics.

Ultralytics YA elige automáticamente GPU si hay una disponible, CPU si
no (ver ultralytics.utils.torch_utils.select_device) -- este módulo
agrega la posibilidad de FORZAR una opción explícita desde la interfaz
del asistente de configuración, con detección real (no asumida) de si
hay GPU disponible en este momento.
"""

import torch

VALID_DEVICE_CHOICES = ("auto", "cpu", "gpu")


def get_gpu_info() -> dict:
    """Detecta si hay una GPU CUDA disponible AHORA MISMO en esta
    máquina y, si la hay, su nombre (ej. "NVIDIA GeForce RTX 3050").
    No se cachea -- se recalcula en cada llamada porque el estado real
    puede cambiar entre la carga de la página del asistente y el
    momento en que se procesa el video."""
    available = torch.cuda.is_available()
    name = torch.cuda.get_device_name(0) if available else None
    return {"available": available, "name": name}


def should_skip_openvino(device_choice: str) -> bool:
    """Decide si la carga del modelo debe IGNORAR el .pt optimizado a
    OpenVINO (ver pipeline/detect_and_track.py:load_model) y usar
    directamente el .pt original.

    Esto es DISTINTO de "¿hay GPU?" -- el backend OpenVINO de Ultralytics
    NUNCA usa una GPU NVIDIA/CUDA, sea cual sea el dispositivo que se le
    pida: cuando existe el directorio "<modelo>_openvino_model/" y no se
    salta, OpenVINO elige su PROPIO dispositivo internamente (su Core()
    con el plugin "AUTO"), que en un equipo con GPU integrada de Intel
    (muy común en laptops que ADEMÁS traen una GPU NVIDIA dedicada, ej.
    esta RTX 3050) puede terminar corriendo en esa GPU integrada -- sin
    que el .pt/CUDA original, mucho más rápido, llegue siquiera a
    intentarse. Antes de esta corrección, 'auto' (la opción por defecto)
    cargaba el modelo OpenVINO sin más, así que en la práctica NUNCA
    usaba la GPU NVIDIA aunque estuviera disponible.

    - 'gpu'  -> True SIEMPRE: se forzó GPU explícitamente, así que debe
      ir directo al .pt original vía CUDA (resolve_device ya valida que
      haya una GPU real antes de llegar acá).
    - 'auto' -> True solo si HAY una GPU CUDA disponible ahora mismo: en
      ese caso preferimos el .pt original sobre CUDA (más rápido que
      cualquier cosa que OpenVINO pueda ofrecer) en vez de arriesgarnos
      a que OpenVINO elija la GPU integrada o la CPU. Si no hay GPU CUDA,
      el objetivo de 'auto' sigue siendo maximizar velocidad en CPU, así
      que ahí SÍ conviene el modelo optimizado a OpenVINO.
    - 'cpu'  -> False siempre: CPU fue forzada explícitamente, y para
      CPU el modelo OpenVINO es una aceleración real, no un riesgo."""
    if device_choice == "gpu":
        return True
    if device_choice == "auto":
        return torch.cuda.is_available()
    return False


def resolve_device(device_choice: str):
    """Traduce la opción elegida en la interfaz ('auto'/'cpu'/'gpu') al
    valor que espera Ultralytics en `model.track(device=...)`.

    - 'auto' -> None: el llamador NO debe pasar el parámetro `device`
      en absoluto, dejando que Ultralytics decida como ya hacía antes
      de que existiera este selector (GPU si hay, si no CPU).
    - 'cpu'  -> "cpu"
    - 'gpu'  -> 0 (primer índice de GPU CUDA) -- levanta RuntimeError
      con un mensaje claro si en este momento no hay ninguna GPU
      disponible (ej. se desconectó o falló el driver entre la carga
      de la página y el procesamiento real).
    """
    if device_choice not in VALID_DEVICE_CHOICES:
        raise ValueError(f"Dispositivo inválido: '{device_choice}' (válidos: {VALID_DEVICE_CHOICES})")

    if device_choice == "auto":
        return None
    if device_choice == "cpu":
        return "cpu"

    if not torch.cuda.is_available():
        raise RuntimeError(
            "Se forzó el uso de GPU, pero no se detectó ninguna GPU CUDA disponible en "
            "este equipo en este momento (¿se desconectó o el driver falló después de "
            "cargar la página del asistente?). Vuelve a intentar con 'Automático' o "
            "'Forzar CPU'."
        )
    return 0
