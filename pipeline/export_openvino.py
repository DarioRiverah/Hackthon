"""
Convierte el modelo YOLO activo del pipeline (ver docs/architecture.md
sección 16) a formato OpenVINO (IR: .xml + .bin) para acelerar la
inferencia en CPU -- especialmente en CPUs Intel, pero OpenVINO también
acelera sobre otras arquitecturas x86 vía su backend de CPU genérico.
Se ejecuta en tiempo de BUILD de Docker (ver Dockerfile), nunca en el
primer arranque del contenedor -- mismo principio que el horneado de los
.pt (ver docs/architecture.md, sección de Docker).

RED DE SEGURIDAD (obligatoria, no opcional): la conversión a OpenVINO es
PURAMENTE una optimización de velocidad -- nunca una dependencia dura del
pipeline. Si falla por CUALQUIER motivo (paquete `openvino` ausente o
incompatible, arquitectura de CPU no soportada, timeout, lo que sea), este
script SIEMPRE termina con código de salida 0 y simplemente no deja el
directorio "<modelo>_openvino_model/" -- pipeline/detect_and_track.py
(ver load_model() ahí) verifica si ese directorio existe antes de
intentar usarlo, y si no existe (porque nunca se creó, o porque se creó
pero falla al cargar) usa el .pt original sin ningún cambio de
comportamiento. El pipeline NUNCA debe fallar por culpa de esta
optimización.

Variable de entorno OPENVINO_EXPORT_FORMAT (default "openvino"): existe
para poder FORZAR un fallo de conversión a propósito en pruebas (pasando
un valor de formato inválido, ej. vía `--build-arg
OPENVINO_EXPORT_FORMAT=formato_invalido_de_prueba` en el build de Docker)
y confirmar que esta red de seguridad realmente funciona -- ver el
resumen de la tarea correspondiente / docs/architecture.md para el
resultado real de esa prueba.
"""
import os
import sys

from ultralytics import YOLO

MODELS = ["yolo26n-pose.pt"]
EXPORT_FORMAT = os.environ.get("OPENVINO_EXPORT_FORMAT", "openvino")


def main():
    any_failed = False
    for model_name in MODELS:
        try:
            path = YOLO(model_name).export(format=EXPORT_FORMAT)
            print(f"OPENVINO_EXPORT_OK: {model_name} -> {path}")
        except Exception as e:
            any_failed = True
            print(f"OPENVINO_EXPORT_FAILED: {model_name}: {type(e).__name__}: {e}")

    if any_failed:
        print(
            "AVISO: uno o más modelos no se pudieron convertir a OpenVINO -- el "
            "pipeline usará los .pt originales para esos casos (ver load_model() "
            "en pipeline/detect_and_track.py). Esto NO es un error fatal del build."
        )

    sys.exit(0)  # SIEMPRE 0 -- ver docstring del módulo.


if __name__ == "__main__":
    main()
