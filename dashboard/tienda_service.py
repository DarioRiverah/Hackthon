"""
Capa de agrupación TIENDA -> CÁMARAS -- ver docs/architecture.md
sección 32 para el razonamiento completo.

Hasta esta sección, cada "tienda" del sistema era en realidad una sola
cámara/video con sus propias zonas (config/zones_<id>.json,
data/output/*_<id>.csv, un registro opcional en history.db). Este
módulo agrega un registro NUEVO y LIVIANO (config/tiendas.json) que
agrupa varias de esas cámaras bajo una tienda, SIN renombrar ni mover
ningún archivo existente -- el identificador que antes se llamaba
"store_name" sigue siendo exactamente el mismo string, ahora llamado
"cámara" conceptualmente.

Organización deliberada: las funciones agregadoras (que combinan datos
de varias cámaras) viven ACÁ, en dashboard/, y no en pipeline/tiendas.py
como sugería una de las opciones -- reutilizan dashboard/store_service.py
y dashboard/video_utils.py (ambos ya viven en dashboard/), así que
ponerlas en pipeline/ hubiera invertido la dependencia normal
(pipeline/ nunca depende de dashboard/, solo al revés) sin ninguna
ganancia real.

100% pura en el sentido de "sin Streamlit/Flask" -- solo depende de
pandas y de los otros módulos puros del proyecto.
"""

import json
import os
import sys

import pandas as pd

import store_service
import video_utils

TIENDAS_PATH = "config/tiendas.json"


# =============================================================================
# Registro (config/tiendas.json) -- CRUD simple, sin lógica de negocio.
# =============================================================================

