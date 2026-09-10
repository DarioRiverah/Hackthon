"""
Comparación del patrón de manos (login alternativo, 4 poses en orden)
-- lógica pura de Python (sin Flask), reutilizada tanto por el registro
del patrón (ver routes/auth_routes.py: /settings/pattern) como por el
intento de login por patrón (/login/pattern).

El frontend (static/js/hand_pattern.js) ya entrega cada pose NORMALIZADA
(traslada usando la muñeca como origen, escala por la distancia
muñeca -> nudillo medio) antes de enviarla -- acá solo se mide qué tan
parecidas son dos secuencias ya normalizadas, no se repite esa
normalización en el backend.
"""

import numpy as np

POSE_COUNT = 4
LANDMARK_COUNT = 21

# Distancia euclidiana PROMEDIO por landmark (mismas unidades
# normalizadas que ya entrega el frontend, donde la distancia
# muñeca->nudillo medio vale 1) por debajo de la cual dos poses se
# consideran "la misma". Punto de partida razonable a ojo, no calibrado
# con capturas reales -- si en el uso real resulta muy estricto (el
# dueño legítimo no logra pasar) o muy laxo (cualquiera pasa), este es
# el único número que hace falta ajustar.
SIMILARITY_THRESHOLD = 0.15


def _pose_distance(pose_a, pose_b) -> float:
    """Distancia euclidiana promedio, landmark por landmark, entre dos
    poses de 21 puntos (x, y, z). Cualquier forma inesperada (poses
    incompletas, tipos raros) devuelve infinito -- nunca matchea."""
    try:
        a = np.asarray(pose_a, dtype=float)
        b = np.asarray(pose_b, dtype=float)
    except (TypeError, ValueError):
        return float("inf")
    if a.shape != (LANDMARK_COUNT, 3) or b.shape != (LANDMARK_COUNT, 3):
        return float("inf")
    return float(np.mean(np.linalg.norm(a - b, axis=1)))


def compare_pattern(candidate: list, stored: list) -> bool:
    """Compara las 4 poses EN ORDEN -- candidate[0] contra stored[0],
    ..., candidate[3] contra stored[3], nunca buscando la mejor
    combinación posible -- así que las 4 poses correctas en otro orden
    NO matchean. Devuelve True solo si las 4 distancias caen bajo
    SIMILARITY_THRESHOLD. Nunca lanza."""
    if not isinstance(candidate, list) or not isinstance(stored, list):
        return False
    if len(candidate) != POSE_COUNT or len(stored) != POSE_COUNT:
        return False
    return all(
        _pose_distance(pose_a, pose_b) <= SIMILARITY_THRESHOLD
        for pose_a, pose_b in zip(candidate, stored)
    )
