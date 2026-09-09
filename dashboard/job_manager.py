"""
Gestor genérico de procesos largos en segundo plano (el pipeline puede
tardar varios minutos) -- usa threading.Thread + subprocess, tal como
pide la migración a Flask (nada de WebSockets/Flask-SocketIO, que sería
complejidad innecesaria para este alcance).

Cada job se identifica por una clave arbitraria (normalmente
f"{store_name}:{tipo}") y guarda su estado en un diccionario en memoria
del proceso -- suficiente porque Flask corre acá como un solo proceso
(servidor de desarrollo), no multi-proceso. El frontend hace polling a
un endpoint que lee este estado vía get_job().

No es lógica de negocio del proyecto (no calcula nada sobre
tráfico/interacción) -- es infraestructura del backend web, así que no
tiene ninguna dependencia de Streamlit ni falta de ella; es exclusiva
de esta migración a Flask.
"""

import re
import subprocess
import threading

_jobs = {}
_lock = threading.Lock()

# Detecta líneas como "[3/10] Descripción" (inicio de paso) en la salida
# del pipeline -- mismo patrón que ya se parseaba en la versión Streamlit.
_STEP_PATTERN = re.compile(r"^\[(\d+)/(\d+)\]\s+(?!completado)(.+)$")


def start_job(job_key: str, command: list, env: dict = None, retry_env: dict = None):
    """Lanza `command` en un hilo de fondo y devuelve de inmediato. Si ya
    hay un job con esa clave corriendo, no lanza uno nuevo (evita doble
    clic disparando el pipeline dos veces).

    `retry_env`: red de seguridad de OpenVINO (ver pipeline/export_openvino.py,
    pipeline/run_pipeline.py:run_step y docs/architecture.md) -- se usa acá
    para la vista previa de calor (que llama a detect_and_track.py
    directamente, fuera de run_pipeline.py). Si el proceso termina con
    código distinto de cero, se reintenta UNA vez con esta variable de
    entorno agregada ({"DISABLE_OPENVINO": "1"}), que fuerza el modelo .pt
    original en vez del optimizado a OpenVINO -- deliberadamente un
    reintento de PROCESO completo, no un try/except interno, porque un
    fallo real de OpenVINO puede ser una caída nativa (segfault) que
    ningún try/except de Python atraparía."""
    with _lock:
        existing = _jobs.get(job_key)
        if existing and existing["status"] == "running":
            return False

        _jobs[job_key] = {
            "status": "running",
            "log_lines": [],
            "step_num": 0,
            "step_total": 0,
            "step_description": "Preparando...",
            "returncode": None,
        }

    thread = threading.Thread(target=_run_job, args=(job_key, command, env, retry_env), daemon=True)
    thread.start()
    return True


def _run_job_once(job_key: str, command: list, full_env: dict) -> int:
    """Corre `command` una vez, transmitiendo su salida en vivo al estado
    del job. Devuelve el código de salida."""
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
        text=True, bufsize=1, env=full_env,
    )
    for line in process.stdout:
        with _lock:
            job = _jobs[job_key]
            job["log_lines"].append(line)
            job["log_lines"] = job["log_lines"][-200:]  # no crecer sin límite

            step_match = _STEP_PATTERN.match(line.strip())
            if step_match:
                step_num, step_total, description = step_match.groups()
                job["step_num"] = int(step_num)
                job["step_total"] = int(step_total)
                job["step_description"] = description

    process.wait()
    return process.returncode


def _run_job(job_key: str, command: list, env: dict, retry_env: dict = None):
    import os
    full_env = {**os.environ, "PYTHONUNBUFFERED": "1"}
    if env:
        full_env.update(env)

    returncode = _run_job_once(job_key, command, full_env)

    if returncode != 0 and retry_env:
        with _lock:
            _jobs[job_key]["log_lines"].append(
                f"\nAVISO: el proceso falló (código {returncode}), posiblemente por el modelo "
                f"optimizado OpenVINO -- reintentando UNA vez con el modelo original (sin OpenVINO)...\n"
            )
        retry_full_env = {**full_env, **retry_env}
        returncode = _run_job_once(job_key, command, retry_full_env)

    with _lock:
        _jobs[job_key]["status"] = "done" if returncode == 0 else "error"
        _jobs[job_key]["returncode"] = returncode


def get_job(job_key: str) -> dict:
    """Devuelve una COPIA superficial del estado del job (o un estado
    'idle' por defecto si nunca se lanzó ninguno con esa clave) -- para
    que el llamador no pueda mutar el estado interno por accidente."""
    with _lock:
        job = _jobs.get(job_key)
        if job is None:
            return {"status": "idle", "log_lines": [], "step_num": 0, "step_total": 0,
                    "step_description": "", "returncode": None}
        return dict(job, log_lines=list(job["log_lines"]))


def clear_job(job_key: str):
    with _lock:
        _jobs.pop(job_key, None)