def _load_registry() -> dict:
    if not os.path.exists(TIENDAS_PATH):
        return {}
    with open(TIENDAS_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_registry(registry: dict) -> None:
    os.makedirs(os.path.dirname(TIENDAS_PATH), exist_ok=True)
    with open(TIENDAS_PATH, "w", encoding="utf-8") as f:
        json.dump(registry, f, indent=2, ensure_ascii=False)


def list_tiendas() -> list:
    """[{"id":, "label":, "n_camaras":}, ...] ordenado por label -- para
    poblar el selector de tienda del sidebar."""
    registry = _load_registry()
    items = [
        {"id": tid, "label": t.get("label", tid), "n_camaras": len(t.get("camaras", []))}
        for tid, t in registry.items()
    ]
    return sorted(items, key=lambda t: t["label"].lower())


def get_tienda(tienda_id: str) -> dict | None:
    return _load_registry().get(tienda_id)


def tienda_id_from_label(label: str) -> str:
    """El id de tienda es una versión "slug" simple del nombre que
    escribe el usuario -- minúsculas, espacios a guión bajo -- para que
    quede en un formato de archivo/URL predecible, igual que ya se
    espera de los identificadores de cámara existentes."""
    slug = label.strip().lower().replace(" ", "_")
    return "".join(c for c in slug if c.isalnum() or c == "_")


def create_tienda(label: str) -> str:
    """Crea una tienda nueva (sin cámaras todavía) y devuelve su id. Si
    ya existe una tienda con ese id, no la duplica -- simplemente
    devuelve el id existente (idempotente, para que un doble submit del
    formulario no rompa nada)."""
    tienda_id = tienda_id_from_label(label)
    if not tienda_id:
        raise ValueError("El nombre de la tienda no puede estar vacío.")

    registry = _load_registry()
    if tienda_id not in registry:
        registry[tienda_id] = {"label": label.strip(), "camaras": []}
        _save_registry(registry)
    return tienda_id


def find_tienda_de_camara(camara_id: str) -> str | None:
    """A qué tienda pertenece una cámara, si a alguna -- una cámara
    creada ANTES de esta funcionalidad (ej. merl_demo) simplemente no
    aparece en ningún registro todavía, y eso es válido: sigue
    funcionando por su cuenta (ver docs/architecture.md sección 32)."""
    registry = _load_registry()
    for tienda_id, t in registry.items():
        if camara_id in t.get("camaras", []):
            return tienda_id
    return None


def get_camaras_de_tienda(tienda_id: str) -> list:
    tienda = get_tienda(tienda_id)
    return list(tienda.get("camaras", [])) if tienda else []


def add_camara_a_tienda(tienda_id: str, camara_id: str) -> None:
    """Registra una cámara (ya existente en el filesystem o a punto de
    crearse vía el asistente) bajo una tienda. Lanza ValueError si esa
    cámara ya pertenece a OTRA tienda distinta -- una cámara es de una
    sola tienda a la vez. Es idempotente si ya pertenece a ESTA misma
    tienda (no la duplica en la lista)."""
    registry = _load_registry()
    if tienda_id not in registry:
        raise ValueError(f"La tienda '{tienda_id}' no existe.")

    dueña_actual = find_tienda_de_camara(camara_id)
    if dueña_actual is not None and dueña_actual != tienda_id:
        raise ValueError(
            f"La cámara '{camara_id}' ya pertenece a la tienda '{dueña_actual}' -- "
            "una cámara no puede estar en dos tiendas distintas."
        )

    if camara_id not in registry[tienda_id]["camaras"]:
        registry[tienda_id]["camaras"].append(camara_id)
        _save_registry(registry)


def remove_camara(camara_id: str) -> bool:
    """Quita una cámara del registro de su tienda (si pertenece a
    alguna) -- usado al eliminar la cámara completa (Parte 2 de gestión
    de datos). No borra la tienda aunque quede sin cámaras -- una
    tienda con 0 cámaras es un estado válido (ver tienda_empty.html).
    Devuelve True si la cámara estaba registrada en algún lado."""
    registry = _load_registry()
    changed = False
    for t in registry.values():
        if camara_id in t.get("camaras", []):
            t["camaras"].remove(camara_id)
            changed = True
    if changed:
        _save_registry(registry)
    return changed


def delete_tienda(tienda_id: str) -> bool:
    """Quita la entrada de la tienda del registro (config/tiendas.json).
    NO borra ninguna cámara -- eso es responsabilidad del llamador (ver
    dashboard/data_management_service.py:delete_tienda_completa()), que
    debe dejar la lista de cámaras de esta tienda vacía ANTES de llamar
    a esto (para no borrar el registro de una tienda que todavía tiene
    cámaras huérfanas colgando). Devuelve True si la tienda existía."""
    registry = _load_registry()
    if tienda_id not in registry:
        return False
    del registry[tienda_id]
    _save_registry(registry)
    return True


def get_camaras_sin_asignar() -> list:
    """Cámaras que YA EXISTEN en el sistema (tienen zonas y/o
    resultados, ver store_service.list_all_stores) pero todavía no
    están registradas bajo ninguna tienda -- para ofrecer "vincular una
    cámara existente" en vez de forzar a repetir el asistente completo."""
    asignadas = set()
    for t in _load_registry().values():
        asignadas.update(t.get("camaras", []))
    return [c for c in store_service.list_all_stores() if c not in asignadas]


def build_sidebar_context(tienda_id: str = None, camara_id: str = None) -> dict:
    """Contexto de tienda para el sidebar (templates/layout.html), usado
    por TODAS las rutas -- las de tienda (que ya conocen su tienda_id) y
    las de cámara existentes (results.html/setup.html), que no saben
    nada de tiendas.json pero igual necesitan mostrar "esta cámara
    pertenece a la tienda X" si corresponde. Si no se pasa tienda_id
    pero sí camara_id, se busca automáticamente."""
    if not tienda_id and camara_id:
        tienda_id = find_tienda_de_camara(camara_id)

    current_tienda = None
    tienda_camaras = []
    if tienda_id:
        t = get_tienda(tienda_id)
        if t:
            current_tienda = {"id": tienda_id, "label": t.get("label", tienda_id)}
            tienda_camaras = list(t.get("camaras", []))

    return {
        "all_tiendas": list_tiendas(),
        "current_tienda": current_tienda,
        "tienda_camaras": tienda_camaras,
    }


# =============================================================================
# Referencia de fecha/duración por cámara -- para la advertencia de
# comparabilidad (ver docs/architecture.md sección 32).
# =============================================================================

def get_camara_referencia(camara_id: str) -> dict:
    """Fecha y duración de referencia de una cámara, para mostrar en
    cualquier vista que combine varias cámaras.

    Duración: se intenta leer el video real (campo "video_reference" de
    config/zones_<camara>.json) SI ese archivo todavía existe en disco
    -- puede no existir si se borró después de procesar. Si no está
    disponible, se documenta explícitamente como tal (no se inventa un
    número).

    Fecha: el sistema actual no guarda una "fecha de grabación"
    explícita fuera del historial opcional (--record-history). Se usa
    la fecha de ÚLTIMA MODIFICACIÓN de data/output/zone_summary_<camara>.csv
    (cuándo se procesó por última vez) como aproximación honesta --
    documentada como tal, no presentada como si fuera la fecha real de
    grabación."""
    import datetime

    zones_path = f"config/zones_{camara_id}.json"
    summary_path = f"data/output/zone_summary_{camara_id}.csv"

    video_reference = None
    if os.path.exists(zones_path):
        with open(zones_path, "r", encoding="utf-8") as f:
            video_reference = json.load(f).get("video_reference")

    duracion_segundos = None
    duracion_fuente = "no_disponible"
    if video_reference and os.path.exists(video_reference):
        d = video_utils.get_video_duration(video_reference)
        if d > 0:
            duracion_segundos = d
            duracion_fuente = "video_real"

    fecha_referencia = None
    fecha_fuente = "no_disponible"
    if os.path.exists(summary_path):
        fecha_referencia = datetime.date.fromtimestamp(os.path.getmtime(summary_path)).isoformat()
        fecha_fuente = "fecha_de_procesamiento"  # aproximación, no la fecha real de grabación

    return {
        "camara_id": camara_id,
        "video_reference": video_reference,
        "duracion_segundos": duracion_segundos,
        "duracion_fuente": duracion_fuente,
        "fecha_referencia": fecha_referencia,
        "fecha_fuente": fecha_fuente,
    }


# =============================================================================
# Vistas agregadas (combinan cámaras de una tienda) -- construidas sobre
# store_service.load_store_data(), no reimplementan nada.
# =============================================================================

def get_zone_summary_combinado(tienda_id: str):
    """Une zone_summary de TODAS las cámaras de una tienda en un solo
    DataFrame, agregando columnas camara_origen/fecha_referencia/
    duracion_referencia. Devuelve (df_combinado, referencias) donde
    referencias es {camara_id: get_camara_referencia(camara_id)} para
    las cámaras que sí aportaron datos."""
    frames = []
    referencias = {}
    for camara_id in get_camaras_de_tienda(tienda_id):
        summary_df, _, _ = store_service.load_store_data(camara_id)
        if summary_df is None or summary_df.empty:
            continue
        ref = get_camara_referencia(camara_id)
        referencias[camara_id] = ref
        df = summary_df.copy()
        df["camara_origen"] = camara_id
        df["fecha_referencia"] = ref["fecha_referencia"]
        df["duracion_referencia"] = ref["duracion_segundos"]
        frames.append(df)

    combinado = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    return combinado, referencias


def get_interaction_summary_combinado(tienda_id: str):
    """Análogo a get_zone_summary_combinado() pero para interacción --
    las cámaras procesadas con --skip-hands simplemente no aportan
    filas acá (igual que hoy no las aportan a nivel de una sola
    cámara)."""
    frames = []
    for camara_id in get_camaras_de_tienda(tienda_id):
        _, _, interaction_df = store_service.load_store_data(camara_id)
        if interaction_df is None or interaction_df.empty:
            continue
        df = interaction_df.copy()
        df["camara_origen"] = camara_id
        frames.append(df)

    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def compute_tienda_kpis(tienda_id: str, zone_summary_combinado: pd.DataFrame,
                         interaction_summary_combinado: pd.DataFrame) -> dict:
    """KPIs agregados de tienda -- sumas simples sobre el combinado, más
    la identificación de la zona (Y cámara) con más tráfico entre TODAS
    las zonas de TODAS las cámaras."""
    camaras = get_camaras_de_tienda(tienda_id)
    total_zones = len(zone_summary_combinado)
    total_visits = int(zone_summary_combinado["total_visits"].sum()) if not zone_summary_combinado.empty else 0

    if interaction_summary_combinado is not None and not interaction_summary_combinado.empty:
        total_interactions = int(interaction_summary_combinado["total_interactions"].sum())
    else:
        total_interactions = None

    if not zone_summary_combinado.empty:
        top_row = zone_summary_combinado.loc[zone_summary_combinado["total_visits"].idxmax()]
        top_zone_label = str(top_row["zone_label"])
        top_zone_visits = int(top_row["total_visits"])
        top_zone_camara = str(top_row["camara_origen"])
    else:
        top_zone_label, top_zone_visits, top_zone_camara = "N/D", 0, None

    return {
        "n_camaras": len(camaras),
        "camaras_con_resultados": int(zone_summary_combinado["camara_origen"].nunique()) if not zone_summary_combinado.empty else 0,
        "total_zones": total_zones,
        "total_visits": total_visits,
        "total_interactions": total_interactions,
        "top_zone_label": top_zone_label,
        "top_zone_visits": top_zone_visits,
        "top_zone_camara": top_zone_camara,
    }


def get_tienda_state(tienda_id: str) -> dict:
    """Análogo a store_service.get_store_state() pero a nivel tienda --
    para los chips de estado del sidebar."""
    camaras = get_camaras_de_tienda(tienda_id)
    con_resultados = sum(1 for c in camaras if store_service.get_store_state(c)["has_results"])
    return {"n_camaras": len(camaras), "camaras_con_resultados": con_resultados}
