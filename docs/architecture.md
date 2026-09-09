# Arquitectura y decisiones técnicas

Este documento registra las decisiones técnicas importantes del
proyecto y su justificación, para que cualquiera (jurado, mentor
técnico, futuro colaborador) entienda no solo *qué* se construyó, sino
*por qué*.

## 1. Pipeline general

```
video (.mp4)
  │
  ├─► detect_and_track.py       (YOLO26 + ByteTrack) ──► tracks.csv
  │
  ├─► track_stitching.py        (corrige fragmentación de IDs)
  │
  ├─► calibrate_zones.py        (manual, una vez por cámara) ──► zones.json
  │
  ├─► zoning.py                 (dwell time, pasa/detiene) ──► zone_summary.csv
  │
  ├─► heatmap.py                (mapa de calor de flujo) ──► heatmap.png
  │
  ├─► detect_hand_positions.py  (YOLOv8-pose) ──► hands.csv
  │
  ├─► track_stitching.py        (mismo script, aplicado a manos)
  │
  ├─► interaction_events.py     (eventos de interacción) ──► interaction_summary.csv
  │
  └─► dashboard/app.py          (Flask: sube, procesa, visualiza)
```

`pipeline/run_pipeline.py` orquesta todos los pasos anteriores (excepto
calibración, que es manual) en un solo comando.

## 2. Por qué un modelo híbrido (YOLO26 + YOLOv8-pose)

Se evaluó YOLO26 (el modelo más reciente de Ultralytics, enero 2026)
como reemplazo completo de YOLOv8 en ambos módulos. Los resultados
medidos sobre el mismo video de prueba (MERL, vista cenital):

| Métrica | YOLOv8 | YOLO26 |
|---|---|---|
| Detecciones de cuerpo | 1987 | **3422** (+72%) |
| IDs de cuerpo antes de costura | 11 | **2** |
| Detecciones de mano | 3425 | 3084 (-10%) |
| IDs de mano antes de costura | 4 | 5 (peor) |
| Eventos de interacción finales | 16 | 20 (más ruido) |

**Decisión**: YOLO26 para detección de cuerpo (mejora clara y medible),
YOLOv8n-pose para detección de manos (mejor desempeño medido en este
caso específico). Esta decisión se tomó con evidencia empírica, no por
preferir el modelo "más nuevo" automáticamente.

## 3. Por qué se construyó costura de tracks propia (`track_stitching.py`)

YOLO + ByteTrack, tal cual, fragmentaba el tracking de una sola persona
en hasta 11 IDs distintos en el video de prueba de MERL. La causa raíz:
la vista cenital (cámara directamente desde arriba) es una perspectiva
atípica para la que los detectores estándar (entrenados
mayoritariamente con vistas laterales/frontales) tienen menor
confianza, causando pérdidas de detección momentáneas cada vez que la
persona interactúa con el estante.

La solución implementada reconecta tracks fragmentados basándose en
**velocidad físicamente plausible** (distancia recorrida / tiempo
transcurrido), no en umbrales de tiempo o distancia independientes.
Esto evita tanto la sub-fusión (no reconectar a la misma persona) como
la sobre-fusión (fusionar por error a personas distintas que coinciden
en tiempo/espacio) — validado explícitamente contra escenas de
multitud, donde velocidades "imposibles" (miles de px/s) identifican
correctamente candidatos de fusión erróneos.

## 4. Alcance honesto de la detección de interacción

El reto pedía idealmente distinguir "toma" (pickup) de "devolución"
(putback) de producto. Esto se evaluó y se decidió **no prometerlo**:

- Requiere reconocimiento de acciones especializado (flujo óptico,
  modelos entrenados específicamente para esto), no solo pose estática.
- El dataset académico RetailAction (Voxel51, 2025), con 21,000
  muestras de tiendas reales, reporta que incluso a esa escala la clase
  "put" está fuertemente subrepresentada y es difícil de distinguir de
  forma confiable — confirmando que esto es un problema de
  investigación activo, no un detalle de implementación.

Lo que el sistema sí entrega de forma confiable: cuándo y con qué
frecuencia/duración la mano entra a la zona del estante ("eventos de
interacción"), clasificados por intensidad (breve/media/prolongada)
como proxy interpretable, sin afirmar si hubo o no una transacción.

## 5. Por qué 100% local (sin nube)

- **Privacidad por diseño / Ley 1581**: mientras el video no salga del
  local, es mucho más simple sostener que no hay tratamiento de datos
  biométricos fuera de las instalaciones.
- **Costo**: subir video en vivo o por lotes de varias cámaras a la
  nube es costoso; procesar localmente y solo mover métricas agregadas
  (KB, no GB) reduce el costo de infraestructura a prácticamente cero.
- **Criterio de evaluación del reto**: "viabilidad edge (correr local)"
  está explícitamente listado como criterio.

Diseño futuro considerado (no implementado): procesamiento local +
sincronización de solo métricas agregadas a un panel en la nube, para
que el dueño pueda revisar desde su celular sin que el video salga
nunca del local.

## 6. Por qué motor de reglas en vez de un LLM para las recomendaciones

Se evaluó usar un modelo de lenguaje (LLM) para redactar las
recomendaciones de forma más natural. Se decidió usar un motor de
reglas en su lugar:

- **Gratuito y sin dependencias externas**: no requiere API de pago
  (se descartó Claude/GPT por esto) ni instalación adicional en cada
  computadora (se descartó Ollama local por requerir instalar el
  runtime + descargar un modelo de varios GB por máquina).
- **Cero riesgo en demo en vivo**: no hay latencia de red ni
  posibilidad de que un modelo externo falle a mitad de la
  presentación.
- **Refuerza el argumento de viabilidad edge**: el sistema completo
  corre sin ninguna dependencia de internet una vez instalado.

Roadmap futuro (no implementado): capa de LLM local vía Ollama como
mejora opcional de redacción, manteniendo el motor de reglas como
respaldo garantizado.

## 7. Escalabilidad: configuración por tienda, no por código

Cada tienda/cámara tiene su propio archivo `config/zones_<nombre>.json`
con las coordenadas de sus zonas, generado por calibración (manual, una
vez). Ningún script del pipeline tiene hardcodeado el nombre, layout, o
categoría de producto de una tienda específica — agregar una tienda
nueva es un proceso de calibración de minutos, no una modificación de
código.

## 8. Evaluación del módulo oficial `solutions.Heatmap` de Ultralytics

Como parte de la reestructuración del proyecto (incorporando recursos
sugeridos por la empresa), se evaluó reemplazar `pipeline/heatmap.py`
(implementación propia) por el módulo oficial `ultralytics.solutions.Heatmap`.

**Resultado: no se pudo hacer funcionar de forma confiable en nuestro
caso.** El módulo reportó "No tracks found" en el 100% de los frames
del video de prueba (MERL, vista cenital), incluso:
- Usando el mismo modelo (YOLO26) que detecta miles de posiciones
  correctamente en nuestro propio `detect_and_track.py` sobre el mismo
  video.
- Probando los tres trackers disponibles: `botsort.yaml` (default),
  `bytetrack.yaml` genérico, e incluso nuestra `custom_bytetrack.yaml`
  ya afinada específicamente para esta vista cenital.

**Conclusión**: `solutions.Heatmap` parece tener alguna capa interna
adicional de filtrado o invocación del modelo distinta a una llamada
directa `model.track()`, que no fue posible diagnosticar sin acceso al
código interno completo del módulo. Dado que ya contamos con una
implementación propia, transparente y validada (`heatmap.py`), se
decidió no invertir más tiempo depurando una dependencia de caja negra
cuando la alternativa propia ya funciona correctamente.

**Se mantiene `pipeline/heatmap.py` (implementación propia) como la
versión definitiva.** `pipeline/heatmap_ultralytics.py` se conserva en
el repositorio como evidencia del intento y la evaluación realizada,
no como parte del flujo de producción.

## 9. Validación cruzada contra smart-store-znibq (Roboflow)

Como parte de la incorporación de los datasets sugeridos por la
empresa, se validó nuestro pipeline (ya entrenado, sin ningún ajuste
adicional) contra el dataset `smart-store-znibq` (743 imágenes reales
de tienda, vista lateral/de esquina -- distinta a la vista cenital de
MERL con la que se construyó y afinó el resto del proyecto).

**Resultados sobre el split de test (23 imágenes):**

| Validación | Resultado |
|---|---|
| Detección de personas (precisión) | 78.3% |
| Detección de personas (recall) | 75.0% |
| Detección de personas (F1) | 76.6% |
| Plausibilidad de detección de interacción (muñeca dentro de zona anotada como interacción) | 96.4% (27/28) |

**Interpretación:**

- La detección de personas generaliza razonablemente bien a una vista
  completamente distinta a la usada durante el desarrollo, sin haber
  hecho ningún ajuste fino -- evidencia de que el sistema no está
  sobre-ajustado a la vista cenital de MERL.
- El resultado más relevante es la validación de interacción: en
  **96.4% de los casos** donde anotadores humanos marcaron una
  interacción de mano real, nuestra detección de muñeca (basada en
  pose) cayó dentro de esa misma zona. Esto es una validación
  **externa e independiente** del enfoque central del módulo de
  interacción (aproximación de mano a producto), en un dataset y
  contexto que el sistema nunca había visto antes.

Ver `pipeline/validate_smart_store.py` para la metodología completa
(IoU >= 0.5 para personas, punto-dentro-de-caja para interacción).

## 10. Calibración por canvas: evaluado y descartado

Se intentó ofrecer una calibración de zonas más fluida dentro del
navegador usando `streamlit-drawable-canvas` (arrastrar rectángulos,
sin el "parpadeo" del modo de clics). El resultado, tras dos rondas de
intentos:

**Intento 1**: `AttributeError: module 'streamlit.elements.image' has
no attribute 'image_to_url'`. Causa: la librería (archivada, sin
mantenimiento desde marzo 2025) busca una función en la ubicación
donde vivía en versiones viejas de Streamlit; Streamlit la movió de
módulo. Se corrigió con un parche que reinyectaba la función en su
ubicación original.

**Intento 2**: tras corregir lo anterior, apareció un segundo error
distinto (`AttributeError: 'int' object has no attribute 'width'`) --
Streamlit no solo movió la función, también le cambió la firma
internamente. Se corrigió reemplazando la función por una
implementación propia e independiente (codificar la imagen
directamente a un "data URL" base64, sin depender de ningún mecanismo
interno de Streamlit).

**Resultado final**: ya sin errores de Python, pero el canvas se
mostraba en blanco/negro -- la imagen de fondo no llegaba a
renderizarse en el navegador. Se probó además optimizar el tamaño de
la imagen (JPEG en vez de PNG, ~5x más liviano) sin confirmación clara
de que resolviera el problema.

**Decisión: se descarta el modo canvas para este MVP.** Dos rondas de
parcheo sobre una librería sin mantenimiento, cada una revelando un
problema distinto, es una señal clara de que se está persiguiendo un
objetivo móvil sin garantía de resolución. Se mantiene el modo
"clásico" (clic por clic, usando `streamlit-image-coordinates`, una
librería activamente mantenida) como el único método de calibración
en el navegador -- ya validado y funcional. El código del intento de
canvas se conserva en `dashboard/app.py`
(`render_zone_calibration_canvas`) por si se retoma en el futuro,
posiblemente separando el frontend de Streamlit hacia otra tecnología
con mejor soporte para este tipo de interacción.

## 11. Evaluación experimental: YOLOE-26 para detección de producto en mano

Se evaluó si YOLOE-26 (detección de vocabulario abierto, sin
entrenamiento) podía distinguir "mano con producto" de "mano vacía"
sobre frames de momentos de interacción ya confirmados (según nuestros
propios `interaction_events`), como posible ingrediente para estimar
pickup vs. putback sin necesidad de fine-tuning.

**Primer intento** (vocabulario abstracto: "product", "hand", "empty
hand"): 0 detecciones en los 3 frames probados, incluso en momentos
donde sabíamos con certeza que había una persona interactuando
activamente con el estante.

**Segundo intento** (vocabulario concreto: "bottle", "box", "bag",
"person", "hand", umbral de confianza más bajo): resultados mixtos,
revisados visualmente:
- 1 de 3: detección de "bottle" correctamente ubicada sobre la mano,
  pero con confianza extremadamente baja (0.10).
- 1 de 3: detección de "bottle" en una ubicación completamente ajena a
  la interacción (equipo de fondo, lejos de las manos) -- un falso
  positivo activo, no solo ausencia de detección.
- 1 de 3: sin ninguna detección de producto.

**Conclusión: no se cumple el criterio de plausibilidad necesario para
seguir invirtiendo tiempo en este enfoque.** Un falso positivo ubicado
con aparente confianza en un lugar incorrecto es más peligroso que no
detectar nada, ya que contaminaría cualquier lógica de negocio
construida encima (ej. comparar estado inicio/fin de un evento de
interacción). Se descarta este camino para el MVP. La detección de
interacción del sistema se mantiene en su alcance ya definido:
frecuencia y duración de interacción física, sin distinguir
pickup/putback (ver sección 4).

## 12. Validación formal contra las etiquetas reales de MERL

Además de la validación externa contra `smart-store-znibq`, se realizó
una validación formal del módulo de interacción contra las anotaciones
oficiales de MERL (`Labels_MERL_Shopping_Dataset.zip`, archivos
`.mat` con los timestamps reales de "Reach To Shelf", "Retract From
Shelf" y "Hand In Shelf" para cada video).

**Metodología**: las 3 sub-acciones de contacto físico se fusionan en
"episodios de contacto con el estante" consolidados (ya que nuestro
sistema mide un evento continuo por cada vez que la mano entra/sale de
la zona, no sub-acciones separadas), y se comparan contra nuestros
eventos detectados con dos métricas: emparejamiento estricto uno-a-uno
(IoU temporal) y cobertura temporal (más permisiva ante diferencias de
granularidad).

**Primer resultado (zona de calibración angosta)**: 12.5% precisión,
14.3% recall, 36.2% de cobertura temporal. Un resultado bajo que en un
primer momento pareció apuntar a una limitación del algoritmo de
detección de mano.

**Diagnóstico**: se notó que el heatmap de esta tienda mostraba dos
manchas de calor separadas (dos secciones del estante con
interacción), pero la zona calibrada solo cubría bien una de ellas
-- coincidiendo con el dato ya conocido de que 37.1% de las posiciones
de mano caían "fuera de cualquier zona". Esto significa que la
interacción real en la sección no cubierta era estructuralmente
invisible para el sistema, sin importar qué tan bien funcionara la
detección de mano en sí.

**Corrección**: se recalibró la zona para cubrir el ancho completo del
estante visible, y se volvió a correr el pipeline completo.

**Resultado final**: 72.7% precisión, 57.1% recall (emparejamiento
estricto), **89.4% de cobertura temporal**. La mejora confirma que la
mayor parte del problema inicial era de calibración de zona, no una
limitación del algoritmo de tracking de mano.

**Lección para el producto**: esto refuerza la importancia de una
buena calibración inicial por tienda -- una zona mal dimensionada
puede ocultar interacción real sin que ningún componente del pipeline
esté fallando. Es un argumento a favor de mejorar la guía visual
durante la calibración (ej. mostrando primero un heatmap preliminar
de referencia) como posible mejora futura.

Ver `pipeline/validate_merl_labels.py` para la metodología completa.

> **Actualización (ver sección 16)**: el 72.7%/57.1%/89.4% reportado
> arriba corresponde a una combinación específica de código y modelo de
> pose que ya no es reproducible con exactitud -- la comparación final
> de modelos de mano (sección 16) corrió esta misma validación, con la
> zona ya corregida de esta sección, y midió 20.0% precisión / 21.4%
> recall / 41.3% cobertura con la configuración final del pipeline
> (YOLOv8n-pose). La lección de calibración de esta sección sigue
> siendo válida y vigente; el número absoluto de calidad de interacción
> debe tomarse de la sección 16, no de aquí.

## 13. Aceleración por GPU (RTX 3050)

Todo el desarrollo y las validaciones de este documento se hicieron
originalmente en CPU (PyTorch instalado sin soporte CUDA por defecto,
un error de instalación común en Windows que pasó desapercibido varios
días). Al detectarlo y corregirlo:

| | CPU | GPU (RTX 3050) |
|---|---|---|
| Detección de cuerpo (un paso) | ~300-360s | ~108s (**~3x más rápido**) |
| Pipeline completo (9 pasos) | ~600-745s | **~219s (~2.7-3.4x más rápido)** |

**Contexto importante**: la mejora no es mayor (10x+, típico de GPU en
otros contextos) porque varias partes del pipeline (lectura/escritura
de video con OpenCV, construcción de CSVs) corren en CPU y no se
benefician de la GPU -- una vez acelerada la inferencia del modelo,
esas partes se convierten en el nuevo cuello de botella.

**Impacto en viabilidad de procesamiento por lotes** (relevante para la
pregunta de si el sistema es práctico para analizar la grabación de un
día completo durante la noche): con CPU, el ritmo de procesamiento era
~5x más lento que tiempo real (12 horas de grabación → ~60 horas de
procesamiento, inviable en una noche). Con GPU, el ritmo es ~1.7x
tiempo real (12 horas de grabación → ~20 horas de procesamiento) --
mucho más práctico, y con margen para acercarse aún más a caber en una
sola noche combinando esto con optimizaciones adicionales no
implementadas todavía (ej. frame-skipping, reducir resolución de
entrada).

**Nota sobre el reto**: el stack sugerido por la empresa (OpenVINO)
está orientado a hardware Intel, no a GPUs NVIDIA -- esta aceleración
es un beneficio adicional de desarrollo, no reemplaza la validación ya
hecha en CPU (que sigue siendo la que demuestra "viabilidad edge" sin
depender de hardware costoso). El sistema funciona correctamente en
ambos casos; la GPU es una mejora de velocidad opcional, no un
requisito.

## 14. Identificación efímera: por qué la narrativa es agregada, no "Cliente X"

La identificación de personas de este sistema (`track_id` -> `id_persona`,
vía `track_stitching.py`) se basa en heurísticas geométricas -- velocidad
implícita y consistencia de dirección sobre posiciones (x, y) -- no en
reconocimiento facial ni ningún dato biométrico, por diseño de privacidad
(ver `docs/privacy_checklist.md`).

Esto es confiable para una sola persona en el cuadro sin nadie más con
quien confundirla (el caso de validación con MERL usado en todo este
documento), pero **no está validado para escenas reales con varias
personas simultáneas**, donde un cruce de trayectorias podría fusionar o
dividir identidades por error -- el propio `track_stitching.py` ya
registra e imprime estos "casos ambiguos" cuando ocurren (ver sección 3).

**Decisión**: en ningún punto del dashboard se presenta un desglose por
persona (ej. "el Cliente 3 hizo esto"), porque implicaría una certeza de
identificación que no podemos garantizar en el caso general. En su lugar:

- `dashboard/storytelling.py` narra en términos de EVENTOS observados
  (detenciones, interacciones, momento en que ocurrieron), agregados por
  zona, nunca atribuidos a un individuo.
- `pipeline/render_stitched_preview.py` y `pipeline/spaghetti_diagram.py`
  (el video de verificación de tracking y el diagrama de trayectorias)
  etiquetan cada `id_persona` con una letra genérica (A, B, C...) sobre
  la paleta categórica "Tableau 10", en vez del número de `id_persona` o
  la palabra "Persona X". El propósito explícito de esas letras es dejar
  claro visualmente si la costura de tracking mantiene el mismo color en
  la misma persona (verificación de continuidad), no ofrecer una
  identificación de cliente.

Esto es el mismo principio que ya aplican las métricas agregadas por zona
en el resto del dashboard: se comunica lo que el sistema puede sostener
con confianza (patrones de comportamiento agregados), no más.

## 15. Filtro de ruido de un solo cuadro (`--min-detections`)

Durante la comparación de modelos de cuerpo (ver sección 16), se detectó
que una corrida de `detect_and_track.py` + `track_stitching.py` producía
un `id_persona` adicional respaldado por una única detección aislada de
un solo cuadro (un "parpadeo" del detector, sin relación temporal ni
espacial razonable con el resto del video) -- inflando artificialmente el
conteo de personas y contaminando cualquier comparación que usara el
número de IDs finales como métrica.

**Causa raíz**: `track_stitching.py` solo fusiona un track con otro si
encuentra un candidato físicamente plausible (gap de tiempo + velocidad
implícita dentro de los umbrales). Un track de un solo cuadro, sin ningún
candidato razonable con quien unirse, simplemente queda solo -- y antes
de este fix, se conservaba como si fuera una persona real.

**Corrección**: se agregó el parámetro `--min-detections` (default: `2`)
a `track_stitching.py`. Después de la costura, cualquier `id_persona`
final que quede con menos detecciones que este umbral se descarta como
ruido, no como una persona real (`filter_isolated_noise`). Usar
`--min-detections 0` desactiva el filtro si algún caso de uso lo
requiere explícitamente.

**Lección para el producto**: al comparar modelos (o al interpretar
conteos de personas en general), un solo cuadro aislado no es evidencia
suficiente de una visita real -- este filtro asegura que las
comparaciones y los conteos reportados reflejen personas que el sistema
efectivamente siguió por al menos un intervalo de tiempo, no ruido de
detección de un solo instante.

## 16. Decisión final de modelos: comparación limpia (YOLO26n vs. YOLO26s, YOLOv8n-pose vs. YOLO26s-pose)

Las secciones 2 y 12 documentan comparaciones de modelos hechas en
distintos momentos del proyecto. Al hacer la revisión final se detectó
que ninguna de las dos podía tomarse como la última palabra:

- La comparación de cuerpo de la sección 2 no usaba todavía el filtro
  `--min-detections` (sección 15) -- un candidato podía verse
  artificialmente peor por culpa de un id_persona espurio de un solo
  cuadro, no por una diferencia real de calidad del modelo.
- La comparación de manos nunca se completó de forma limpia: quedó
  mezclada con calibraciones de zona distintas a mitad de camino, y el
  código en producción (`POSE_MODEL_NAME`) había quedado apuntando a
  `yolo26s-pose.pt`, en desacuerdo con lo que este mismo documento y el
  README llevaban meses afirmando (`YOLOv8n-pose`).

Se rehizo la comparación completa desde cero: se limpiaron
`data/processed/` y `data/output/`, y se corrió cada combinación de
modelo sobre `data/raw/1_2_crop.mp4` contra la misma
`config/zones_merl_demo.json` (la zona ya corregida de la sección 12),
con los mismos parámetros de costura para cada rol (cuerpo:
`--max-gap-seconds 15 --max-speed-px-per-s 500`; mano:
`--max-gap-seconds 60 --max-speed-px-per-s 200`, ambos con
`--min-detections 2`) y el mismo `--debounce-seconds 0.5`.

**Cuerpo -- YOLO26n vs. YOLO26s** (detección + costura, sin manos):

| Métrica | YOLO26n | YOLO26s |
|---|---|---|
| Detecciones | **3422** | 3406 |
| IDs antes de costura | **2** | 4 (incluye 1 id de un solo cuadro, descartado por el filtro de la sección 15) |
| IDs finales (después de costura) | 1 | 1 |

Con el filtro de ruido ya activo, ambos modelos terminan en el mismo
resultado final (1 persona, correcto para este clip), pero YOLO26n
detecta más posiciones con menos fragmentación cruda -- y al ser el
modelo más liviano de los dos, también favorece la viabilidad edge del
proyecto. **Se confirma YOLO26n para detección de cuerpo.**

**Manos -- YOLOv8n-pose vs. YOLO26s-pose** (detección + costura +
`interaction_events.py`, validado contra `data/raw/1_2_label.mat` con
`validate_merl_labels.py --fps 30`):

| Métrica | YOLOv8n-pose | YOLO26s-pose |
|---|---|---|
| Detecciones de muñeca | 3425 | 3447 |
| Frames sin muñeca confiable | **3** | 20 |
| IDs antes de costura | 4 | 2 |
| Eventos de interacción finales | 15 | 20 |
| Precisión (vs. MERL) | **20.0%** | 10.0% |
| Recall (vs. MERL) | **21.4%** | 14.3% |
| F1 (vs. MERL) | **20.7%** | 11.8% |
| Cobertura temporal (vs. MERL) | 41.3% | 41.9% (empate) |

YOLO26s-pose fragmenta menos el track (2 IDs crudos vs. 4) y detecta
ligeramente más posiciones en bruto, pero sus keypoints de muñeca son
menos confiables cuadro a cuadro (20 frames sin muñeca válida contra
solo 3) y eso se traduce en eventos de interacción con peor
correspondencia temporal contra las etiquetas reales: duplica casi la
tasa de falsos positivos y pierde recall frente a YOLOv8n-pose. La única
métrica donde empatan es la cobertura temporal (la más permisiva de las
dos). **Se confirma YOLOv8n-pose para detección de manos.**

Nota honesta sobre los números absolutos: comparados con el 72.7%
precisión / 57.1% recall / 89.4% cobertura reportados en la sección 12,
estos resultados (20.0% / 21.4% / 41.3%) son notablemente más bajos.
Dado que la sección 12 documenta un proceso de calibración de zona que
se corrigió DESPUÉS de obtener ese número, y que la comparación de manos
nunca se completó limpiamente (como se explica arriba), no hay forma de
reconstruir con certeza qué combinación exacta de código/calibración
produjo el 72.7% original -- es probable que reflejara una versión
distinta del pipeline o una calibración ligeramente distinta a la
`zones_merl_demo.json` actual. La comparación de esta sección es, en
cambio, totalmente reproducible: mismo código, misma zona, mismo
video, ambos modelos evaluados bajo condiciones idénticas. Se prioriza
esta evidencia limpia por encima del número histórico de la sección 12
para la decisión de modelo (que es lo que esta sección decide), aunque
el número absoluto de calidad del sistema de interacción debería
tratarse como pendiente de una nueva validación formal de punta a punta
con la configuración final, no como algo ya cerrado en 72.7%.

**Configuración final (fijada en el código):**

```
pipeline/detect_and_track.py:      MODEL_NAME = "yolo26n.pt"
pipeline/detect_hand_positions.py: POSE_MODEL_NAME = "yolov8n-pose.pt"
```

## 17. Eliminación del heatmap "combinado" del flujo activo

`pipeline/heatmap.py` incluía un tercer modo (`--mode combinado`) que
superponía las dos señales en una sola imagen: color de fondo
(azul->rojo) para tráfico/permanencia corporal, y un contorno blanco
para marcar la zona de mayor interacción de mano (ver
`render_combined_heatmap`). `pipeline/run_pipeline.py` lo corría como
paso 12/12 de la corrida completa.

**Decisión: se quita ese paso del orquestador.** El heatmap de flujo y
el de interacción, cada uno visto por separado (ya generados como
pasos independientes del mismo pipeline), comunican la misma
información con más claridad que la versión combinada -- superponer
ambas señales en una sola imagen no aportaba un dato nuevo, solo
mezclaba dos lecturas independientes de una forma menos legible que
verlas una a la vez. Simplifica además la corrida completa (un paso
menos) sin perder ninguna capacidad de análisis: quien quiera comparar
ambas señales puede alternar entre las dos pestañas de heatmap ya
disponibles en el dashboard.

`pipeline/heatmap.py` conserva `render_combined_heatmap` y el modo
`--mode combinado` en el código -- sigue siendo invocable manualmente
por línea de comandos -- pero ya no forma parte del flujo de
producción ni se muestra en `dashboard/app.py`.

## 18. Diagrama de espagueti agregado: misma razón que la sección 14

El diagrama de espagueti (`pipeline/spaghetti_diagram.py`) dibujaba
originalmente una línea de color distinto por cada `id_persona`, con
su propia etiqueta ("Trayectoria A", "B", "C"...) -- igual que el
video de verificación de tracking, pero con un problema de fondo
distinto: mientras que en el video de verificación esas letras existen
explícitamente para confirmar continuidad de tracking (ver sección
14), en el diagrama de espagueti no cumplían ese propósito -- ahí solo
servían para "distinguir visualmente" trayectorias, lo cual termina
comunicando, aunque no se use la palabra "persona", el mismo tipo de
desglose individual que la sección 14 ya decidió no ofrecer: la
identificación de personas (`id_persona`, vía `track_stitching.py`) no
está validada para escenas con varias personas simultáneas, así que
presentar "la trayectoria de tal persona" como un dato distinguible es
una certeza que no podemos garantizar en el caso general.

**Decisión (aplicando el mismo principio de la sección 14 a esta
visualización): el diagrama de espagueti ahora dibuja todas las
trayectorias detectadas en un único color, con transparencia baja por
trayectoria individual (overlay + `cv2.addWeighted`, ~0.30-0.40 de
opacidad por línea).** El efecto buscado -- y confirmado visualmente
con datos sintéticos de varias personas con recorridos parecidos --
es que donde varias trayectorias coinciden, la superposición de líneas
semitransparentes se ve más intensa/sólida, revelando la tendencia de
circulación real del video sin necesidad de distinguir quién es quién.
Los marcadores de inicio (verde) y fin (rojo) se conservan porque
aportan valor visual (de dónde entra y sale la gente en general), pero
ya no se etiquetan con una letra por persona.

Esto es consistente con el principio de la sección 14: comunicar lo
que el sistema puede sostener con confianza (un patrón agregado de
circulación), no una certeza de identificación individual que no
tenemos forma de garantizar en escenas con varias personas.

## 19. Bug: los videos de verificación no reproducían en el navegador

**Síntoma reportado**: al intentar reproducir
`tracked_preview_corregido_*.mp4` / `hands_preview_corregido_*.mp4`
desde el dashboard (`st.video()`), el navegador mostraba "No se ha
encontrado ningún video que tenga un formato y tipo MIME compatibles".

**Diagnóstico (confirmado, no asumido)**: se inspeccionó el códec real
del archivo generado (no el que el código *pedía*, sino el que
`cv2.VideoWriter` terminó escribiendo). `cv2.CAP_PROP_FOURCC` reportó
`FMP4` para un archivo que el código pedía como `mp4v` -- ambos son en
la práctica MPEG-4 Part 2 (vía el encoder nativo de FFmpeg), no H.264.
Los navegadores modernos (Chrome, Firefox, Edge) esperan H.264/AVC1
dentro de un contenedor `.mp4` y no traen decodificador para MPEG-4
Part 2 -- de ahí el error exacto reportado.

**Antes de cambiar el códec, se verificó qué opciones realmente
funcionan en esta instalación específica de OpenCV/FFmpeg** (no se
asumió que `avc1` funcionaría solo porque es la recomendación
estándar):

- `avc1`/`h264`/`H264`/`X264`: todos fallan en este entorno con
  `Failed to load OpenH264 library: openh264-2.5.0-win64.dll` seguido
  de `Unable to create encoder` / `Failed to initialize VideoWriter`.
  Causa: OpenH264 es una librería con licencia de Cisco que los
  builds prebuilt de OpenCV-Python (los que trae `requirements.txt`)
  no incluyen por defecto -- hay que descargarla aparte. A pesar del
  error, `cv2.VideoWriter` no lanza una excepción ni deja
  `isOpened()` en `False` (falso positivo), y el archivo resultante
  queda con metadata inconsistente (la caja `stsd` del `.mp4` sí dice
  `avc1`, pero el contenido de `mdat` no es un bitstream H.264 válido)
  -- es decir, intentar forzar `avc1` aquí no solo no soluciona el
  problema, sino que produce un archivo roto de una forma más difícil
  de diagnosticar que el original.
- `vp80` (VP8) y `vp09` (VP9), en contenedor `.webm`: funcionan sin
  ningún error, con el codec real (`V_VP8`/`V_VP9`) confirmado dentro
  del contenedor WebM (formato Matroska/EBML). `libvpx` no tiene la
  misma restricción de licencia que el H.264 y viene incluido en el
  build de FFmpeg que usa OpenCV-Python.

**Decisión**: se cambió el códec de salida a **VP8 en contenedor
`.webm`** (`cv2.VideoWriter_fourcc(*"VP80")`) en los tres lugares del
pipeline que generan video con `cv2.VideoWriter` para consumo humano:
`pipeline/render_stitched_preview.py` (los videos que sí se muestran
en el dashboard), y también `pipeline/detect_and_track.py` y
`pipeline/detect_hand_positions.py` (generan su propio preview
"crudo", no mostrado actualmente en el dashboard, pero con el mismo
problema potencial si se llegara a exponer). WebM/VP8 es un formato
soportado nativamente por todos los navegadores modernos, así que no
hace falta ningún paso adicional de re-codificación con `ffmpeg` --de
hecho, `ffmpeg`/`ffprobe` no están instalados en este entorno de
desarrollo, lo cual habría hecho de esa alternativa un paso extra a
instalar sin necesidad, dado que VP8 ya resuelve el problema con lo
que el proyecto ya tiene instalado.

**Verificación de que quedó resuelto**: se regeneraron los videos de
verificación reales del pipeline (`tracked_preview_corregido_*.webm`,
`hands_preview_corregido_*.webm` para los clips de prueba de MERL) y
se confirmó -- inspeccionando la caja de codec dentro del contenedor
WebM, igual que en el diagnóstico -- que el códec de salida real es
`V_VP8`, no una etiqueta inconsistente como ocurría con el intento de
`avc1`.

**Nota para el futuro**: si se necesitara H.264 real más adelante
(por ejemplo, por compatibilidad con algún reproductor que no soporte
WebM), la vía correcta sería descargar `openh264-2.5.0-win64.dll`
desde el repositorio oficial de Cisco y colocarla donde el binario de
OpenCV la pueda cargar, o instalar `ffmpeg` en el sistema y
re-codificar como paso posterior opcional (condicional a que
`ffmpeg` esté en el PATH, sin romper el pipeline si no lo está). No se
implementó ninguna de las dos porque VP8/WebM ya resuelve el problema
reportado sin depender de nada adicional.

## 20. Asistente de IA opcional para redactar recomendaciones (Groq)

> **[OBSOLETO -- retirado]** Esta funcionalidad (y su continuación en la
> sección 21) fue eliminada por completo del proyecto. Ver sección 38
> para la razón del retiro y el detalle de qué se quitó. Esta sección se
> conserva sin editar, como registro histórico de la decisión original.

Se agregó `dashboard/ai_advisor.py`: una sección **100% opcional** en la
pestaña "Recomendaciones" que redacta en un tono más natural/conversacional
las mismas recomendaciones que el motor de reglas ya genera, usando la API
de Groq (gratuita, aportada por cada usuario).

**Por qué esto NO contradice la decisión de la sección 6**: aquella
sección rechazó un LLM como reemplazo del motor de reglas -- ya sea de
pago (Claude/GPT, costo y riesgo de disponibilidad en demo) o local
(Ollama, carga de instalación por máquina). Esta funcionalidad es
distinta en un punto esencial: **el motor de reglas (`ai_insights.py`)
sigue siendo la única fuente de los datos y del diagnóstico de
negocio** -- el LLM no calcula nada, solo redacta en prosa los mismos
hechos que ya se calcularon. Es además estrictamente opcional y
aislado: si nadie ingresa una API key, la pestaña se comporta
exactamente igual que antes de este cambio, sin ninguna dependencia de
red ni de una cuenta externa para el camino principal del producto. El
argumento de viabilidad edge de la sección 5 sigue intacto para todo lo
demás del sistema; esto es un extra de redacción, no una pieza
necesaria del análisis.

**Cómo se evita que el modelo invente datos**: el mensaje de sistema
(`SYSTEM_PROMPT` en `ai_advisor.py`) instruye explícitamente al modelo a
no agregar ninguna cifra, porcentaje o afirmación que no esté en los
datos entregados, y el mensaje de usuario le pasa como contexto
estructurado exactamente los mismos datos ya calculados (resumen
ejecutivo, métricas por zona, interacción por zona, y el
diagnóstico/sugerencia que el motor de reglas ya redactó por zona) --
nunca los CSV crudos completos ni ningún dato que el motor de reglas no
haya ya procesado. Esto reduce el riesgo de invención a "parafrasear mal
un hecho ya dado", no "inventar un hecho nuevo" -- un modelo de lenguaje
no puede garantizarse 100% libre de error de paráfrasis, por lo que esta
sección se presenta como complemento de redacción, nunca como
reemplazo del motor de reglas (que sigue mostrándose siempre, arriba,
sin depender de esto).

**Manejo de la API key**: la ingresa cada usuario en un campo de tipo
contraseña (`st.text_input(..., type="password")`), vive únicamente en
`st.session_state` de esa sesión del navegador, y nunca se escribe a
ningún archivo del proyecto, variable de entorno, ni se imprime en
ningún log o mensaje de error. No hay ninguna key del proyecto
hardcodeada en ningún lado.

**Endpoint y modelo usados** (verificados contra la documentación
oficial vigente antes de implementar, no asumidos de memoria):

```
POST https://api.groq.com/openai/v1/chat/completions
Authorization: Bearer <API key del usuario>
model: "llama-3.1-8b-instant"
```

Es el endpoint de chat completions de Groq, compatible con el formato
de OpenAI. Se eligió `llama-3.1-8b-instant` por ser el modelo más
liviano/económico del catálogo (más que suficiente para redactar un
párrafo corto) y el que tiene los límites de uso más generosos en la
capa gratuita (14,400 solicitudes/día al momento de verificarlo) -- no
el modelo más grande/capaz disponible, ya que esta tarea no lo requiere.

> **Actualización**: el modelo en producción (`GROQ_MODEL` en
> `dashboard/ai_advisor.py`) pasó después a `openai/gpt-oss-20b` -- el
> endpoint y el resto del diseño de esta sección no cambiaron, solo el
> identificador del modelo. Ver sección 21 para las mejoras posteriores
> (guardado encriptado de la key, formato de respuesta estructurado) y
> para las pruebas hechas con una API key real ya funcionando, que
> resuelven el pendiente que quedaba abierto abajo.

**Manejo de errores**: cualquier fallo (key inválida, límite de
velocidad excedido, error de red, timeout, respuesta en formato
inesperado) se captura explícitamente en `call_groq()` y se traduce a
un mensaje en lenguaje llano vía `st.error()` -- nunca se deja escapar
una excepción sin manejar. El resto de la pestaña (motor de reglas,
botón de PDF, tabla de métricas) no depende de esta sección y sigue
funcionando sin importar qué pase con la llamada a Groq.

**Verificación realizada**: no fue posible crear una cuenta real de
Groq desde este entorno de desarrollo (requiere un flujo de registro
en navegador, fuera del alcance de este entorno no interactivo). Se
verificó en su lugar, con pruebas automatizadas (`streamlit.testing.v1.AppTest`):
(1) que sin ninguna API key ingresada, el botón queda deshabilitado y
el resto de la pestaña se ve idéntico a como se veía antes de este
cambio; y (2) el manejo de errores con una key inválida A PROPÓSITO,
haciendo una llamada real (sin simular) contra `api.groq.com` -- Groq
respondió `401 Invalid API Key` como se esperaba, y el dashboard lo
tradujo correctamente al mensaje en español sin ninguna excepción.
**Queda pendiente que el usuario confirme una generación exitosa con
una API key real y válida propia** -- eso no se pudo probar desde aquí.

## 21. Asistente de IA: guardado local encriptado de la key + respuesta estructurada

> **[OBSOLETO -- retirado]** Ver la nota al inicio de la sección 20 y la
> sección 38: toda la funcionalidad del asistente de IA (incluyendo el
> guardado encriptado de la key descrito aquí) fue eliminada del
> proyecto. Esta sección se conserva sin editar, como registro histórico
> de la decisión original.

Dos mejoras sobre la funcionalidad de la sección 20, ambas preservando
sin excepción su regla de diseño central: el motor de reglas
(`ai_insights.py`) sigue siendo la única fuente de cifras y diagnóstico
de negocio; el LLM solo redacta.

**Guardado local encriptado de la API key.** Antes, la key vivía
únicamente en `st.session_state` (se perdía al cerrar el navegador).
Ahora el usuario puede, opcionalmente, guardarla en disco para no tener
que volver a pegarla cada vez:

- Se usa `cryptography.fernet.Fernet` (encriptación simétrica estándar).
  La primera vez que se guarda una key, se genera una clave de
  encriptación local aleatoria (`.secrets/encryption.key`) y se usa para
  encriptar la API key, guardando el resultado en
  `.secrets/groq_api_key.enc`. Ninguno de los dos archivos contiene la
  key en texto plano -- se verificó abriendo `groq_api_key.enc` como
  bytes crudos y confirmando que ni contiene la cadena original ni es
  decodificable como UTF-8 igual al original (ver la verificación más
  abajo).
- Al cargar el dashboard, si ambos archivos existen, la key se
  desencripta automáticamente hacia `st.session_state` sin pedírsela de
  nuevo al usuario -- pero nunca se vuelve a mostrar en un campo de
  texto ni se imprime en ningún lado. La interfaz solo muestra un
  indicador ("🔑 Clave de API guardada") con botones para cambiarla o
  eliminarla, nunca el valor real.
- Si los archivos existen pero no se pueden desencriptar (corrupción, o
  se copió el proyecto a otra máquina sin llevarse `.secrets/` completa
  -- por ejemplo, solo el `.enc` sin su `encryption.key`), la carga
  falla de forma controlada: se muestra un aviso ("no se pudo leer la
  clave guardada, ingrésala de nuevo") y el dashboard cae de vuelta al
  estado "sin key", sin ninguna excepción.
- `.secrets/` se agrega automáticamente a `.gitignore` (creándolo si no
  existía) la primera vez que se guarda una key, y la propia carpeta
  incluye un archivo `NO_COMPARTIR.txt` con la misma advertencia.

**Límite de seguridad real, sin adornos (para no sobre-prometer):**
esto protege la key de una **exposición accidental** -- que alguien vea
el campo en pantalla, que el proyecto se copie/comprima/respalde para
compartirlo con alguien más y la key viaje sin querer dentro. **NO**
protege contra alguien con **acceso completo a esta misma
computadora**: la clave de encriptación (`encryption.key`) vive en el
mismo lugar que el archivo que desbloquea (`groq_api_key.enc`) -- quien
pueda leer un archivo puede leer el otro. Esto es equivalente al nivel
de protección de "at rest sin segundo factor externo" (ej. sin
depender del llavero/gestor de credenciales del sistema operativo, que
sería un paso más seguro pero también más complejo y menos portable
entre Windows/Mac/Linux). **La carpeta `.secrets/` nunca debe copiarse,
respaldarse ni compartirse junto con el resto del proyecto** -- ni
siquiera con alguien de confianza, porque compartir el proyecto
completo compartiría también la key.

**Respuesta estructurada en vez de prosa libre.** El `SYSTEM_PROMPT` se
actualizó para pedir un formato fijo en Markdown -- una frase de
apertura, una viñeta por cada zona presente en los datos entregados, y
una línea de cierre con la sugerencia más importante a considerar
primero -- en vez de "un par de párrafos cortos" sin estructura. La
regla de no inventar cifras se mantiene exactamente igual, solo se le
agregó la instrucción de formato; no se relajó ninguna restricción
existente. Se subió `max_completion_tokens` de 400 a 600, porque el
formato con viñetas (una por zona) puede necesitar más espacio que un
párrafo corrido, especialmente con 3+ zonas.

**Verificación realizada:**

- Guardado/recuperación/cambio/eliminación de la key: probado de punta
  a punta con `streamlit.testing.v1.AppTest`, incluyendo guardar una key
  de prueba y confirmar que `groq_api_key.enc` no es legible como texto
  plano (empieza con el prefijo estándar de un token Fernet, `gAAAAA...`,
  y no es decodificable como UTF-8 igual a la key original); simular el
  "reinicio" de la app con una sesión nueva y confirmar que la key se
  recupera automáticamente sin pedirla de nuevo; usar "Cambiar clave" y
  confirmar que el campo aparece vacío (nunca pre-llenado) y que la key
  vieja queda reemplazada; usar "Eliminar clave" y confirmar que ambos
  archivos se borran y la interfaz vuelve al estado inicial; y simular
  un archivo `.enc` corrupto, confirmando que el dashboard no truena y
  cae de vuelta al estado "sin key" con un aviso claro.
- Manejo de errores: repetido el mismo camino que en la sección 20 (key
  inválida a propósito, llamada real -- no simulada -- contra
  `api.groq.com`), ahora pasando por el flujo de guardado nuevo.
- Formato estructurado con una API key real: [PENDIENTE DE COMPLETAR --
  ver el resumen de la tarea correspondiente para el estado exacto de
  esta verificación].

## 22. Rediseño visual y estructural completo del dashboard

Se rehizo por completo la identidad visual del dashboard (reemplazando,
sin mezclar, el sistema anterior -- paleta Ember/Frost, tipografía Space
Grotesk + Inter, documentado hasta ahora solo en los docstrings de
`dashboard/style.py`/`dashboard/app.py`, nunca en una sección propia de
este documento) y se reorganizó la estructura de `render_results_view()`
en `dashboard/app.py`
siguiendo el patrón de un panel de monitoreo/analítica retail (KPIs
arriba, paneles con borde por visualización, grid de 2 columnas donde
el contenido lo permite).

**Por qué un rediseño completo y no una extensión**: el sistema anterior
ya era coherente en sí mismo, pero se reemplazó a pedido explícito por
una nueva dirección de marca (paleta e identidad distintas) -- no hubo
un problema de fondo con el sistema anterior, es una decisión de
producto de renovar la imagen visual.

**Concepto e implementación técnica**: el CSS ahora vive en un archivo
independiente, `dashboard/assets/theme.css` (organizado en secciones:
variables, tipografía, botones, inputs, tarjetas/paneles, pestañas,
sidebar, expanders, métricas, alertas, dataframe, file uploader,
componentes propios), no como un string de Python embebido.
`dashboard/style.py` se redujo a leer ese archivo e inyectarlo, más las
dos funciones que generan HTML dinámico (`status_chip`,
`render_step_status`), que referencian las variables CSS vía `var(--color-x)`
en vez de repetir valores hex en Python. `layout_view.py` (matplotlib) y
`report_generator.py` (reportlab) siguen importando los mismos colores
como constantes de Python desde `style.py`, porque ninguna de esas dos
librerías puede consumir variables CSS -- es la misma paleta duplicada
por necesidad técnica, no dos fuentes de verdad distintas.

**Paleta final**:

| Token | Valor | Uso |
|---|---|---|
| `--color-surface` | `#EEF1F4` | Fondo de página |
| `--color-panel` | `#FFFFFF` | Fondo de tarjetas/paneles |
| `--color-surface-alt` | `#E3E8ED` | Superficie de expanders "técnicos" |
| `--color-ink` | `#1A2333` | Texto principal |
| `--color-ink-muted` | `#5B6472` | Texto secundario |
| `--color-ink-on-accent` | `#000000` | Texto sobre fondos saturados (ver contraste abajo) |
| `--color-line` | `#D7DEE5` | Bordes/divisores (deliberadamente sutil) |
| `--color-hot` / `--color-hot-text` | `#E8543E` / `#B93C27` | "Zona caliente" -- fondo / variante segura como texto |
| `--color-cold` / `--color-cold-text` | `#0EA5A0` / `#0A736F` | "Zona fría" -- fondo / variante segura como texto |
| `--color-zone-paso`, `--color-zone-nicho`, `--color-zone-none` | `#E8A23E`, `#C9793A`, `#C7CDD3` | Estados intermedios del semáforo, sin equivalente de marca (ver más abajo) |
| `--color-info/success/warning/error` | `#2E72C7` / `#157A52` / `#9C5F0C` / `#C93B4E` | Alertas semánticas, definidas para HTML propio (Streamlit no permite recolorear su `st.info/success/warning/error` nativo) |

Tipografía: **Manrope** (encabezados/paneles) + **IBM Plex Sans** (cuerpo
y datos).

**Por qué existen `--color-hot-text` y `--color-cold-text` además de
`--color-hot`/`--color-cold`**: `--color-hot` y `--color-cold` son
valores fijos pedidos explícitamente para el rediseño y no se
modificaron. Pero al verificar contraste (ver sección siguiente), se
encontró que NINGUNO de los dos funciona bien como color de TEXTO sobre
fondos claros (`--color-hot` como texto da 3.64:1, `--color-hot` de
fondo con texto blanco da igual 3.64:1) -- son colores de saturación
media, pensados para rellenos/fondos, no para texto pequeño. Se
definieron variantes más oscuras de la misma familia de color
específicamente para los pocos lugares donde el acento aparece como
texto (pestaña activa, hover de botones/expanders) en vez de
renunciar al acento o forzar un contraste insuficiente.

**Por qué "Paso" e "Interés de Nicho" NO se unificaron a hot/cold**: son
los dos estados intermedios del semáforo de 4 categorías (alguna señal
positiva, pero no las dos a la vez). Forzarlos a variantes de hot/cold
habría reducido las 4 categorías del semáforo a solo 2 tonos
distinguibles, rompiendo su lectura rápida -- se mantienen como colores
propios, coherentes en temperatura (ambos cálidos) pero visualmente
distintos de "Caliente".

### Verificación de contraste WCAG (obligatoria, Fase 4)

Se calculó el contraste real (ratio WCAG, fórmula de luminancia
relativa) de TODA combinación texto-sobre-fondo usada en el proyecto --
en `theme.css` y en el HTML dinámico generado por Python (tarjetas de
semáforo, tarjetas de interacción, chip de estado, texto del plano de
matplotlib). La tabla completa vive al final de
`dashboard/assets/theme.css`; resumen de lo que falló en el primer
intento y cómo se corrigió (siempre ajustando el color de TEXTO, nunca
el de fondo, para no perder el significado semántico de "zona
caliente"):

| Combinación que falló primero | Ratio inicial | Corrección | Ratio final |
|---|---|---|---|
| Texto blanco sobre `--color-hot` (tarjeta "Zona Caliente") | 3.64:1 | Texto cambiado a `--color-ink-on-accent` (negro) | 5.77:1 |
| Texto blanco sobre `--color-cold` (tarjeta "Zona Fría"/interacción) | 3.04:1 | Igual: negro | 6.91:1 |
| Texto blanco sobre `--color-zone-paso`/`--color-zone-nicho`/`--color-zone-none` | 2.17:1 / 3.34:1 / 1.60:1 | Igual: negro | 9.67:1 / 6.28:1 / 13.10:1 |
| Texto blanco del botón `type="primary"` (Streamlit lo pinta blanco por defecto) sobre `--color-hot` (ahora `primaryColor`) | 3.64:1 | Forzado a negro vía CSS (`!important`) en `stBaseButton-primary` | 5.77:1 |
| `--color-hot` usado directamente como color de TEXTO (pestaña activa, hover) | 3.64:1 (blanco) / 3.21:1 (surface) | Se creó `--color-hot-text`, una variante más oscura de la misma familia | 5.62:1 / 4.95:1 |
| `--color-cold` usado directamente como texto | 3.04:1 | Se creó `--color-cold-text` | 5.68:1 |
| Chip de estado: texto coloreado (Frost/gris) sobre pastilla tenue | 2.43:1 | Rediseñado: el texto SIEMPRE usa `--color-ink`, el estado se comunica con un punto de color decorativo (no-texto) | 12.39:1 / 11.88:1 |
| Etiqueta de zona en el plano de matplotlib (texto blanco sobre recuadro negro semitransparente encima del color de zona) -- caso "Sin datos" | 4.26:1 (alpha=0.4) | Se subió la opacidad del recuadro a 0.55 | 6.71:1 |
| Alertas propias (`--color-success`/`--color-warning`) con texto blanco, primer intento | 3.41:1 / 2.72:1 | Colores oscurecidos manteniendo la familia (verde/ámbar) | 5.33:1 / 5.18:1 |

**No verificado contra AA a propósito** (no es texto): `--color-line`
sobre `--color-surface`/`--color-panel` (1.20:1 / 1.36:1) -- es un
borde/divisor decorativo, y se pidió explícitamente un "gris-azulado
sutil", que por definición implica bajo contraste. El criterio WCAG
1.4.11 (contraste no-textual, 3:1) aplicaría si ese borde fuera la
ÚNICA forma de distinguir un componente -- aquí los paneles y botones
también se distinguen por texto/forma, así que se priorizó la sutileza
pedida. Fácil de ajustar si no es lo esperado.

### Cambios estructurales (Fase 3)

- **Fila de 4 KPIs** (`compute_overview_kpis()` + `render_overview_kpis()`
  en `app.py`), antes de las tarjetas de semáforo y de las pestañas:
  zonas monitoreadas, visitas totales, interacciones totales (o "N/D" si
  el video se procesó sin detección de manos -- nunca se muestra "0"
  cuando en realidad no se midió), y zona con más tráfico. Los 4 salen
  directo de `zone_summary_df`/`interaction_summary_df` ya calculados,
  ninguna cifra nueva.
- **Paneles con borde + título interno** (`st.container(border=True, key=...)`
  + `st.markdown("#### ...")` como primer elemento) aplicados a: el
  resumen narrado (Historia), el plano de zonas y el selector de
  heatmap/trayectorias (Mapas, en 2 columnas), las tarjetas de
  interacción por zona (Interacción), el resultado de la simulación
  (Simulador, solo tras presionar "Simular"), y el bloque de reporte PDF
  (Recomendaciones) -- además de las tarjetas de recomendación y de
  tendencias que ya estaban en paneles con borde desde una pasada
  anterior. Contenido que ya vivía dentro de un `st.expander` (la tabla
  completa de métricas, el video de verificación) NO se envolvió en un
  panel adicional -- el expander ya cumple ese rol, un borde extra
  adentro habría sido anidación redundante.
- **Grid de 2 columnas**: aplicado en Mapas (plano de zonas | selector de
  heatmap), que ya existía en Tendencias (fecha A | fecha B) y en
  Simulador (zona origen | zona destino). NO se forzó en la tabla
  completa de métricas (una tabla larga no cabe bien recortada a la
  mitad) ni en los 3 KPI del resultado del simulador o los 3 valores de
  cada tarjeta de tendencia (3 elementos ya caben bien en 3 columnas
  proporcionadas al contenido -- forzarlos a un grid de 2 habría dejado
  una celda vacía o desbalanceada sin ninguna ganancia de legibilidad).
- **Encabezados de panel consistentes**: todo panel con borde usa
  `#### Título` como primer elemento (antes se mezclaba `**texto en
  negrita**` en las tarjetas de recomendación/tendencia con
  `st.subheader()` suelto en otros lados).
- **Sidebar**: se revisó `render_sidebar()` sin moverle nada. Un elemento
  se identificó como potencialmente "de más" respecto al pedido ("solo
  selector de tienda + chips de estado"): el `st.sidebar.caption("Flujo,
  permanencia e interacción -- sin identificar personas.")` bajo el
  título -- es una reafirmación de privacidad, no parte del selector ni
  de los chips. Se reporta sin quitarlo, a la espera de confirmación.

### Verificación honesta

Igual que en pasadas anteriores: no hay forma de ver el resultado
renderizado en un navegador real desde este entorno. Se verificó con
`streamlit.testing.v1.AppTest` que la app arranca sin excepciones y que
las 6 pestañas ejecutan su código sin errores con los datos reales de
`merl_demo` (incluyendo la fila de KPIs con cifras reales: 1 zona, 6
visitas, 9 interacciones, "Snacks" como zona de mayor tráfico), que el
CSS de `theme.css` se inyecta correctamente, y que el flujo del
asistente de configuración (subida de video real) sigue funcionando. El
panel de "Resultado de la simulación" NO se pudo ejercitar con datos
reales porque `merl_demo` solo tiene 1 zona calibrada (el simulador
requiere 2+) -- queda sin probar por falta de un dataset con más zonas,
no por un problema conocido. **La confirmación visual final -- cómo se
ve realmente en un navegador -- la debe dar el usuario.**

## 23. Bug: el CSS se mostraba como texto visible en la página

El rediseño de la sección 22 introdujo un bug real reportado por el
usuario con captura de pantalla: el contenido completo de
`dashboard/assets/theme.css` (comentarios incluidos) aparecía como texto
literal en la página -- viñetas donde había guiones, negritas donde
había comentarios, un link clickeable donde había la URL de Google
Fonts.

**Causa raíz confirmada** (no era lo que parecía a primera vista): la
línea `dashboard/style.py:58` que inyecta el CSS ya estaba bien escrita
(`st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)`). El
problema real vivía DENTRO de `theme.css`: su propio comentario de
cabecera, al explicar cómo se carga el archivo, incluía literalmente el
texto `st.markdown(f"<style>{css}</style>")` como ejemplo de código --
es decir, el archivo contenía la subcadena `</style>` DOS veces (una en
el comentario, cerca del principio; otra al final, la real). Streamlit
usa `remark`/`rehype` (confirmado inspeccionando el bundle instalado)
para su Markdown, que sigue la especificación CommonMark: un bloque
HTML de tipo "style" termina en la PRIMERA línea que contenga
`</style>`, sin importar que esté dentro de un comentario `/* */`. Con
dos ocurrencias, el bloque se cerraba prematuramente en el comentario, y
todo el CSS real que venía después quedaba fuera de la protección de
`unsafe_allow_html`, mostrado como Markdown normal.

**Corrección**: se reescribió ese comentario para no contener nunca el
texto literal de la etiqueta de cierre, y se agregó una advertencia
explícita en el propio archivo para que nadie vuelva a introducir esa
subcadena en un comentario futuro.

**Segundo bug relacionado, encontrado al revisar `status_chip()` y
`render_step_status()` como pidió el usuario** (no reportado por captura
de pantalla, encontrado por verificación rigurosa con un parser real):
`render_step_status()` devolvía un f-string triple-comillado con el
HTML indentado 4 espacios (para que se leyera bien en el código fuente).
CommonMark interpreta cualquier línea indentada 4+ espacios como un
BLOQUE DE CÓDIGO literal -- sin importar `unsafe_allow_html=True` --,
así que este indicador de progreso también habría mostrado su HTML
crudo como texto en vez de renderizarlo, cada vez que corriera el
pipeline completo desde el dashboard. Corregido envolviendo el resultado
en `textwrap.dedent(...).strip()` antes de devolverlo. `status_chip()`
no tenía este problema (genera HTML inline de una sola línea, sin
indentación de bloque).

**Verificación rigurosa realizada** (más allá de "la app no truena"):
se instaló temporalmente `markdown-it-py` (compatible con CommonMark,
la misma familia de especificación que `remark`/`rehype`) solo para
verificar -- no es una dependencia del proyecto, no se agregó a
`requirements.txt`. Con `streamlit.testing.v1.AppTest` más ese parser
real se confirmó, de forma programática y no solo por inspección visual
del código:
- El elemento que inyecta `theme.css` tiene `allow_html=True` (leído del
  proto real de Streamlit, no asumido) y su valor entero se parsea como
  UN SOLO token `html_block` -- no como texto + HTML mezclado.
- El HTML renderizado a partir de ese valor no tiene NADA visible fuera
  de la etiqueta `<style>...</style>` (se extrajo con una expresión
  regular y se confirmó que queda una cadena vacía).
- Ninguna palabra "huella" del CSS (`VARIABLES`, `color-hot`,
  `fonts.googleapis`, etc.) aparece como texto fuera de ese bloque.
- Se revisaron los 32 elementos `st.markdown` que produce la app
  completa recorriendo las 6 pestañas con datos reales de `merl_demo` --
  cero fugas en ningún otro lugar.
- `render_step_status()`, tras el fix, se parsea también como un único
  `html_block` (antes del fix se parseaba como `code_block`, confirmando
  el problema con evidencia, no solo con lectura de código).
- Se confirmó por código fuente que las 5 líneas donde se invocan
  `status_chip()`/`render_step_status()` en `app.py` pasan
  `unsafe_allow_html=True` a `st.markdown()`.

Como en toda esta serie de tareas: no hay forma de confirmar visualmente
en un navegador real desde este entorno. Esta vez la verificación fue
deliberadamente más profunda que "arranca sin excepciones" -- se
verificó el contenido real que vería el navegador con un parser
conforme a la misma especificación que usa Streamlit -- pero sigue
siendo el usuario quien debe confirmar el resultado final mirándolo.

## 24. Cinco defectos visuales concretos, de capturas de pantalla reales

El usuario revisó capturas de pantalla reales del rediseño (sección 22)
y reportó 5 defectos específicos. A diferencia de las secciones 22/23,
aquí no hubo rediseño ni exploración abierta -- cada punto tenía una
causa concreta que investigar antes de corregir.

**1. Los títulos se veían en una fuente serif del navegador, no en
Manrope.** Causa raíz real (no la que parecía obvia): `.streamlit/config.toml`
tenía `font = "sans serif"` -- CON ESPACIO. El enum válido de Streamlit
usa guion (`"sans-serif"`); un valor que no matchea ningún enum y no
tiene `":"` se trata como un nombre de fuente LITERAL inexistente, así
que el navegador termina cayendo a su fuente de documento por defecto
(serif en la mayoría). Se confirmó inspeccionando
`venv/Lib/site-packages/streamlit/config.py` y `runtime/theme_util.py`
que Streamlit tiene un mecanismo NATIVO para cargar Google Fonts:
`font`/`headingFont` aceptan el formato `"<nombre>:<url>"`, y Streamlit
inyecta un `<link rel="stylesheet">` real por cada uno (confirmado en el
bundle JS: un componente mapea `fontSources` 1:1 a elementos `<link>`).
Esto es más robusto que el `@import` original dentro de un `<style>`
insertado dinámicamente. Se cambió `config.toml` a:
```
font = "IBM Plex Sans:https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&display=swap"
headingFont = "Manrope:https://fonts.googleapis.com/css2?family=Manrope:wght@500;600;700;800&display=swap"
```
(dos URLs, no una combinada -- Streamlit rechaza una URL con más de un
`family=`). Se eliminó el `@import` de `theme.css` (redundante y fue la
técnica menos confiable) y se agregó `!important` a la regla `h1,h2,h3,h4`
como refuerzo, ya que Streamlit aplica su propia regla de fuente de
encabezado vía un selector generado por styled-components con mayor
especificidad que un simple `h1, h2, h3`. **Verificación real, no
teórica**: se llamó directamente `_populate_theme_msg()` (la función de
producción de Streamlit que arma el mensaje de tema) con la config real
y se confirmó `heading_font: Manrope`, `body_font: IBM Plex Sans`, y las
dos URLs registradas en `font_sources` -- sin excepción.

**2. Los KPIs no se veían como tarjetas.** El código YA envolvía cada
KPI en `st.container(border=True, key="panel_kpi_...")` (correcto
estructuralmente, confirmado con AppTest). El problema era puramente
visual: `--color-line` (el color de borde) es deliberadamente muy sutil
(~1.2:1 de contraste, ver sección 22) -- suficiente para paneles grandes
con una imagen/gráfico adentro dándoles peso visual, pero insuficiente
para tarjetas pequeñas que dependen ENTERAMENTE del borde para leerse
como "tarjeta". Se agregó una sombra sutil (`box-shadow`) al panel
genérico y una más marcada específica para `st-key-panel_kpi`, que no
depende del contraste del borde para percibirse.

**3. Tarjetas de zona/interacción como bloques de color sólido.**
Cambiadas de fondo saturado + texto `--color-ink-on-accent` (negro) a
fondo TINTADO (`color-mix(in srgb, color 12%, white)`) + borde izquierdo
de 5px con el color saturado + texto `--color-ink` normal -- mismo
lenguaje visual que las tarjetas de recomendación/tendencia. Contraste
recalculado (ink sobre cada tinte al 12%): 13.98:1 a 15.08:1 según la
zona, ver la tabla en `theme.css`. `--color-ink-on-accent` no se
eliminó -- sigue en uso en el texto del botón primario.

**4. El plano de la tienda se veía vacío/sin terminar.** Tres causas
combinadas en `layout_view.py`: (a) el área de dibujo usaba el mismo
blanco que el panel que lo envuelve (`--color-panel` para ambos), sin
ningún límite visual propio; (b) `ax.axis("off")` quita también los
spines, así que no quedaba ningún marco; (c) los límites del plot eran
el frame de cámara COMPLETO, no el área donde realmente hay zonas
calibradas -- con pocas zonas en un frame grande, la mayor parte del
plot quedaba vacía. Corregido: fondo `--color-surface` (distinto del
panel blanco que lo envuelve), un `Rectangle` sin relleno como marco
explícito (`--color-ink-muted`, no el `--color-line` ultra-sutil de los
paneles CSS -- aquí es la única señal de "esto es un diagrama
contenido"), y los límites del plot recortados al área que ocupan las
zonas calibradas (+18% de margen) en vez del frame completo. La
etiqueta de zona pasó de un recuadro negro puro a `--color-ink` (mismo
alpha=0.55, contraste recalculado: 5.06:1 a 8.65:1 según la zona, el
caso más ajustado sigue por encima del mínimo). Verificado visualmente
de forma directa (a diferencia del resto del dashboard, esto es un PNG
estático que sí se pudo abrir e inspeccionar) -- la mejora es clara:
la zona ahora ocupa la mayor parte del plot, con un marco visible.
Límite honesto: matplotlib no puede usar Manrope/IBM Plex Sans (son
fuentes de Google Fonts que solo se cargan en el navegador vía
`config.toml`, no están instaladas como fuente de sistema en este
entorno) -- la etiqueta del plano sigue en la fuente sans-serif por
defecto de matplotlib. Bundlear los archivos de fuente reales para que
matplotlib los use es posible pero es una decisión de alcance mayor
(añadir binarios de fuente al proyecto) que no se tomó sin preguntar.

**5. Inconsistencia de tamaño entre KPIs numéricos y de texto.**
Investigación exhaustiva (código Python de `st.metric` en
`elements/metric.py`, y el bundle JS de `Metric`) NO encontró ningún
mecanismo de auto-ajuste de tamaño por tipo o longitud del valor -- los
4 KPIs ya usaban `st.metric()` de forma idéntica (confirmado con
AppTest, no era una mezcla de `st.metric` + `st.markdown` como se
sospechaba). No se pudo confirmar la causa raíz exacta. Se aplicó un
fix defensivo: `font-size` fijo y explícito con `!important` en
`stMetricValue`/`stMetricLabel`, que garantiza tamaño idéntico sin
importar cuál sea la causa real (aunque no se haya identificado).

**Verificación honesta**: como en las secciones anteriores, esto se
verificó con `streamlit.testing.v1.AppTest` (sin excepciones en las 6
pestañas con datos reales de `merl_demo`) y, para el Defecto 1
específicamente, con una llamada directa a código de producción de
Streamlit (no un mock). El Defecto 4 se pudo verificar visualmente de
forma directa por ser una imagen estática. Los Defectos 1, 2, 3 y 5 NO
se pudieron confirmar visualmente en un navegador real -- eso lo debe
hacer el usuario con una nueva captura de pantalla.

## 25. Migración completa de Streamlit a Flask

Decisión arquitectónica final: reemplazar por completo el frontend de
Streamlit por un backend Flask + Jinja2 + HTML/CSS/JS propio (sin
frameworks de frontend de terceros en esa etapa). No fue un ajuste
puntual -- fue reconstruir toda la capa de interfaz, manteniendo intacta
toda la lógica de negocio (`pipeline/*.py` sin ningún cambio; los
módulos de `dashboard/` con lógica pura reutilizados tal cual o
separados de su parte de presentación).

**Por qué**: las secciones 22, 23 y 24 documentan tres rondas
sucesivas de rediseño visual sobre Streamlit, cada una encontrando un
defecto nuevo -- fuentes que caían a serif por un espacio de más en un
enum de `config.toml`, CSS inyectado dinámicamente que se mostraba como
texto literal en la página, tarjetas que se leían como bloques de color
sólido en vez de tarjetas, botones cuyo color de texto Streamlit
sobrescribía pese a `!important`. El patrón común: Streamlit no expone
suficiente control sobre su propio HTML/CSS generado, así que cada
mejora de diseño terminaba siendo un parche indirecto (manipular un
`config.toml`, apuntar a un `data-testid` interno no documentado,
forzar con `!important` contra un selector generado por
styled-components) en vez de un cambio directo. Tras la tercera ronda
de este patrón, la decisión fue dejar de pelear contra la capa de
presentación de una herramienta pensada para prototipos rápidos de
datos, y construir una propia con control total sobre el HTML y el CSS.

**Qué se mantuvo exactamente igual**: `pipeline/*.py` no cambió ni una
línea -- se sigue invocando por subprocess exactamente como antes.
`pipeline/history_db.py`, `dashboard/ai_insights.py`, y la lógica interna
de `simulator.py`, `storytelling.py`, `trends.py`, `layout_view.py` y
`report_generator.py` tampoco cambiaron su comportamiento -- solo se
separó su lógica pura de su antigua capa de presentación en Streamlit.

**Qué cambió de raíz**: `dashboard/app.py` y `dashboard/style.py`
(el "glue" de Streamlit) se descartaron por completo. En su lugar:
Flask con blueprints (`main`, `setup`, `api`), plantillas Jinja2,
CSS y JavaScript propios. Los procesos largos (el pipeline puede tardar
varios minutos) corren en un hilo de fondo (`dashboard/job_manager.py`)
con polling desde el frontend cada 1.5s -- se descartó WebSockets/
Flask-SocketIO por ser complejidad innecesaria para este alcance. La
calibración de zonas pasó de clic-por-clic con recarga de página
(`streamlit-image-coordinates`) a un `<canvas>` HTML5 donde el polígono
en progreso vive enteramente en el navegador -- solo se envía al backend
al cerrar cada zona.

**Bug real encontrado durante la verificación de la migración** (no
teórico): `app.run(debug=True, ...)` sin `use_reloader=False` deja
activo el reloader por stat de Werkzeug, que puede reiniciar el proceso
Flask ante CUALQUIER archivo que detecte "modificado" bajo el
directorio del proyecto -- incluyendo archivos dentro de `venv/` que
`torch` toca en tiempo de ejecución al cargar el modelo YOLO. Un
reinicio a mitad de un "Procesar video" borra sin aviso todo el estado
en memoria de `job_manager` (diseñado deliberadamente como un dict de
proceso, no persistente en disco), dejando el sondeo del frontend
viendo un job "idle" para siempre aunque el pipeline real siga
corriendo. Se corrigió agregando `use_reloader=False` explícito. Esto
se encontró exactamente porque se probó el flujo completo con
Playwright contra el servidor real, no solo revisando el código.

**Verificación real, no solo revisión de código**: se instaló
Playwright + Chromium headless y se probó, contra el servidor Flask
real corriendo: el panel de resultados de solo lectura con datos reales
de `merl_demo` (las 6 pestañas, sin errores de consola), y el flujo
completo del asistente de configuración de punta a punta con un video
real -- subida, calibración por canvas (clics reales con coordenadas
escaladas, cierre de zona, guardado), lanzamiento del pipeline real en
segundo plano, sondeo de progreso mostrando "Paso X de 6" en tiempo
real, y redirección automática a un panel de resultados con datos
genuinamente calculados por el pipeline (no datos de prueba
precargados). El archivo `config/zones_<tienda>.json` generado por el
canvas se confirmó byte a byte compatible con el formato que
`pipeline/zoning.py` ya esperaba, sin ningún cambio en ese módulo.

**Limpieza posterior**: los archivos originales de Streamlit
(`dashboard/app.py`, `dashboard/style.py`, `dashboard/assets/theme.css`,
`.streamlit/config.toml`) se movieron a `_legacy_streamlit/` como
referencia histórica, no se borraron de inmediato. Las dependencias
`streamlit`, `streamlit-image-coordinates` y `streamlit-drawable-canvas`
se quitaron de `requirements.txt` y se desinstalaron del entorno virtual
-- se confirmó (con `import streamlit` fallando con
`ModuleNotFoundError`, no solo con un monkey-patch de `__import__`) que
los módulos de lógica pura de `dashboard/` importan y funcionan
correctamente sin Streamlit instalado en absoluto.

## 26. Limpieza final de Streamlit + rediseño visual a nivel profesional

Dos tareas separadas, ejecutadas juntas: (1) cerrar los últimos rastros
de la migración de la sección 25 (algunos quedaron sueltos: código vivo
que aún importaba `dashboard/style.py`, comentarios/docstrings con rutas
viejas, `dashboard/assets/theme.css` y `.streamlit/config.toml` sin
mover), y (2) una pasada de diseño real sobre el resultado de esa
migración, con la instrucción explícita de que se viera "diseñado por
alguien con oficio", no una demo de hackathon.

**Limpieza de Streamlit (verificación repetida, no asumida)**: los
archivos legacy pasaron de `dashboard/` a `_legacy_streamlit/` en la
raíz del proyecto (`app.py`, `style.py`, `theme.css`,
`streamlit_config/config.toml`), cada uno con un `README.md` explicando
qué es y que su borrado definitivo queda a decisión del usuario. El
`dashboard/style.py` "vivo" (no el legacy) resultó estar huérfano --
nada lo importaba ya tras la sección 25 -- así que se eliminó del árbol
activo. `streamlit`, `streamlit-image-coordinates` y
`streamlit-drawable-canvas` se desinstalaron del entorno virtual (no
solo se quitaron de `requirements.txt`) y se repitió la verificación de
pureza de los 13 módulos de lógica de negocio de `dashboard/` con
Streamlit realmente ausente del intérprete (`ModuleNotFoundError`, no
un mock) -- los 13 importan sin problema. `flask` se agregó a
`requirements.txt`, que no lo tenía documentado pese a ser la dependencia
real del backend actual.

**Sistema de espaciado y tipografía**: se evaluó adoptar Tailwind CSS
(con la paleta del proyecto como tema) contra reforzar el CSS propio con
una escala explícita. Se eligió la segunda opción -- el problema real no
era la ausencia de un framework de utilidades, sino varios `style="..."`
inline con valores sueltos (`gap:16px`, `margin-bottom:0.75rem`,
`font-size:0.9rem`) esparcidos en las plantillas; una escala de
variables CSS (`--space-1` a `--space-10`, múltiplos de 4px, y
`--text-xs` a `--text-display`) resuelve exactamente ese problema sin
reescribir cuatro plantillas y cuatro archivos JS que ya funcionaban
bien, y sin agregar una dependencia de build (Tailwind vía CDN no
permite purga de clases ni personalización completa del tema sin un
paso de compilación). `main.css` quedó reescrito sobre esa escala:
jerarquía de encabezados explícita (h1 32px/h3 22px/h4 18px, antes h1/h2/h3
heredaban el tamaño por defecto del navegador y solo h4 tenía un valor
deliberado), tarjetas KPI y de métricas unificadas a un mismo tamaño de
número grande (antes 26px vs. 30px sin razón), y más aire alrededor del
contenido (`--main-content` pasó de `2rem 2.5rem` a `48px 64px` de
padding).

**Iconografía (Lucide, SVG, sin runtime de componentes)**: se
reemplazaron TODOS los emojis del diseño (🔑✏️🗑️💾 en el panel del
asistente de IA, 🛑🚶✋ en los íconos de la línea de tiempo de Historia)
por íconos de Lucide, cargados vía CDN (`cdn.jsdelivr.net`, versión
fijada `0.462.0`) como un bundle UMD que solo reemplaza
`<i data-lucide="...">` por el SVG correspondiente -- sin un framework
de componentes ni estado propio. Los puntos de estado de la barra
lateral (antes los caracteres `●`/`○`) pasaron a ser un `<span>` con
`border-radius:50%` y color de fondo, dibujado 100% en CSS -- ni emoji
ni ícono hacen falta ahí. Como los mensajes de alerta y el timeline se
arman en tres lugares distintos (Jinja del lado servidor, y JS del lado
cliente en tres archivos), se centralizó el markup con ícono en un solo
lugar por cada lado: la macro `templates/_macros.html:alert()` para
Jinja, y `window.alertHtml()`/`window.refreshIcons()` en `main.js` para
JS -- evita repetir la tabla ícono-por-tipo cuatro veces.

**Gráfico de evolución histórica (Chart.js)**: la pestaña Tendencias
solo comparaba DOS fechas mediante tarjetas (`compare_dates()`,
sección de arriba) -- una limitación real cuando ya hay 3 o más fechas
guardadas, porque las tarjetas no pueden mostrar una tendencia, solo un
antes/después puntual. Se agregó `trends.get_history_series()` (lógica
pura nueva, reutiliza `history_db.get_zone_summary_for_date()` para
TODAS las fechas disponibles, no solo dos) y un gráfico de líneas real
con Chart.js (CDN, versión fijada `4.4.7`) en `results.js`, una línea
por zona, selector de métrica, y colores tomados de las mismas
variables CSS del tema (`getComputedStyle` en tiempo de ejecución, no
colores repetidos a mano). Las tarjetas de comparación A/B se
mantuvieron debajo del gráfico como el detalle fecha-a-fecha -- son
complementarias, no redundantes. El `<canvas>` se inicializa recién al
abrir la pestaña por primera vez (no al cargar la página): un canvas
dentro de un `.tab-panel` con `display:none` mide 0x0 en el momento en
que Chart.js sería creado si se inicializara con la página, y quedaría
con tamaño incorrecto de forma permanente.

**Deliberadamente NO adoptado**: ningún framework de componentes UI
(Bootstrap, Material, etc.) -- el pedido explícito era evitar que la
app se viera "reconocible" como hecha con una librería de terceros;
mantener HTML/CSS propio con una escala de diseño rigurosa logra el
mismo resultado visual sin ese riesgo.

**Verificación**: Playwright + Chromium headless (ya instalado, ver
sección 25) tomó capturas reales de las 12 vistas principales
(bienvenida, las 6 pestañas del panel de resultados, y las 4 etapas del
asistente de configuración incluida la calibración por canvas con una
zona dibujada) contra el servidor Flask real corriendo, con 0 errores
de consola en todas. Las capturas se inspeccionaron una por una (no solo
se generaron) -- ver `docs/screenshots/README.md` para la lista
completa y qué mostraba cada una. El gráfico de Tendencias se probó
además con datos reales de 4 fechas insertadas temporalmente en
`history.db` solo para esa verificación (eliminadas después; el
historial real del proyecto sigue vacío) -- confirmó que las líneas, el
selector de métrica, y el cambio de dataset sin recrear el gráfico
funcionan correctamente.

## 27. Acentos de marca + tratamiento de fondos (barra lateral oscura, chips, gradientes, animaciones, fondo con textura)

Segunda pasada de pulido visual sobre el rediseño de la sección 26,
enfocada en dos cosas: acentos de marca que antes faltaban (barra
lateral oscura, chips de color en íconos KPI, gradiente en el botón
primario, resplandor en la pestaña activa, 5 animaciones puntuales) y
tratamiento de FONDOS -- no solo tarjetas -- para que la página se
sienta con profundidad, no plana.

**Regla explícita que se mantuvo**: `--color-hot` y `--color-cold`
siguen exclusivos de la clasificación de zona real (tarjetas de
categoría, leyenda, heatmaps) y de UN solo uso decorativo ya
justificado -- el pulso en la tarjeta "Zona Caliente" (`.category-card-pulse`),
que literalmente ES esa clasificación, no una decoración genérica.
Ningún fondo nuevo (body, `.page-hero`, chips de ícono) usa hot/cold --
todos usan variaciones de `--color-ink` (mezclado vía `color-mix()`
sobre panel/surface) o los acentos semánticos ya existentes
(info/success/warning/ink-muted).

**Barra lateral oscura**: `--sidebar-bg` (`--color-ink`) a
`--sidebar-bg-alt` (#232E42) en gradiente vertical. Texto en
`--sidebar-text` (#F3F5F7, 14.4:1) y `--sidebar-text-muted` (#A9B4C2,
7.5:1) -- ambos verificados contra los dos extremos del gradiente, no
solo contra un color plano. Un detalle real que casi se pasa: el punto
inactivo de los chips de estado usaba `--color-ink-muted`, que da solo
2.64:1 sobre `--sidebar-bg` (insuficiente incluso para el mínimo de 3:1
de componentes no textuales) -- se corrigió a `--sidebar-text-muted`
específicamente dentro de `.sidebar`.

**Chips de color en íconos KPI**: círculo de 40px detrás de cada ícono,
con acento por tipo de dato (`--accent-zonas`=info, `--accent-visitas`=success,
`--accent-interacciones`=warning, `--accent-top-zona`=ink-muted neutro
-- deliberadamente NO hot, para no insinuar que "zona con más tráfico"
es lo mismo que "zona caliente", que es un cálculo distinto).

**Fondo de página**: gradiente diagonal `#EEF1F4` -> `#E6EBF0` (160deg)
+ una textura de puntos (`radial-gradient`, 3.2% de opacidad, 26px de
espaciado). Se ajustó dos veces hacia abajo desde un primer intento más
visible (4.5%/22px) tras verlo en una página con mucho espacio vacío
(el asistente de bienvenida) -- ahí se notaba más de lo deseado. Se
prefirió reducir la intensidad en vez de dejarlo y decir que "quedó
bien".

**Sección "hero"**: `templates/layout.html` ahora envuelve el `<h1>` en
un `.page-hero`, con un nuevo bloque `{% block hero_extra %}` que
`results.html` usa para incluir el expander de "Agregar nueva
grabación" y todo "Panorama general" en la MISMA franja visual que el
título -- fondo con gradiente de `--color-ink` al ~7% de opacidad hacia
`--color-panel`. `welcome.html`/`setup.html` no definen `hero_extra`,
así que su hero es solo el título -- comportamiento esperado, no un
defecto.

**Separación entre secciones**: se evaluaron las dos opciones que
ofrecía la tarea (bandas de color alternadas vs. un separador con
sombra) y se eligió la más liviana -- envolver cada bloque grande en su
propia superficie de color arriesgaba el look "recargado" que la
propia tarea pedía evitar. `.section-divider` (línea con bordes
difuminados + sombra finísima) marca el corte entre "Resumen por zona"
y las pestañas sin sumar otra superficie.

**Botón primario**: gradiente 135deg de `--color-hot` a
`color-mix(--color-hot, black 14%)` -- dos tonos derivados del mismo
color base, no un color nuevo inventado.

**Pestaña activa**: además del subrayado ya existente, un
`box-shadow: 0 4px 10px -4px rgba(232,84,62,0.55)` que actúa como
resplandor difuso justo debajo del texto.

**Las 5 animaciones**, todas respetando `prefers-reduced-motion` (regla
global en `:root` que corta duración/transición a ~0 para cualquier
elemento):
1. Conteo de KPIs (JS, `main.js:initKpiCountUp`) -- easing cúbico,
   ~700ms, se salta entero si el usuario pide menos movimiento (no solo
   se acorta).
2. Aparición escalonada de tarjetas KPI/zona (`@keyframes aparecer-tarjeta`,
   delay creciente por `:nth-child`).
3. Elevación en hover (`.panel`, `.kpi-card`, `.category-card` --
   `translateY` + sombra más marcada).
4. Transición suave de expanders -- nativamente `<details>` no anima;
   se implementó con la Web Animations API (`element.animate()`,
   nativa del navegador, sin librería) animando `height`, patrón
   estándar para acordeones accesibles.
5. Pulso en la tarjeta "Zona Caliente" (`.category-card-pulse::after`,
   halo que respira cada 2.6s).

**Bug real encontrado y corregido durante la verificación** (no
teórico): la primera versión de la animación 2 usaba `opacity: 0` como
valor BASE de la regla más `animation: ... forwards`, con limpieza en
JS (`el.style.animation = "none"`) tras terminar para no bloquear el
`transform` de la animación 3 (hover) con el `transform` de la
animación 2 ya completada. Resultado real, confirmado con
`getComputedStyle` vía Playwright: al quitar la animación, el
`opacity: 0` base de la regla (una propiedad estática, no tocada por
"quitar la animación") volvía a aplicarse -- las 4 tarjetas KPI y la
tarjeta de zona quedaban invisibles PARA SIEMPRE tras cargar la página.
Se corrigió cambiando `forwards` por `backwards` y la base a
`opacity: 1` -- con `backwards` la tarjeta empieza visible por cascada
normal, la animación solo se nota durante el delay/duración, y al
terminar no deja nada fijado (sin necesitar limpieza por JS). Esto se
encontró exactamente porque se inspeccionó `getComputedStyle` real
tras una captura de Playwright que mostraba las tarjetas en blanco, no
por revisión de código.

**Verificación**: Playwright con y sin `prefers-reduced-motion:
reduce` emulado -- con la preferencia activa, `opacity` de las
tarjetas sigue en `1` y el valor del KPI se muestra directo (sin pasar
por el conteo animado), confirmando que "reduced motion" no dejó nada
invisible ni a medio animar. Hover, resplandor de pestaña y pulso se
confirmaron con `getComputedStyle` (no solo capturas): `transform`
cambia a `translateY(-3px)` con `box-shadow` más fuerte en hover, la
pestaña activa expone el `box-shadow` de resplandor, y
`.category-card-pulse::after` expone `animationName: pulso-caliente`.

## 28. Paleta propia, modo oscuro/claro, y menú lateral de navegación

Tres cambios estructurales grandes, hechos como fases secuenciales:
paleta propia con libertad de elección (ya no "heredada" de rondas
anteriores), modo oscuro/claro completo con interruptor persistente, y
reemplazo de las pestañas horizontales por un menú lateral vertical
(con una sección nueva, "Resumen", que unifica lo que antes eran
"Panorama general" + "Resumen por zona" repetidos arriba de cada
pestaña).

**Paleta (Fase A)**: neutros "zinc" fríos (`#F7F7F9`...`#1C1C24` en
claro, `#111114`...`#F1F1F4` en oscuro) + acento propio índigo/violeta
(`#5B4FD6` claro / `#9083FF` oscuro) para TODA la UI genérica -- botones,
enlaces, foco de formularios, pestaña activa, chips de estado
"Calibrada/Procesada". Decisión deliberada: `--color-hot`/`--color-cold`
NO se reinventaron con hues nuevos -- se mantuvo el hex exacto que ya
usa `dashboard/colors.py` (Python), porque esos dos colores son un
contrato cruzado entre el CSS y una imagen generada por matplotlib
(`api/layout-plot.png`) que debe seguir viéndose igual en las tarjetas
de zona y en el plano -- inventar un hue nuevo solo en CSS habría hecho
que la tarjeta de zona y el plano de la tienda mostraran rojos
distintos para la "misma" zona caliente.

**Auditoría y migración de usos indebidos de hot/cold**: al revisar el
CSS existente antes de escribir la paleta nueva, se encontró que
`--color-hot`/`--color-cold` se usaban como acento GENÉRICO de UI en
al menos 9 lugares que no tienen nada que ver con clasificación de
zona: botón primario, `:hover`/`:focus` de botones y formularios,
pestaña activa, `accent-color` de checkbox/radio/range, hover de
`details.expander` y `.dropzone`, el spinner de progreso, y --el más
notorio-- el punto "activo" de los chips de estado "Calibrada/Procesada"
de la barra lateral (que usaba `--color-cold` literal para decir
"completado", sin relación alguna con zonas frías). Todo eso se migró
a `--color-accent` (genérico) o `--color-success` (para "completado",
semánticamente correcto -- antes decía "frío" para significar "listo").
Las tarjetas de Recomendaciones/Tendencias, que usaban la metáfora
"hot=accionable/cold=analítico" (`.card-hot`/`.card-cold`), se
renombraron a `.card-accent`/`.card-info` con los tokens
correspondientes -- ya no son "casi zona caliente/fría" visualmente.

**Modo oscuro/claro (Fase B)**: `:root[data-theme="light"]` /
`:root[data-theme="dark"]`, con `@media (prefers-color-scheme: dark)`
como red de seguridad si JavaScript está deshabilitado. El script que
decide el tema vive INLINE en el `<head>` de `layout.html`, antes de
cualquier hoja de estilo -- lee `localStorage`, si no hay nada cae a
`prefers-color-scheme`, y fija `data-theme` en `<html>` ANTES del
primer pintado (el patrón estándar para evitar el "flash" de tema
incorrecto). El interruptor (sol/luna, en la fila del logo de la barra
lateral) solo maneja el clic y guarda la preferencia explícita.
Verificado con Playwright en 3 escenarios reales: SO en claro sin
preferencia guardada -> `data-theme="light"`; SO en oscuro sin
preferencia guardada -> `data-theme="dark"` (respeta el sistema);
clic en el interruptor desde oscuro -> cambia a claro Y sobrevive un
`reload()` completo (confirma la persistencia real en localStorage, no
solo el cambio visual inmediato).

Intensidades de hot/cold ajustadas por tema, no el mismo valor
reusado: el porcentaje de mezcla del fondo tintado de `.category-card`
sube de 12% (claro) a 20% (oscuro) vía `--category-tint-pct`, porque el
mismo 12% contra un panel oscuro resultaba casi imperceptible. El color
BASE del borde de la tarjeta de "Resumen por zona" viene fijo desde
Python (`classify_zones()` en `layout_view.py`, que no se tocó) y por
lo tanto NO cambia de hue entre temas -- solo cambia el color contra el
que se mezcla (`--color-panel`, que sí es reactivo al tema) y el
porcentaje. Se verificó visualmente que el resultado se ve bien en
ambos modos de todas formas (un vino oscuro elegante en modo oscuro,
no un error). Las tarjetas de "Interacción con producto" y la leyenda
de colores, en cambio, SÍ son 100% reactivas al tema porque su color se
arma en la plantilla vía `var(--color-hot)`/`var(--color-cold)`
directamente, no un hex fijo de Python -- se corrigieron los dos
lugares que antes tenían hex hardcodeado (`#0EA5A0`, `#E8543E`, etc.)
en `results.html` para que usaran las variables.

**Limitación conocida y aceptada**: la imagen "Plano de la tienda"
(`api.layout_plot`, matplotlib) usa los colores de `colors.py` fijos y
NO se adapta al tema -- adaptarla requeriría pasarle el tema a
`layout_view.render_layout_plot()`, fuera del alcance permitido (no
tocar esa lógica). Se le dio un fondo blanco explícito (`.panel-img`)
para que se vea como una "hoja clara enmarcada" intencional en modo
oscuro, no como un elemento roto.

**Menú lateral (Fase C)**: decisión -- cambio de sección vía JavaScript
en una sola página, NO rutas Flask reales por sección. Razón: las 6
secciones ya comparten toda su lógica interactiva (selector de
heatmap, gráfico de Tendencias con Chart.js, Simulador, asistente de
IA, botón de PDF) atada a IDs de elementos en UNA página ya cargada;
convertir cada una en una ruta separada habría significado duplicar la
construcción de contexto de `main_routes.results()` seis veces o
reestructurarla a fondo, further alejándose de "esto es una
reorganización de dónde vive el contenido, no una reconstrucción de su
lógica". El menú lateral reutiliza LITERALMENTE las mismas clases que
ya usaban las pestañas horizontales (`.tabs-nav`, `.tab-btn`,
`data-tab`, `.tab-panel`) -- la única diferencia es dónde viven
(`{% block sidebar_nav %}` en la barra lateral en vez de arriba del
contenido) y su estilo (`.sidebar .tabs-nav`/`.sidebar .tab-btn`
override a columna vertical con indicador de borde izquierdo en vez de
subrayado inferior) -- `static/js/results.js` (`initTabs()`) no
necesitó ni una línea de cambio.

La nueva sección "Resumen" (antes "Panorama general" + "Resumen por
zona", repetidos arriba de las 6 pestañas anteriores) se armó como un
`tab-panel` más, marcado activo por defecto -- se sacó el `<h3>Panorama
general</h3>` y la fila de KPIs de `{% block hero_extra %}` (que ahora
solo tiene el expander de "Agregar nueva grabación") y se movieron
adentro de `#tab-resumen` junto con "Resumen por zona", que antes vivía
suelto en `{% block content %}` antes del `<nav>` de pestañas.

**Ancho de la barra lateral**: subió de 272px a 296px para que
"Interacción con producto" (el ítem más largo) no se sintiera apretado
-- confirmado visualmente, cabe en una sola línea en el ancho de
prueba (1500px de viewport).

**Verificación**: Playwright con `browser.new_context(color_scheme=...)`
(no solo `emulate_media`, para probar el escenario real de "primera
visita, SO en X, sin localStorage todavía") -- 6 capturas (Resumen,
Mapas, Recomendaciones × 2 temas) más una de Interacción con producto
por tema, inspeccionadas una por una. Confirmado sin ambigüedad: menú
lateral con las 7 secciones sin apretarse, ambos temas con contraste
claramente suficiente a simple vista (no solo por los números), la
tarjeta de "Zona Caliente" legible y con buen aspecto en modo oscuro
pese a la limitación de hue fijo, y el plano de la tienda mostrándose
como una superficie clara intencional (no rota) sobre fondo oscuro.
Cero errores de consola en las 8 combinaciones de página × tema
probadas.

## 29. Regresión real del asistente de configuración tras el menú lateral (sección 28)

Reporte: en "1. Sube tu video", el área de video/vista previa aparecía
"en blanco" aunque "Usar otro video" sí se mostraba (evidencia de que
`video_path` de sesión SÍ estaba seteado, solo que no se veía). Auditoría
completa del asistente (subir/recortar/calibrar/procesar) en ambos
temas, no solo el síntoma puntual.

**Causa raíz confirmada del síntoma reportado**: `.media-frame` (la
clase del `<video>` de vista previa) nunca tuvo borde/fondo propio, a
diferencia de sus hermanos `.panel-img` (imágenes) y
`#calibration-canvas` (canvas de calibración), que sí los tienen desde
el rediseño de la sección 26. Un `<video>` sin límite visual propio se
funde con la página si el navegador aún no pintó un cuadro (o si el
cuadro real de la cámara es oscuro) -- en modo oscuro, contra una
página casi negra, el efecto es "no hay nada ahí" aunque el elemento
esté presente, cargado y con datos (confirmado con
`video.readyState === 4` y `videoWidth/videoHeight` correctos vía
Playwright -- el elemento SÍ existe y SÍ cargó, el problema era 100%
de ausencia de marco visual, no de lógica/backend). Corregido dándole a
`.media-frame` el mismo tratamiento que sus hermanos: `border: 1px
solid var(--color-line); background: var(--color-bg-alt); box-shadow:
var(--shadow-card);` -- ahora tiene un marco visible sin importar qué
tan oscuro sea el contenido del video ni el tema activo.

**Segundo problema real, encontrado en la auditoría (no reportado
todavía)**: el botón "Guardar todas las zonas" (`.btn-primary`) se
volvía prácticamente invisible justo después de guardar una zona
(queda `disabled`). Causa: `.btn:disabled { opacity: 0.5; }` es un
truco que solo funciona si el texto y el fondo tienen SUFICIENTE
contraste incluso después de que ambos se desvanezcan igual -- pero
`.btn-primary` usa `--color-on-accent` (blanco en modo claro, casi
negro en modo oscuro) específicamente para contrastar contra un fondo
SATURADO. Al aplicar opacity:0.5 a TODO el botón, el fondo saturado
también se desvanece revelando la página detrás, y el texto (ahora a
mitad de opacidad) queda prácticamente del mismo tono que esa página
-- blanco-sobre-casi-blanco en modo claro, oscuro-sobre-casi-negro en
modo oscuro. Confirmado con `getComputedStyle` real (no solo
inspección visual): antes del fix, el botón deshabilitado en foco/hover
mostraba fondo y texto sin contraste efectivo. Corregido con un estado
`:disabled` EXPLÍCITO para `.btn-primary` (fondo `--color-line`, texto
`--color-ink-muted`, `opacity: 1`) en vez del truco de opacidad --
funciona igual de bien en ambos temas porque no depende de qué color
tenga el fondo/texto original.

**Resto de la auditoría, confirmado SIN problemas**: `.progress-ring`
(el spinner giratorio) y `.progress-card`/`.progress-title`/`.progress-desc`
ya usaban `var(--color-accent)`/`var(--color-line)`/`var(--color-ink)`
desde la sección 27 -- se ve y gira correctamente en ambos temas,
verificado visualmente (no solo por código) en una captura con el
proceso real en curso mostrando "Paso 1 de 6" en modo oscuro. Los
colores de dibujo del canvas de calibración (verde para zonas
cerradas, rojo para el polígono en progreso) son intencionalmente fijos
en JavaScript -- se dibujan SOBRE el video de la cámara, no sobre
"chrome" de la interfaz, así que no necesitan ser reactivos al tema (y
de hecho NO deberían serlo: un verde/rojo saturado siempre visible
sobre cualquier footage es la elección correcta). Se confirmó por
búsqueda exhaustiva (`grep` de `background:#`/`color:#` en templates y
JS) que no queda ningún otro color hardcodeado fuera de los bloques de
definición de tema y del blanco intencional de `.panel-img`.

**Verificación final**: flujo completo subir -> recortar (miniaturas
visibles) -> calibrar (canvas + vista previa de calor visibles, zona
dibujada y guardada con el botón ya legible) -> procesar (spinner +
"Paso X de 6" + log expandible, todos legibles) probado de punta a
punta con Playwright, dos tiendas de prueba independientes (una por
tema). En modo CLARO se dejó completar el pipeline real las 6 etapas
hasta redirigir a un panel de resultados con datos genuinos (7 visitas,
"Zona de Paso"). En modo OSCURO se confirmó visualmente cada paso
incluyendo el inicio real del procesamiento (Paso 1 de 6 en pantalla) --
no se esperó la finalización completa en ese modo porque el pipeline ya
se había verificado exhaustivamente en corridas anteriores de esta
sesión y el objetivo de esta ronda era la capa visual, no repetir la
validación del pipeline en sí. Cero errores de consola JavaScript en
las dos corridas completas.

## 30. Ancho del contenido principal no aprovechaba pantallas anchas

Reporte: en el área de contenido (a la derecha del menú lateral), las
tarjetas se detenían bastante antes del borde derecho en pantallas
anchas, dejando una franja vacía sin usar.

**Causa raíz confirmada con Playwright** (ancho real medido, no
supuesto): `.main-content { max-width: 1280px; }`, sin `margin: 0
auto`. A 1920px de ancho de viewport (la resolución de escritorio más
común) con la barra lateral de 296px, el espacio disponible real es
1624px -- pero el límite de 1280px lo cortaba ahí, dejando **344px**
vacíos, todos acumulados del lado derecho (sin `margin:auto` que
repartiera el sobrante). A 1440px el límite ni siquiera se activaba
(1144px de espacio disponible < 1280px), por eso el defecto no era
visible en esa resolución -- confirma que el problema era
específicamente el valor del límite, no un cálculo de resta roto.

**Corrección**: `max-width: 1700px` (generoso -- absorbe 1920px con
sidebar de 296px sin activarse en absoluto) + `margin: 0 auto` (reparte
cualquier sobrante en partes iguales a los dos lados en vez de
acumularlo de un solo lado, para monitores ultra anchos donde el
límite sí se activa).

**Verificado con Playwright, 3 anchos de viewport**:

| Viewport | Espacio disponible (viewport - sidebar) | Ancho real de `.main-content` | Vacío a la derecha |
|---|---|---|---|
| 1920px | 1624px | 1624px | 0px (antes: 344px) |
| 1440px | 1144px | 1144px | 0px (sin cambio, ya estaba bien) |
| 2560px (bonus, ultra ancho) | 2264px | 1700px (límite activo) | 282px repartidos simétricamente a cada lado (antes habría sido 564px de un solo lado) |

Confirmado visualmente en capturas reales a los 3 anchos, no solo por
los números.

## 31. Historial de tendencias: opt-out en vez de opt-in

El checkbox "Guardar este resultado en el historial de tendencias"
pasó de desmarcado (opt-in, fácil de olvidar) a marcado por defecto
(opt-out) -- la expectativa normal de un dueño de tienda es que cada
video quede guardado automáticamente. Junto al checkbox, el campo de
fecha (`<input type="date">`, ya existía pero quedaba oculto hasta
marcar el checkbox) ahora siempre es visible, PRE-LLENADO con la fecha
real del navegador del usuario (no del servidor -- así "hoy" coincide
con la zona horaria de quien está mirando la pantalla) y con
`max` = esa misma fecha (no se puede elegir un día futuro). Al
desmarcar el checkbox, el campo se deshabilita visualmente
(`input:disabled` + una clase `.field-disabled` que atenúa también la
etiqueta y el texto de ayuda) en vez de desaparecer -- sigue
comunicando "esto existe pero no aplica ahora mismo".

**Backend**: no requirió ningún cambio. `api_routes.py:process()` ya
recibía `record_history`/`run_date` como JSON explícito (via
`fetch()`, no un `<form>` tradicional), así que la ambigüedad de "un
checkbox desmarcado no se envía en un POST de formulario" que
preocupaba la tarea no aplica acá -- `setup.js` siempre manda
`record_history: true/false` explícito leyendo `.checked` en JS, nunca
"ausente".

**Verificado con Playwright**: checkbox marcado por defecto (`True`) y
fecha pre-llenada con la fecha real del sistema (`date.today()` en
Python vs. el valor leído del input coincidieron exactamente) al
cargar el asistente para una tienda nueva. Al desmarcar, `disabled`
pasa a `true` y la clase `field-disabled` se aplica (confirmado por
`getComputedStyle`/atributo, no solo visualmente). Se corrió el
pipeline real una vez de punta a punta (con `--skip-hands` para
acelerar) dejando el checkbox en su estado por defecto sin tocar nada,
y se confirmó con una consulta SQL directa a `data/output/history.db`
que la fila quedó con `run_date` exactamente igual a la fecha del día
en que se corrió la prueba.

**Hallazgo operativo, no relacionado con esta funcionalidad**: durante
la verificación se observó que cada subprocess lanzado por
`job_manager.py` (y a su vez cada subprocess que ESE lanza) aparece
duplicado en el árbol de procesos de Windows -- un hijo directo con la
línea de comando IDÉNTICA al padre, en al menos 3 niveles distintos
(`dashboard/app.py`, `pipeline/run_pipeline.py`,
`pipeline/detect_and_track.py`). Confirmado con
`Get-CimInstance Win32_Process` (PowerShell, no `wmic` -- su
salida UTF-16 se corrompe al pasar por bash) que es un patrón
padre-hijo real, no un artefacto de lectura. Es un comportamiento del
entorno Windows de esta máquina/sesión (probablemente del mecanismo de
backgrounding de la terminal usada para lanzar `python.exe`), presente
desde mucho antes de esta tarea -- no algo introducido por el cambio
del checkbox. Un intento de "limpiarlo" matando uno de los dos procesos
de un job en curso ROMPIÓ esa corrida (quedó en estado `error`,
confirmado) -- la segunda corrida, sin intervenir, completó
exitosamente pese a la duplicación aparente. Documentado para que
quede constancia: si se ve un job "duplicado" en el futuro, NO matar
ninguno de los dos procesos mientras esté corriendo.

## 32. Nivel de agrupación TIENDA -> CÁMARAS

Hasta esta sección, cada "tienda" del sistema era en realidad una sola
cámara/video con sus propias zonas (`config/zones_<id>.json`,
`data/output/*_<id>.csv`, un registro opcional en `history.db`). Esta
sección agrega un nivel de agrupación por ENCIMA de eso -- una tienda
física real (ej. "Tienda Centro") puede tener varias cámaras (entrada,
góndola de snacks, caja...) -- SIN renombrar ni mover ningún archivo
existente: el identificador que antes se llamaba "store_name" sigue
siendo exactamente el mismo string en el filesystem, ahora llamado
"cámara" conceptualmente.

**Modelo de datos (`config/tiendas.json`)**: un registro nuevo y
liviano, independiente de todo lo demás:

```json
{
  "tienda_centro": {
    "label": "Tienda Centro",
    "camaras": ["tienda_centro_entrada", "tienda_centro_snacks"]
  }
}
```

Cada entrada de `camaras` es un identificador que YA EXISTE como
"store_name" -- este archivo solo agrupa, no describe zonas ni
resultados (eso sigue viviendo donde siempre vivió). Una cámara
pertenece a una sola tienda a la vez (`add_camara_a_tienda` lanza
`ValueError` si ya está asignada a otra); una cámara creada ANTES de
esta funcionalidad (ej. `merl_demo`) simplemente no aparece en el
registro todavía y sigue funcionando exactamente igual por su cuenta --
si `config/tiendas.json` no existe en absoluto, el sistema se comporta
como si estuviera vacío (`{}`), no como un error.

**Capa de agregación -- `dashboard/tienda_service.py`** (módulo nuevo,
NO `pipeline/tiendas.py`, ver "Decisión de organización" abajo):

- `get_camaras_de_tienda(tienda_id)` -- lista de cámaras de una tienda.
- `get_zone_summary_combinado(tienda_id)` / `get_interaction_summary_combinado(tienda_id)`
  -- concatenan (`pd.concat`) el `zone_summary`/`interaction_summary`
  de TODAS las cámaras de la tienda en un solo DataFrame, reutilizando
  `store_service.load_store_data()` sin reimplementar nada, agregando
  una columna `camara_origen` (más `fecha_referencia`/
  `duracion_referencia`, ver abajo).
- `compute_tienda_kpis(...)` -- sumas simples sobre el combinado
  (zonas totales, visitas totales, interacciones totales) más la zona
  con más tráfico entre TODAS las zonas de TODAS las cámaras,
  indicando de qué cámara es.
- `get_camara_referencia(camara_id)` -- fecha/duración de referencia de
  una cámara, con una postura de "honestidad técnica" explícita (mismo
  principio que el resto del proyecto, ver sección 4): la duración se
  lee del video real (`video_reference` en `zones_<camara>.json`) SOLO
  si ese archivo todavía existe en disco; si no, se reporta
  `duracion_fuente: "no_disponible"` en vez de inventar un número. La
  fecha usa la fecha de ÚLTIMA MODIFICACIÓN de
  `zone_summary_<camara>.csv` (cuándo se procesó) como aproximación
  honesta, marcada explícitamente `fecha_fuente: "fecha_de_procesamiento"`
  -- NUNCA presentada como si fuera la fecha real de grabación, que hoy
  el sistema no guarda de forma confiable fuera del historial opcional.

**Decisión de organización (desviación deliberada de una de las dos
opciones planteadas)**: las funciones agregadoras viven en
`dashboard/tienda_service.py`, no en `pipeline/tiendas.py`. Reutilizan
`dashboard/store_service.py` y `dashboard/video_utils.py`, ambos ya
viven en `dashboard/` -- ponerlas en `pipeline/` habría invertido la
dependencia normal del proyecto (`pipeline/` nunca depende de
`dashboard/`, solo al revés) sin ninguna ganancia real.

**Simulador multi-cámara (`dashboard/simulator.py`)**: `simulate_move()`
-- el cálculo central (tasa de interacción por visita, extrapolada al
tráfico de la zona destino) -- **no cambió una sola línea**. Se
agregaron funciones nuevas al lado (`get_zone_options_multi`,
`run_simulation_multi`) que arman una clave compuesta
`"camara_id::zone_id"` (porque dos cámaras distintas podrían calibrar
una zona con el mismo id) y llaman a `simulate_move()` sin
modificarla. `run_simulation_multi` también devuelve `same_camara` y
la fecha/duración de referencia de ambas cámaras, para que la interfaz
decida cuándo mostrar la advertencia de comparabilidad.

**Advertencia de comparabilidad -- OBLIGATORIA, no en un tooltip**:
aparece en dos lugares:
1. En la vista combinada (`tienda_combinada.html`), como un
   `{% call alert('warning') %}` visible SIEMPRE que 2+ cámaras
   aportan resultados (`camaras_con_resultados >= 2`) -- deliberadamente
   sin importar si las fechas coinciden por casualidad, porque una
   coincidencia de fecha no vuelve la comparación justa por sí sola
   (podrían tener duraciones distintas igual). Cada fila de la tabla de
   zonas muestra su propia fecha/duración de referencia.
2. En el resultado del simulador multi-cámara
   (`tienda_combinada.js:comparabilidadHtml()`), SOLO cuando
   `same_camara === false` -- muestra explícitamente AMBAS
   fechas/duraciones y ambos nombres de cámara, no solo el resultado
   numérico. Si origen y destino son de la MISMA cámara, no se muestra
   (esa comparación sí es justa: mismo video, mismo período) --
   idéntico al comportamiento de siempre para una sola cámara.

**Navegación**: `main.tienda_home` (`/tienda`) decide entre 3 vistas
según cuántas cámaras tiene la tienda elegida: 0 -> `tienda_empty.html`
(estado vacío con CTA a agregar la primera cámara), 1 -> redirect
DIRECTO a `/store/results?store=<camara>` (se salta el selector de
modo porque "combinada" y "por cámara" mostrarían lo mismo con una sola
cámara -- una elección sin sentido), 2+ -> `tienda_combinada.html`
con un selector real en el sidebar ("Vista combinada" + una pestaña
por cámara, reutilizando la clase `.tab-btn` ya existente sin CSS
nuevo). El asistente de configuración (`setup_routes.py`) no cambió su
lógica interna en absoluto -- lo único que cambió es que, al terminar,
la cámara resultante se registra automáticamente bajo la tienda actual
vía `tienda_service.add_camara_a_tienda()`. La ruta
`/tienda/<id>/nueva-camara` ofrece además "vincular una cámara
existente" (`get_camaras_sin_asignar()`) para agrupar retroactivamente
cámaras creadas antes de que existiera esta funcionalidad.

**Verificado end-to-end con Playwright + datos reales**: se creó una
tienda nueva (`tienda_qa_multi`), se vinculó `merl_demo` (cámara
preexistente, procesada antes de esta tarea) como primera cámara, y se
creó una segunda cámara genuinamente nueva (`camara_qa_dos`) corriendo
el asistente completo de punta a punta (subida real de
`data/raw/10_2_crop.mp4`, calibración real de una zona por clics de
mouse en el canvas, procesamiento real del pipeline con
`--skip-hands`, ~10.7 min). Con las dos cámaras procesadas (6 visitas
en `merl_demo`/"Snacks", 3 visitas en `camara_qa_dos`/"Zona camara
dos"), se confirmó en el navegador real:
- KPIs combinados correctos: 2 cámaras con resultados, 2 zonas, 9
  visitas totales (6+3), zona con más tráfico "Snacks" atribuida
  correctamente a `merl_demo`.
- Advertencia de comparabilidad visible (no oculta) en la vista
  combinada, en modo claro y oscuro (capturas de pantalla).
- Simulador multi-cámara: al elegir "Snacks" (`merl_demo`, referencia
  2026-09-02, 149s) como origen y "Zona camara dos" (`camara_qa_dos`,
  referencia 2026-09-05, 142s) como destino, el resultado numérico
  (-50% de cambio estimado, mismo cálculo que `simulate_move()`) vino
  acompañado de la advertencia con AMBAS fechas y AMBAS duraciones
  explícitas, sin errores de consola del navegador.
- Regresión: `/store/results?store=merl_demo` y
  `/store/results?store=camara_qa_dos` siguen renderizando su vista
  individual completa (7 secciones cada una: Historia, Mapas,
  Interacción, Tendencias, Simulador, Recomendaciones...) sin ningún
  cambio visible respecto a antes de esta tarea.
- Casos de 0 y 1 cámara probados por separado (tiendas de prueba
  descartables): 0 cámaras muestra el estado vacío; 1 cámara redirige
  directo a `/store/results`, sin selector de modo.

Se detectó y corrigió en el camino un import muerto
(`history_db.get_available_dates`, nunca usado) que había quedado en
`tienda_service.py` de un borrador anterior. Todos los datos de prueba
(`tienda_qa_multi`, `camara_qa_dos` y sus archivos generados en
`config/`, `data/output/` y `data/processed/`) se eliminaron al
terminar -- `config/tiendas.json` quedó en su estado original (sin
registro, equivalente a `{}`).

## 33. Bug: subir un video de reemplazo corrompía el de OTRA cámara (colisión de nombre de archivo)

Reportado como dos síntomas en `/setup?store=snaks` (tienda real
"demo", con cámaras `snaks`, `merl_demo`, `dulces`): (1) la vista
previa de un video ya subido se veía con controles pero sin miniatura,
0:00/0:00 de duración; (2) subir un video de reemplazo para una cámara
se quedaba "cargando" sin completar ni mostrar error.

**Causa raíz confirmada (una sola, para ambos síntomas)**:
`setup_routes.py:upload()` guardaba el video subido en
`os.path.join("data/raw", uploaded_file.filename)` -- usando el
NOMBRE DE ARCHIVO ORIGINAL tal cual lo entrega el navegador, sin
ningún namespacing por cámara. Si dos cámaras distintas se configuran
subiendo archivos locales con el mismo nombre (algo mucho más probable
ahora que la agrupación tienda -> cámaras invita a montar varias
cámaras de la misma tienda en una sola sesión, típicamente reusando el
mismo video de muestra) ambas terminan escribiendo al MISMO archivo
físico en disco. Se confirmó que esto YA había ocurrido en los datos
reales del proyecto: `zones_snaks.json` y `zones_merl_demo.json` tenían
el mismo `video_reference` (`data/raw/14_1_crop.mp4`) antes de esta
corrección.

Se reprodujo en vivo con Playwright: subir un archivo local llamado
igual para una segunda cámara sobreescribe silenciosamente (sin error,
en <1s) el archivo que la primera cámara sigue referenciando -- la
recarga de la primera cámara pasa a mostrar la duración/contenido del
video de la SEGUNDA cámara. Esto explica el síntoma 1 (una cámara
mostrando el video incorrecto, o un archivo a medio sobrescribir en el
peor caso de timing). El mismo problema de identidad compartida se
propagaba río abajo a los artefactos intermedios nombrados por el
basename del video en vez de por cámara (ej.
`data/processed/tracks_<basename>.csv`, usado por
`has_heat_preview` en `setup.html`) -- dos cámaras que comparten video
también terminaban compartiendo (o pisándose) su caché de vista previa
de calor.

Se investigó exhaustivamente una hipótesis de bloqueo/deadlock de
Windows para el síntoma 2 (dado el patrón de "procesos duplicados" ya
documentado en la sección 31) -- se confirmó experimentalmente que
sobrescribir un archivo mientras `cv2.VideoCapture` lo tiene abierto
(backend FFMPEG) NO bloquea ni lanza excepción en este entorno (la
escritura concurrente es silenciosamente permitida), y que el servidor
de desarrollo SÍ atiende requests largos de forma concurrente (dos
`trim()` síncronos de ~20s lanzados en simultáneo terminan en ~29s
combinados, no ~40s) -- descartando ambas como causa de un cuelgue
literal del request de subida. La causa confirmada y suficiente para
ambos síntomas es la colisión de identidad de archivo.

**Corrección**: en `dashboard/routes/setup_routes.py:upload()`, el
video se guarda ahora como `data/raw/<store_name><extensión original>`
-- namespaced por CÁMARA, nunca por el nombre de archivo que el
usuario haya usado localmente. Cada cámara es dueña exclusiva de su
propio archivo en disco, sin importar qué nombre tenía el archivo en
la máquina del usuario. `trim()` (`api_routes.py`) no necesitó cambios
-- deriva el nombre de su salida (`<basename>_recortado.mp4`) del
`input_path` que ya viene namespaced, así que hereda la corrección
automáticamente. Ningún otro punto del código guardaba archivos por
nombre original (se verificó con una búsqueda global de
`uploaded_file.filename`).

**Migración de los datos reales ya afectados**: `snaks` y `merl_demo`
(que compartían `data/raw/14_1_crop.mp4`) recibieron cada una su
propia copia independiente (`data/raw/snaks.mp4`,
`data/raw/merl_demo.mp4`); `dulces` se migró también por consistencia
(`data/raw/dulces.mp4`). Se actualizó el `video_reference` de cada
`config/zones_<camara>.json` -- las zonas calibradas y los resultados
ya procesados NO se tocaron (la calibración es válida contra el
contenido del video, que no cambió, solo su ruta canónica). Los
archivos de muestra originales (`data/raw/14_1_crop.mp4`,
`data/raw/1_2_crop.mp4`) se dejaron intactos, sin borrar, por si algo
más los referencia.

**Verificado con Playwright, sobre el fix real**:
- La vista previa de un video ya existente carga correctamente
  (duración real, sin 0:00) para `snaks` y `merl_demo` por separado,
  cada una con su propio archivo y duración independientes.
- Reemplazar el video de `snaks` con un archivo local llamado
  deliberadamente igual a uno usado antes para otra cámara ("colisión"
  simulada) ahora se guarda en `data/raw/snaks.mp4` -- completa en
  <1s (no se queda cargando) -- y `merl_demo` queda completamente sin
  afectar (misma duración de antes, verificado releyendo su página).
- Agregar una cámara nueva a la tienda real "demo" (flujo completo:
  `/tienda/demo/nueva-camara` -> asistente -> subir video) sigue
  funcionando sin cambios -- el video queda guardado como
  `data/raw/<id-de-la-cámara-nueva>.mp4` y la vista previa carga con
  la duración correcta. Cámara y archivos de prueba (`diag_nueva_camara`)
  se eliminaron al terminar.

## 34. Archivado histórico completo por fecha

Hasta esta sección, "guardar en el historial" (`--record-history`) solo
guardaba NÚMEROS AGREGADOS (zone_summary/interaction_summary) en
`history.db` -- los archivos "ricos" (heatmaps, eventos crudos, video
de verificación) vivían solo en `data/output/`/`data/processed/` y se
SOBREESCRIBÍAN en la siguiente corrida, así que era imposible ver "cómo
se veía el heatmap del 17 de agosto" una vez llegaba una corrida nueva.

**Qué se archiva, dónde, y qué se excluye deliberadamente**
(`pipeline/history_archive.py`, invocado desde `run_pipeline.py` justo
después de `history_db.record_run()`, en el mismo bloque
`--record-history`): una copia completa a
`data/history/<camara>/<fecha>/` con nombres GENÉRICOS (no atados al
basename del video, a diferencia de `data/output/`):

```
data/history/<camara>/<fecha>/
    zone_summary.csv
    interaction_summary.csv   (si existe -- no todas las corridas miden interacción)
    zone_events.csv
    interaction_events.csv    (si existe)
    heatmap_flujo.png
    heatmap_manos.png         (si existe)
    spaghetti.png
    zones.json                (copia de la calibración vigente en ese momento)
```

**NO se archivan los videos de verificación** (`tracked_preview_corregido_*.webm`,
`hands_preview_corregido_*.webm`) -- decisión deliberada, no un
descuido: (1) son una herramienta de control de calidad técnico ("¿se
siguió bien a cada persona?"), no contenido que el dueño de la tienda
necesite revisar por fecha histórica; (2) pesan ~decenas-cientos de MB
cada uno -- archivarlos en cada corrida habría vuelto insostenible el
crecimiento de `data/history/` con el tiempo. La vista histórica de
Mapas simplemente no ofrece el expander de video para una fecha
archivada, con un mensaje explícito ("no se archivan por fecha... para
verlo, procesa de nuevo esta cámara") en vez de fingir que "todavía no
existe".

**Vista histórica de solo lectura** (`main.results_historico`, ruta
`/store/results/historico?store=X&fecha=Y`): reusa el MISMO template
`results.html` y la MISMA lógica de negocio que la vista en vivo --
`main_routes.py` extrajo el cuerpo de `results()` a una función pura
compartida, `_build_results_context(...)`, que recibe los DataFrames y
las rutas de imagen YA RESUELTAS por el llamador (en vivo: `store_service.load_store_data()`
+ rutas de `data/output/`; histórico: `store_service.load_archived_store_data()`
+ rutas dentro de `data/history/<camara>/<fecha>/`) y arma exactamente
el mismo contexto en ambos casos. Ninguna lógica de negocio se
bifurca por `is_historical` -- solo la PROCEDENCIA de los datos
cambia. `storytelling.py` se refactorizó igual: `build_story(events_df, ...)`
es el núcleo puro, `get_story_data(store_name, ...)` es un envoltorio
que resuelve las rutas en vivo.

Dentro de la vista histórica: una franja/badge NARANJA, siempre
visible arriba del contenido ("Viendo resultados archivados del
{fecha} -- esta NO es la corrida más reciente...", con un link directo
de vuelta a la vista actual). El "Plano de la tienda" (`api.layout_plot`)
acepta un `?fecha=` opcional para colorear las zonas con el tráfico
DE ESA FECHA, no el actual. El Simulador, el reporte PDF y el
asistente de IA se DESHABILITAN con un mensaje explícito en la vista
histórica (los tres operan sobre `data/output/` en vivo vía sus
propios endpoints -- rehacerlos "históricos" habría requerido
duplicar esos endpoints sin que la tarea lo pidiera explícitamente).
Tendencias/el selector de fecha archivada SÍ se muestran igual en
ambas vistas (es una funcionalidad sobre `history.db` completo, no
sobre una corrida puntual).

**Selector de fecha archivada**: vive en la pestaña Tendencias (un
panel "Ver una fecha archivada" arriba de todo lo demás) -- criterio
propio, ver enunciado de la tarea. Un enlace en el propio banner
histórico permite volver.

**Verificado con Playwright + datos reales**: se procesó `snaks` DOS
veces (`--record-history --run-date 2026-08-01` y `2026-08-15`, ~10
min cada una, reusando su video ya calibrado) -- ambas corridas
generaron su carpeta en `data/history/snaks/<fecha>/` con los 8
archivos esperados (4 CSV + 3 PNG + zones.json), sin ningún `.webm`.
La vista histórica de `2026-08-01` mostró el banner correcto, un KPI
"Visitas totales" = 17 (coincide EXACTO con `zone_summary.csv`
archivado, no con el valor en vivo), el heatmap archivado sirvió
`200 OK`, Historia mostró la narrativa de esos eventos, el aviso de
"video no archivado" apareció, y el Simulador/PDF/IA se
deshabilitaron con su mensaje. "Volver a la vista actual" navegó
correctamente y el banner desapareció.

## 35. Gestión de datos (ver espacio + eliminar)

Nueva página `/store/datos?store=<camara>` (`dashboard/data_management_service.py`
+ `dashboard/templates/data_management.html`), enlazada desde la
navegación de `results.html` (ícono `database`) -- **todas las
acciones son destructivas y ninguna ocurre con un solo clic**: cada
botón "Eliminar" abre un `<dialog>` real (elemento nativo del
navegador, sin librería) que exige un segundo clic explícito de
"Sí, eliminar" antes de llamar al backend.

**Las 4 acciones, cómo funcionan y su confirmación**:
1. **Eliminar video(s) crudo(s)** -- borra el/los archivo(s) de
   `data/raw/` de esta cámara (el referenciado en `zones_<camara>.json`
   más cualquier variante `<camara>*` como un `_recortado`). Diálogo
   simple que ADVIERTE explícitamente: "sin él no se podrá reprocesar
   esta cámara hasta que subas uno nuevo".
2. **Eliminar resultados actuales** -- borra `data/processed/` +
   `data/output/` de esta cámara (resueltos por `camara_id` para los 4
   CSV/PDF, y por el basename del video de referencia para heatmaps/
   tracks/videos de verificación -- ver sección 33 sobre por qué esos
   dos esquemas de nombres conviven). Deja la cámara "calibrada pero no
   procesada", sin tocar el video crudo ni el historial archivado.
3. **Eliminar una fecha archivada** -- borra la carpeta de
   `data/history/<camara>/<fecha>/` Y la fila de `history.db` en la
   misma acción (`pipeline/history_archive.delete_archived_date()` +
   `pipeline/history_db.delete_run()`, nueva función agregada a
   `history_db.py` -- hasta ahora solo existían inserts/reads). Un
   botón por fila en la tabla de fechas archivadas.
4. **Eliminar cámara completa** -- irreversible: combina las 3
   anteriores + `config/zones_<camara>.json` + la quita del registro
   de su tienda (`tienda_service.remove_camara()`, función nueva).
   Exige escribir el NOMBRE EXACTO de la cámara en un input antes de
   habilitar el botón de confirmación (patrón común en herramientas
   reales para el borrado más peligroso) -- el backend vuelve a
   validar esa igualdad server-side, no confía solo en el frontend.

Los tamaños en disco son REALES (`os.path.getsize`/`os.walk`, nunca
estimados), calculados on-demand al cargar la página.

**Verificado con Playwright, con una cámara descartable
(`test_borrar`, video/zonas/resultados/fecha archivada de prueba, NO
datos reales)**: las 3 acciones simples borraron exactamente lo
esperado del disco (confirmado con `os.path.exists` después de cada
una); el diálogo de "eliminar cámara completa" mantuvo el botón de
confirmación DESHABILITADO al abrir y con un nombre incorrecto
escrito, y lo habilitó solo con el nombre exacto -- tras confirmar,
`config/zones_test_borrar.json`, el video, los resultados y la carpeta
de historial desaparecieron, `history.db` quedó sin filas para esa
cámara, y el navegador redirigió a `/tienda`. Además, sobre datos
REALES: se eliminó la fecha archivada de prueba `snaks/2026-08-15`
(una de las dos generadas para verificar la Parte 1) desde la página
real, confirmando que SOLO esa fecha desapareció (`2026-08-01` quedó
intacta tanto en disco como en `history.db`).

## 36. Tendencias agrupadas por semana/mes

`dashboard/trends.py:get_history_series_agrupada(store_name, agrupacion)`
-- análoga a la ya existente `get_history_series()` (que grafica cada
fecha suelta), pero agrupa TODAS las fechas de `history.db` por semana
ISO (`date.isocalendar()`) o por mes calendario, reutilizando
`get_available_dates()`/`get_zone_summary_for_date()` sin
reimplementar la lectura. Cada bucket agrega sus fechas con la función
correcta por métrica -- **visitas totales se SUMAN** (representan una
cantidad real acumulada en el período), **tasa de detención y
permanencia promedio se PROMEDIAN** (sumar dos porcentajes o dos
duraciones entre fechas distintas no significa nada). Devuelve la
MISMA forma que `get_history_series()` para alimentar el mismo
`<canvas>` de Chart.js sin lógica adicional, más `has_enough_buckets`/`n_buckets`.

**Selector Día/Semana/Mes** en la pestaña Tendencias: las 3
agrupaciones se calculan TODAS server-side en cada carga de página
(volumen de datos pequeño, evita un endpoint AJAX nuevo) y se
embeben juntas en un solo `<script type="application/json">`;
`results.js:initTrendsChart()` reconstruye el `<canvas>` con la
agrupación elegida sin recargar la página.

**Caso de pocos datos, manejado explícitamente (no un gráfico vacío ni
engañoso)**: si al agrupar por semana o mes quedan MENOS DE 2 buckets
distintos, se oculta el `<canvas>` y se muestra un mensaje honesto
("Hace falta más historial acumulado para ver la tendencia por
semana/mes... probá con 'Día' mientras tanto"), citando cuántos
buckets hay hoy. La opción "Día" nunca se ve afectada por este
chequeo (ya está protegida por el gate existente de "se necesitan al
menos 2 fechas guardadas" de más arriba en la misma pestaña).

**Verificado con Playwright, con datos reales de `snaks`**: con 2
fechas casi consecutivas (2026-09-05, 2026-09-06 -- misma semana ISO,
mismo mes), tanto "Semana" como "Mes" mostraron el mensaje honesto
("1 semana(s) distinto(s)... se necesitan al menos 2"), sin gráfico.
Tras agregar 2 fechas más distantes (2026-08-01, 2026-08-15), "Mes"
mostró un gráfico real de 2 buckets (agosto + septiembre) y "Semana"
uno de 3 buckets -- confirmado también que "Día" nunca dejó de
funcionar durante estas pruebas.

## 37. Nota de mantenimiento encontrada de paso: heatmaps huérfanos por la migración de la sección 33

Al calcular tamaños en disco para la Parte 2 (sección 35) se detectó
que `merl_demo` y `dulces` reportaban un tamaño de "resultados
actuales" sospechosamente bajo (0.0-1.0 MB). Causa: la migración de la
sección 33 (namespacing del video subido) copió el VIDEO de cada
cámara a su nuevo nombre y actualizó `video_reference`, pero NO movió
los heatmaps/diagrama de espagueti ya generados -- esos siguen
nombrados por el basename del video VIEJO (`heatmap_14_1_crop.png`,
`heatmap_1_2_crop.png`), ahora huérfanos e invisibles tanto para la
pestaña Mapas como para este cálculo de tamaño. Se corrigió copiando
(no moviendo, para no perder el original) esos 3 PNG por cámara a su
nombre namespaced actual (`heatmap_merl_demo.png`, `heatmap_dulces.png`,
etc.) -- una reparación de datos puntual, no un cambio de código
(cualquier cámara reprocesada DESDE la sección 33 en adelante ya
genera sus artefactos con el nombre correcto de una sola vez).

## 38. Retiro completo del Asistente de IA (Groq) de la pestaña Recomendaciones

Se eliminó por completo la funcionalidad documentada en las secciones 20
y 21 (`dashboard/ai_advisor.py`, sus 4 endpoints en
`dashboard/routes/api_routes.py`, la sección "Asistente de IA (opcional)"
de `templates/results.html`, la lógica de UI correspondiente en
`static/js/results.js`, el guardado encriptado en `.secrets/`, y las
dependencias `requests`/`cryptography` de `requirements.txt`). Esta
sección documenta el retiro; las secciones 20 y 21 se dejaron intactas
(con una nota cruzada hacia esta) como registro histórico de por qué se
construyó originalmente.

**Razón del retiro**: se determinó innecesaria -- el motor de reglas
(`dashboard/ai_insights.py`) ya cubre por completo la necesidad de
generar recomendaciones (diagnóstico + sugerencia por zona, resumen
ejecutivo, tabla de métricas, reporte PDF), sin depender de un servicio
externo (Groq) ni de que el usuario consiga, pegue y administre una API
key. La sección 20 ya había sido explícita en que esto era un extra de
redacción y no una pieza necesaria del análisis (`ai_insights.py` sigue
siendo, como siempre, la única fuente real del diagnóstico de negocio) --
retirar el extra no le quita nada a esa pieza central.

**Qué se conservó, sin ningún cambio**: el motor de reglas
(`ai_insights.py`), el resto de la pestaña Recomendaciones (tarjetas de
diagnóstico/sugerencia por zona, resumen ejecutivo, tabla completa de
métricas, botón de reporte PDF), y el widget de ayuda flotante (FAQ) --
se revisaron sus 8 respuestas y ninguna mencionaba el Asistente de IA.

**Qué se verificó explícitamente antes de borrar cada pieza** (para no
romper nada compartido):

- `requests` y `cryptography` en `requirements.txt`: se confirmó por
  búsqueda en todo `dashboard/` y `pipeline/` que ningún otro módulo los
  importa -- solo `ai_advisor.py` los usaba. Se quitaron ambas líneas
  (junto con su comentario) sin dejar nada huérfano.
- CSS: la sección "Asistente de IA" en `results.html` solo usaba clases
  genéricas ya compartidas por el resto de la app (`.panel`,
  `.form-field`, `.btn`, `.btn-sm`, `.btn-danger`, `.btn-primary`,
  `.caption`) -- no existía ninguna regla CSS dedicada a este componente
  en `main.css`, así que no hubo nada que borrar ahí.
- `import ai_insights` en `dashboard/routes/api_routes.py` quedó sin uso
  tras quitar el endpoint `/api/store/<store_name>/ai-advisor/generate`
  (era el único lugar de ese archivo que lo llamaba) -- se quitó ese
  import puntual; el módulo `ai_insights.py` en sí NO se tocó y sigue
  siendo importado normalmente por `main_routes.py` y
  `report_generator.py`.
- `simpleMarkdownToHtml()` en `results.js` solo la usaba el resultado del
  Asistente de IA -- se borró junto con `initAiAdvisor()`.
  `escapeHtml()`, en cambio, la sigue usando el Simulador -- se dejó
  intacta.
- `.secrets/` (carpeta en disco, solo contenía `NO_COMPARTIR.txt`; no
  había ninguna key de prueba guardada) y su entrada en `.gitignore`: se
  confirmó que ningún otro módulo del proyecto lee ni escribe en
  `.secrets/` antes de borrar la carpeta y quitar la entrada.

**Espaciado en `results.html`**: la sección eliminada era el último
bloque dentro de `<section id="tab-recomendaciones">`, envuelto en su
propio `{% if not is_historical %}...{% endif %}` -- se quitó el bloque
completo y la pestaña vuelve a terminar en el `<details>` de "Ver tabla
completa de métricas", con el mismo margen inferior que ya traía ese
componente (`details.expander { margin-bottom: var(--space-4); }` en
`main.css`); no hizo falta ningún ajuste manual de espaciado.

## 39. Dockerización -- CPU por defecto, modelos horneados en la imagen

Se agregó soporte para correr el proyecto completo con Docker (`Dockerfile`,
`docker-compose.yml`, `.dockerignore`, `DOCKER.md`), pensado explícitamente
para la demo del hackathon: que cualquier máquina con Docker Desktop pueda
levantar el sistema con un solo comando, sin instalar Python/PyTorch/OpenCV
a mano, y sin depender de conexión a internet durante la demo en sí.

**Decisión: CPU por defecto, GPU como variante opcional documentada.**
`requirements.txt` no fija versión de PyTorch a propósito (funciona
tenga o no GPU la máquina, ver el comentario ya existente ahí desde
antes de Docker). Puesto en un `Dockerfile`, eso mismo sin más cuidado
resolvería en Linux la build de PyTorch con binarios CUDA embebidos
-- pesa gigabytes de más aunque la máquina no tenga GPU. El `Dockerfile`
principal instala explícitamente la build CPU-only desde el índice
oficial de PyTorch (`--index-url https://download.pytorch.org/whl/cpu`)
ANTES de `pip install -r requirements.txt`, para que esa dependencia
transitiva de `ultralytics` ya llegue satisfecha. Es el único camino
que se prueba a fondo y el que arranca `docker-compose.yml` sin ninguna
bandera especial -- pedir GPU en una máquina que no la tiene hace que el
contenedor no arranque en absoluto, algo inaceptable para una demo en
una laptop que no se controla de antemano.

**Modelos YOLO horneados en la imagen, no descargados en el primer
arranque.** El `Dockerfile` ejecuta, en tiempo de *build*:
`python -c "from ultralytics import YOLO; YOLO('yolo26n.pt'); YOLO('yolov8n-pose.pt')"`
-- los dos únicos modelos que usa la cadena de producción real
(confirmado leyendo `pipeline/run_pipeline.py`, lo que
`dashboard/job_manager.py` termina lanzando al presionar "Procesar
video"; ver sección 16 para la decisión de modelo original).
`ultralytics.YOLO(...)` descarga el peso oficial la primera vez que se
instancia si no lo encuentra en cache -- forzar esa descarga en build
time (no en el primer uso real) es lo que garantiza que el contenedor
nunca necesite internet para procesar un video, ni la primera vez ni
ninguna después. `config/` y `data/` (incluyendo `data/output/history.db`)
se montan como volúmenes en `docker-compose.yml` -- nunca se hornean en
la imagen -- para que persistan entre reinicios y reconstrucciones de la
imagen.

**Bug real encontrado al dockerizar, no visible en desarrollo local:**
`requirements.txt` no incluía `lap` (el solver de asignación lineal que
usa el tracker ByteTrack de `ultralytics`, invocado desde
`pipeline/detect_and_track.py` y `pipeline/detect_hand_positions.py` vía
`model.track(...)`). En local nunca se notó porque `ultralytics` lo
resuelve con su propio mecanismo de "AutoUpdate": la primera vez que
hace falta, intenta un `pip install lap` automático en pleno
procesamiento -- silenciosamente exitoso en cualquier máquina de
desarrollo con internet, y de hecho así había quedado instalado en el
entorno virtual local sin que nadie lo agregara a mano a
`requirements.txt`. Construir la imagen Docker desde cero (sin ese
"acarreo histórico" del venv de desarrollo) expuso el problema de
inmediato: la primera corrida real del pipeline dentro del contenedor
intentaba descargar `lap` de internet a mitad de "Procesar video" --
exactamente el escenario que la imagen con modelos horneados existe
para evitar (una demo sin WiFi confiable se habría colgado ahí). Se
agregó `lap>=0.5.12` (la versión exacta que pidió el AutoUpdate) a
`requirements.txt`, y se reconstruyó y re-verificó la imagen de punta a
punta para confirmar que ya no aparece ningún intento de instalación en
tiempo de ejecución.

**Otra cosa notada, no un problema:** el pipeline sigue emitiendo el
warning `OpenCV: FFMPEG: tag 0x30385056/'VP80' is not supported with
codec id 139` durante la generación de los videos `.webm` de
verificación -- este es el mismo warning ya diagnosticado y confirmado
inofensivo antes de Docker (ver sección sobre el bug de códec de video,
más arriba en este documento): a pesar del mensaje, `libvpx` sí codifica
VP8 válido dentro del Dockerfile de este proyecto también (se confirmó
inspeccionando los `.webm` resultantes: tamaño y reproducción
correctos). No es una regresión de Docker, solo el mismo ruido ya
conocido apareciendo también dentro del contenedor.

**Verificación real hecha (no solo "el Dockerfile se ve bien"):**
build de la imagen CPU con `docker build` (647-648MB finales, medido con
`docker save | wc -c`, no con la columna `SIZE` de `docker images` --
esa columna cuenta capas compartidas de forma que puede inflar el
número visualmente cuando el mismo build queda taggeado dos veces, como
pasó acá entre el `docker build` manual y el `docker-compose build`);
contenedor levantado con `docker-compose up`, servidor respondiendo en
`localhost:5000`; un video real subido, recortado, calibrado (vía
`POST /api/store/<store>/save-zones`, el mismo endpoint que usa el
canvas de calibración -- se optó por esto en vez de automatizar clics
de canvas) y procesado de punta a punta DENTRO del contenedor (los 11
pasos del pipeline, cuerpo + manos, sin fallos de dependencias,
generando resultados reales no triviales: 1 visita, 1 detención, 1
interacción de producto detectada); `docker-compose down` + `up`
confirmado sin pérdida de datos, con checksums (`md5sum`) idénticos
antes y después tanto en `config/zones_*.json` como en
`data/output/zone_summary_*.csv`, y la página de resultados sirviendo
esos mismos datos después del reinicio.

**Variante GPU:** documentada en `DOCKER.md` como secundaria/opcional,
con un `Dockerfile.gpu` separado (base `nvidia/cuda:12.4.1-runtime-ubuntu22.04`
+ Python 3.13 vía deadsnakes + PyTorch con CUDA 12.4). Se construyó con
éxito (~8.0 GB, medido con `docker inspect`) y se verificó, corriendo el
contenedor con `docker run --gpus all`, que `torch.cuda.is_available()`
devuelve `True` y reconoce correctamente la RTX 3050 de la máquina de
desarrollo, y que el dashboard Flask arranca igual que en la imagen CPU.
No se corrió el pipeline completo de 11 pasos con esta variante (sí con
la CPU) -- alcance acotado a propósito por tratarse de un camino
secundario. Dos bugs reales aparecieron y se corrigieron al construirla
por primera vez (quedan documentados como comentarios en
`Dockerfile.gpu` y en `DOCKER.md`): (1) sin `DEBIAN_FRONTEND=noninteractive`,
`apt-get install` se queda colgado indefinidamente esperando un prompt
interactivo de `tzdata` que nunca llega en un build no interactivo --
no falla, cuelga, que es más difícil de diagnosticar; (2) la imagen
base de NVIDIA trae `blinker` preinstalado por `apt` como paquete de
sistema (distutils), y `pip install -r requirements.txt` se cuelga (de
nuevo, no falla limpio) al intentar reemplazarlo por la versión que
pide `flask` -- se resolvió agregando `--ignore-installed` a ese
`pip install` (solo en el Dockerfile GPU; el Dockerfile CPU parte de
una imagen `python:3.13-slim` limpia, sin este conflicto, así que no
lo necesita).

## 40. Selección automática CPU/GPU (confirmada, no nueva) + optimización OpenVINO con red de seguridad de dos capas

Continuación de la sección 39 -- tres piezas nuevas sobre la
dockerización: confirmar que la selección de dispositivo del pipeline
nativo ya era automática, convertir los modelos a OpenVINO en el build
con una red de seguridad verificada de verdad (incluyendo un fallo real
encontrado en desarrollo), y automatizar la elección CPU/GPU de Docker
con `docker-run.sh`/`docker-run.ps1`.

**1. Selección automática CPU/GPU del pipeline nativo -- ya existía,
sin código nuevo.** Se revisó `pipeline/detect_and_track.py` y
`pipeline/detect_hand_positions.py`: ninguno de los dos pasa `device=`
a `YOLO(...)` ni a `.track(...)`. Se confirmó leyendo el código fuente
instalado de Ultralytics (`venv/Lib/site-packages/ultralytics/utils/torch_utils.py`,
función `select_device()`) que su docstring dice textualmente
*"Defaults to auto-selecting the first available GPU, or CPU if no GPU
is available"* -- y `ultralytics/cfg/default.yaml` confirma `device:`
vacío por defecto. No hizo falta agregar ninguna lógica: si estos
mismos scripts corren en una máquina/imagen con PyTorch+CUDA
disponible (ej. `Dockerfile.gpu`), usan la GPU automáticamente; si no,
usan CPU. Esto es ortogonal y no se confunde con el punto 3 de abajo
(elegir qué IMAGEN de Docker levantar), que sí es código nuevo.

**2. Conversión a OpenVINO en build-time (`pipeline/export_openvino.py`)
con red de seguridad de DOS capas.** `yolo26n.pt` y `yolov8n-pose.pt`
(los mismos dos modelos de la sección 16/39) se convierten a formato
OpenVINO (IR) durante el build del `Dockerfile`, igual principio que el
horneado de los `.pt`: nunca en el primer arranque del contenedor.

La conversión es explícitamente una optimización, nunca una dependencia
dura -- `export_openvino.py` SIEMPRE sale con código 0 pase lo que pase
(atrapa cualquier excepción por modelo, loguea, sigue). En tiempo de
inferencia, `load_model()` (definida en `detect_and_track.py`, importada
por `detect_hand_positions.py`) revisa si existe
`<modelo>_openvino_model/`; si no existe, o existe pero falla al
`YOLO(directorio)` (try/except), cae al `.pt` original.

**Por qué DOS capas y no una sola con try/except**: probando esto en
desarrollo (Windows, fuera de Docker), cargar el modelo OpenVINO y
correr `.track()` con ByteTrack produjo un **segfault real** (el
proceso de Python moría con código de salida 139, no una excepción
manejable) -- confirmado reproducible tanto en un script combinado como
en un proceso Python nuevo dedicado solo a esa llamada. Un
`try/except` de Python **no puede atrapar una caída nativa del
intérprete**. Por eso la segunda capa vive un nivel más arriba, a nivel
de PROCESO: `pipeline/run_pipeline.py:run_step()` y
`dashboard/job_manager.py:start_job()` (este último para la vista
previa de calor, que llama a `detect_and_track.py` fuera de
`run_pipeline.py`) reciben un `retry_env` opcional
(`{"DISABLE_OPENVINO": "1"}`); si el subproceso de detección termina
con código de salida distinto de cero -- por CUALQUIER motivo, excepción
Python o señal nativa -- se reintenta UNA vez con esa variable de
entorno, que le dice a `load_model()` que ni intente el directorio
OpenVINO. Curiosamente, el mismo modelo OpenVINO NO reprodujo el
segfault corriendo dentro del contenedor Linux (ver mediciones abajo,
funcionó sin problema) -- pero la causa raíz real (conflicto de
threading/runtime nativo entre el backend de OpenVINO y el de
PyTorch/MKL en ciertas configuraciones) es exactamente la clase de
fallo impredecible entre plataformas que justifica tener la red de
DOS capas siempre activa, no solo en la plataforma donde se reprodujo.

**Prueba real de la red de seguridad de build-time** (fallo forzado a
propósito, no simulado): se construyó
`docker build --build-arg OPENVINO_EXPORT_FORMAT=formato_invalido_de_prueba -t retail-vision-mvp:cpu-broken-openvino .`
-- `export_openvino.py` recibe ese formato inválido vía la variable de
entorno del mismo nombre (existe justamente para esto). Resultado real:
ambos modelos fallaron con `ValueError: Invalid export format=...`
(logueado), **el build terminó en código 0** igual que siempre, la
imagen se construyó completa. Un contenedor levantado desde ella: no
tiene ningún `*_openvino_model/`; arranca el dashboard normal; y
corriendo `detect_and_track.py` sobre el mismo video de prueba,
procesó de punta a punta sin ningún error visible, en silencio con el
`.pt` original (ni un mensaje de `[OpenVINO]` en el log, porque
`load_model()` ni intenta cargarlo si el directorio no existe),
produciendo el resultado **idéntico**: 69 detecciones, 3 IDs únicos.

**Tiempos reales medidos DENTRO del contenedor** (clip de 15s/449
frames, `detect_and_track.py`, cuerpo solamente, Intel Core i5-10300H;
2 corridas limpias por configuración, sin otros builds de Docker
compitiendo por CPU en simultáneo -- una medición inicial bajo carga
concurrente dio 315s para el camino sin OpenVINO, un outlier de
contención de recursos que se descartó y no se reporta como real):

| Configuración | Corrida 1 | Corrida 2 | Promedio |
|---|---|---|---|
| Con OpenVINO | 43.1s | 35.5s | 39.3s |
| Sin OpenVINO (`.pt` puro) | 57.5s | 73.6s | 65.6s |

Speedup real ~1.7x (rango 1.3x-2.1x), consistentemente a favor de
OpenVINO en las 4 mediciones.

**Equivalencia de detección**: comparando los CSV de tracks fila por
fila entre ambas configuraciones sobre el mismo video -- mismo número
de filas (69=69), secuencia `frame`+`track_id` **idéntica** en las 69
filas (mismo tracking, mismos IDs, mismo orden), y coordenadas de caja
con diferencia máxima de 4.5px / promedio 0.2px (variación numérica
esperable de la conversión de formato, sin impacto práctico observado).

**3. `docker-run.sh` / `docker-run.ps1`: selección automática de imagen
Docker (CPU vs. GPU).** Código nuevo, distinto del punto 1. Ambos
scripts prueban el passthrough de GPU DE VERDAD (no solo si existe el
binario `nvidia-smi`) con
`docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`;
si funciona, levantan `docker-compose.gpu.yml` (nuevo, ver abajo); si
no, `docker-compose.yml` (CPU, sin cambios). Se agregó también
`docker-compose.gpu.yml` -- una corrección real sobre lo que decía la
sección 39 (y un primer borrador de `DOCKER.md`): ahí se afirmó que
Compose "clásico" no soporta pedir GPU sin un plugin aparte de NVIDIA.
Se probó de verdad y eso era **incorrecto** -- el bloque estándar
`deploy.resources.reservations.devices` de la Compose Specification
funciona sin ningún plugin extra con Docker Desktop + Compose v2
(`docker compose -f docker-compose.gpu.yml up --build`): el contenedor
arranca, `torch.cuda.is_available()` da `True`, reconoce la RTX 3050
correctamente, y el dashboard responde igual que con `docker run`
directo (que también se dejó documentado como alternativa). Se
corrige acá para que el historial de decisiones quede preciso: `docker
run` no era la única forma práctica, solo la primera que se probó.

## 41. Efecto "Liquid Glass" completo (`backdrop-filter`), incluida la barra lateral

Portado desde `main.css` del proyecto de prueba (`diseño-prueba`), a
pedido explícito del usuario -- esta vez incluyendo la barra lateral,
revirtiendo la restricción de una tarea anterior ("la sidebar se queda
oscura tal cual") porque el usuario decidió que ahora quiere ver el
resultado completo antes de aprobar o descartar el costo de rendimiento
del blur.

**1. Discrepancia entre la descripción de la tarea y el archivo de
referencia real -- se siguió el archivo, no la paráfrasis.** El pedido
mencionaba `backdrop-filter` en tarjetas KPI, tarjeta destacada,
category-cards y tablas. Al releer `main.css` de `diseño-prueba` línea
por línea (sección "LIQUID GLASS"), el blur real solo se aplica a
`.sidebar`, `dialog.confirm-dialog`, `.theme-toggle`, `.sidebar
.tab-btn.active` y `.btn-primary:not(:disabled)`. Las tarjetas KPI,
`.panel` y `.progress-card` se mantienen explícitamente OPACAS
(`background: var(--color-panel)`, sin filtro) en la propia referencia.
Se replicó el archivo real, no la descripción del pedido, para no
inventar un efecto que el diseño de referencia no tiene.

**2. `.btn-primary` y `.dm-switch` quedaron fuera del blur a propósito.**
`.btn-primary` tiene `background-color` 100% opaco -- aplicarle
`backdrop-filter` no produce ningún cambio visible (el filtro solo actúa
sobre lo que se ve A TRAVÉS del elemento, y con opacidad 100% no hay
nada que atravesar), así que se omitió en vez de copiar una regla sin
efecto. `.dm-switch` (el interruptor de tema animado portado en la tarea
anterior) reemplazó por completo al `.theme-toggle` original de la
referencia; al ser un widget ilustrado pequeño y no una superficie de
"vidrio", no se le aplicó blur.

**3. Reversión de `--sidebar-bg` y variables asociadas a tokens
compartidos.** `--sidebar-bg`, `--sidebar-bg-alt`, `--sidebar-text`,
`--sidebar-text-muted`, `--sidebar-border`, `--sidebar-chip-bg`,
`--sidebar-active-bg` y `--sidebar-accent` dejaron de ser hex fijos
oscuros y ahora derivan de los 19 tokens compartidos (`--color-panel`,
`--color-ink`, etc.) en los tres bloques de tema (`:root`,
`[data-theme="dark"]`, fallback `prefers-color-scheme`). Nuevos tokens
`--glass-surface`/`--glass-control`/`--glass-edge`/`--glass-shadow` se
definen a partir de `--color-panel` con `color-mix()`, con una capa
`@supports` que solo los hace translúcidos si el navegador soporta
`backdrop-filter`, y un fallback `@media (prefers-reduced-transparency:
reduce), (prefers-contrast: more)` que los fuerza de vuelta a opacos.

**4. El fondo general de página necesitó más color del que tenía --
hallazgo real de inspección visual, no supuesto.** El blur solo es
perceptible si hay algo con contraste de color detrás. La primera
versión de `body{}` agregó dos manchas radiales de color
(`color-mix(in srgb, var(--color-accent) 22%, transparent)` y
`var(--color-hot) 14%`) más una textura de puntos. Al generar e
inspeccionar personalmente las 8 capturas de Playwright, el efecto se
veía claro en modo oscuro pero casi imperceptible en modo claro (una
mancha blanca/pastel sobre panel casi blanco no genera contraste
suficiente). Se subieron las intensidades a 45%/32%, se agrandaron los
radios (760px/620px) y se reposicionó la mancha superior (10%/25%) para
cubrir mejor la altura de la barra lateral. Tras corregir, se
regeneraron y re-inspeccionaron las 8 capturas: el efecto ahora es
claramente visible en ambos modos sin volverse excesivo en modo oscuro.

**5. Verificación:** 8 capturas Playwright en `docs/screenshots/`
(`liquid-glass-{combinada,resumen,mapas,setup}-{claro,oscuro}.png`,
inspeccionadas una por una) más una captura adicional del diálogo de
confirmación con vidrio (`liquid-glass-dialogo-ejemplo.png`). Prueba
funcional automatizada tras el cambio: Simulador, Gestión de datos,
diálogo de confirmación y carga de calibración siguen funcionando, cero
errores de consola.

## 42. Fondo tintado por color en las tarjetas KPI no destacadas (vista combinada y vista de una cámara)

Antes de este cambio, de las 4 tarjetas de cualquier `.kpi-row`, solo la
tarjeta "hero" (la primera, ver sección 22) tenía fondo con color
propio -- las otras 3 seguían con `background: var(--color-panel)`
liso, y únicamente su ícono llevaba color. El pedido: extender el MISMO
color que cada ícono ya tiene (no inventar una asignación nueva) a un
lavado suave sobre toda la tarjeta.

**1. Asignación de color por tarjeta -- derivada del ícono que YA
estaba, no reinventada.** Cada `.kpi-card` no-hero ya trae adentro un
`.kpi-icon-chip-{zonas,visitas,interacciones,top}`, y esas 4 clases ya
mapean a `--accent-zonas` (`--color-info`, azul), `--accent-visitas`
(`--color-success`, verde), `--accent-interacciones` (`--color-warning`,
ámbar) y `--accent-top-zona` (`--color-ink-muted`, gris neutro) --
ver línea 953 y siguientes. En vez de re-derivar el color por posición
o por texto de la etiqueta (que además NO coinciden 1:1 entre vistas:
p. ej. en `tienda_combinada.html` la tarjeta con la etiqueta "Zonas
monitoreadas" usa la clase de ícono `kpi-icon-chip-visitas`, verde --
son slots de color reutilizados entre páginas, no nombres semánticos
por vista), se detecta el color por el propio icon-chip anidado con el
selector `:has()`:
```css
.kpi-row .kpi-card:not(:first-child):has(.kpi-icon-chip-zonas) {
    background: color-mix(in srgb, var(--accent-zonas) var(--category-tint-pct), var(--color-panel));
}
/* ...mismo patrón para -visitas, -interacciones, -top */
```
Esto hace que el tinte funcione igual en `tienda_combinada.html` Y en
`results.html` (la vista de una sola cámara) SIN tocar ningún HTML --
ambas plantillas ya traían las clases de ícono correctas, la única
plantilla que sí se tocó en la tarea anterior (la de la cuadrícula en
"L") fue `tienda_combinada.html`, y ni siquiera hizo falta agregarle
nada nuevo para este cambio.

**2. Mecanismo de tinte: reutilizado, no inventado.** `color-mix(in
srgb, COLOR var(--category-tint-pct), var(--color-panel))` es
exactamente el mismo mecanismo (y el mismo token de porcentaje) que ya
usan las `.category-card` (sección de zonas hot/cold/paso/nicho) --
`--category-tint-pct` ya estaba calibrado por tema (12% claro, 20%
oscuro, con nota explícita de que en oscuro hace falta más % para
notarse igual). Se reutilizó tal cual en vez de crear un token nuevo
solo para estas tarjetas.

**3. Ajuste de contraste real encontrado, no asumido.** El pedido pedía
confirmar (no asumir) que `--color-ink` seguía funcionando para el
texto. Verificación WCAG (mismo método/fórmula que el resto del
archivo): `--color-ink` (el que ya usa `.kpi-value`) sobre los 4 fondos
tintados da 14.34-14.46:1 en claro y 9.97-10.36:1 en oscuro -- de sobra.
PERO `.kpi-label`/`.caption` usan `--color-ink-muted`, no `--color-ink`
-- y ESE color sobre los mismos fondos da 4.88-4.93:1 en claro (bien) y
apenas **4.50:1 y 4.51:1** en oscuro para las tarjetas ámbar/verde --
pasa AA (4.5:1) por un margen demasiado ajustado para confiar en
redondeos del motor de renderizado. Se corrigió llevando
`.kpi-label`/`.caption` a `--color-ink` completo en las tarjetas
no-hero (`.kpi-row .kpi-card:not(:first-child) :is(.kpi-label,
.caption) { color: var(--color-ink); }`) -- el mismo criterio que ya
usan las `.category-card`, que tampoco usan ink-muted para su texto
sobre un fondo tintado.

**Ratios de contraste verificados (texto sobre cada fondo tintado)**:

| Tarjeta (color derivado del ícono) | Claro -- `--color-ink` (valor) | Claro -- `--color-ink` (label/caption, ya corregido) | Oscuro -- `--color-ink` (valor) | Oscuro -- `--color-ink` (label/caption, ya corregido) |
|---|---|---|---|---|
| zonas (`--color-info`, azul) | 14.46:1 | 14.46:1 | 10.36:1 | 10.36:1 |
| visitas (`--color-success`, verde) | 14.34:1 | 14.34:1 | 9.99:1 | 9.99:1 |
| interacciones (`--color-warning`, ámbar) | 14.34:1 | 14.34:1 | 9.97:1 | 9.97:1 |
| top-zona (`--color-ink-muted`, gris) | 14.46:1 | 14.46:1 | 10.33:1 | 10.33:1 |

(La columna "ya corregido" es igual a la del valor porque, tras el
punto 3, todo el texto de estas tarjetas usa `--color-ink` -- antes de
corregir, label/caption daban 4.88-4.93:1 en claro y 4.50-4.51:1 en
oscuro con `--color-ink-muted`.)

**4. Verificación:** Playwright, 2 vistas (`tienda_combinada.html` y
`results.html`) x 2 temas -- confirmado por `getComputedStyle` que las
3 tarjetas no-hero tienen `background-color` computado DISTINTO entre
sí (no solo el ícono), capturas guardadas en `docs/screenshots/`
(`kpi-tint-{combinada,resumen}-{claro,oscuro}.png`) e inspeccionadas
una por una. Simulador y Gestión de datos siguen funcionando, cero
errores de consola.

**5. Nota sobre un error propio de estructura del documento, corregido
en esta misma ronda.** La sección "Efecto Liquid Glass" de la tarea
anterior se había insertado por error A MITAD de la sección 40 (el
`old_string` de aquel `Edit` coincidió con una tabla que parecía el
final del archivo, pero la sección 40 en realidad seguía más abajo con
el punto 3 de Docker, cortando incluso una oración de esa sección por
la mitad). Se detectó al correr `wc -l` para confirmar el fin real del
archivo antes de escribir esta sección nueva, y se recompuso la
oración partida y se reubicó el contenido completo de "Liquid Glass"
a su lugar correcto (quedó como sección 41, justo arriba de esta), sin
perder ni alterar su contenido.

## 43. Nuevo interruptor de tema (luna con cráteres, nubes y estrellas SVG) -- reemplaza el diseño anterior, más chico

El usuario trajo un componente distinto de Uiverse.io (by Galahhad) para
reemplazar el interruptor sol/luna con nubes CSS de la sección 27 --
mismo propósito (cambiar `data-theme`), otra metáfora visual (luna con
cráteres en vez de sol con resplandor), esta vez con nubes/estrellas
reales (divs + SVG) en vez de gradientes CSS puros.

**1. El enganche con `main.js` no cambió.** `initThemeToggle()` solo
busca `document.getElementById("darkmode-toggle")` y usa `.checked` +
evento `change` -- no depende de ninguna clase ni de la estructura
interna del componente. Se agregó `id="darkmode-toggle"` al
`<input type="checkbox" class="sky-toggle__checkbox">` del HTML nuevo y
`main.js` no se tocó (más allá de un comentario desactualizado que
mencionaba `.dm-switch`, corregido de paso).

**2. Colisión de nombre real, resuelta renombrando el componente
nuevo.** `.theme-switch` YA existía en el proyecto -- era el `<div>`
contenedor genérico (`display:inline-flex`, `flex-shrink:0`) del
interruptor anterior, en `layout.html`. El componente de Uiverse usa
`.theme-switch` como nombre de bloque BEM para TODO (`.theme-switch`,
`.theme-switch__container`, `.theme-switch__clouds`, etc.). Se
renombró el bloque completo del componente nuevo a `.sky-toggle` (`
.sky-toggle`, `.sky-toggle__checkbox`, `.sky-toggle__container`, ...)
en vez de tocar el nombre viejo -- no hacía falta un `<div>` contenedor
aparte: el `<label class="sky-toggle">` del componente nuevo YA es el
elemento raíz clickeable, así que reemplaza de una sola vez tanto al
`<div class="theme-switch">` como al `<label class="switch-control">`
que existían antes. El `flex-shrink: 0` que evitaba que el interruptor
se comprimiera dentro del `.brand-row` (flex, `justify-content:
space-between`) se movió directamente a `.sky-toggle`.

**3. Tamaño: se redujo `--toggle-size` de 30px (valor por defecto del
componente) a 16px.** Todo el CSS interno usa `em`, heredado de
`font-size: var(--toggle-size)` -- a 30px el contenedor medía
`5.625em x 2.5em` = ~169x75px, dominaba el encabezado de la sidebar. A
16px resuelve a 90x40px exactos (confirmado con
`getBoundingClientRect()` vía Playwright, no solo calculado a mano),
dentro del rango pedido (79-101 x 35-45) y visualmente bien
proporcionado junto al título "Space Management" en ambos temas (ver
capturas de verificación, punto 5).

**4. Único agregado fuera del CSS "tal cual" que trajo el usuario:**
una regla `:focus-visible` (`.sky-toggle__checkbox:focus-visible +
.sky-toggle__container { outline: ...; }`) para no perder el indicador
de foco de teclado que sí tenía el interruptor anterior -- el
componente de Uiverse tal cual no trae ninguno. No cambia la
apariencia por defect/hover/click, solo agrega un contorno visible al
navegar con Tab.

**5. Verificación:** Playwright -- tamaño renderizado real 90x40px;
clic sobre el `<label>` completo cambia `data-theme` en `<html>` y
`localStorage['theme']` en ambas direcciones (claro→oscuro→claro);
capturas de `.brand-row` y de la sidebar completa en ambos temas
(`docs/screenshots/sky-toggle-{brand-row,sidebar}-{claro,oscuro}.png`)
confirmando visualmente sol+nubes en claro y luna con cráteres+estrellas
en oscuro, sin romper la alineación del encabezado. Simulador, Gestión
de datos, Setup y la presencia del interruptor en la propia página de
Setup (mismo `layout.html`) siguen funcionando, cero errores de
consola. Se confirmó además que no quedó ninguna regla huérfana del
diseño anterior (`.dm-switch`, `.buttonBackground/-Clouds/-Stars/-Glow/-Nub`,
`.switch-control`, `#theme-toggle-btn`) -- ese último id ni siquiera
existía ya en el CSS antes de este cambio, era una referencia
desactualizada en el enunciado de la tarea.

## 44. Extensión del lenguaje "Liquid Glass"/tinte-por-categoría al resto del dashboard (auditoría de 9 pantallas)

Tarea explícitamente de replicar, no inventar: extender a las otras 8
pantallas (Vista combinada, ya aprobada, quedó intocada) los 4 patrones
ya confirmados -- tarjetas KPI/zona tintadas por categoría, vidrio en
sidebar/tarjeta destacada, interruptor chico, y cuadrícula asimétrica
"L" donde encaje. Auditoría real (leer cada template/CSS) antes de
tocar nada, para no "actualizar" algo que ya estaba bien.

**Veredicto por pantalla:**

1. **Resumen (cámara individual)** -- YA tenía el tratamiento de color
   (`.kpi-card`/`.category-card`, mismo mecanismo `:has()` de la sección
   42) porque comparte CSS global con la vista combinada. Lo único que
   le faltaba era el layout: seguía en fila de 4 iguales en vez de la
   "L". Se agregó `kpi-panorama-grid` + las 4 clases de área
   (`kpi-card-hero/-zonas/-visitas/-trafico`) a su `.kpi-row` en
   `results.html` -- CERO CSS nuevo, reutiliza tal cual las reglas ya
   escritas para la vista combinada en la sección de la cuadrícula "L".
   Encaja perfecto: mismas 4 tarjetas (1 hero + 3), y el encabezado de
   esta sección ya se llama igual ("Panorama general").

2. **Historia** -- el panel "Resumen narrado" ya estaba bien (opaco,
   como corresponde a texto, no a datos categorizables). Lo desactualizado
   era `.timeline-icon`: los 3 tipos de evento (parada/mano/paso)
   compartían el mismo chip gris neutro, sin distinción de color -- el
   único lugar del dashboard donde un ícono de evento típico
   (footprints/hand/timer-reset, los MISMOS íconos que ya tienen color
   en los KPI) seguía sin color. Se extendió el mecanismo de
   `.kpi-icon-chip` (chip tintado 18% + ícono a color completo) con 3
   clases nuevas (`.timeline-icon-stop/-hand/-footprints`), reusando
   colores ya establecidos: stop=`--color-hot` (misma semántica que
   "Zona Caliente"), hand=`--color-cold` (el mismo color fijo que ya usa
   `.category-card` en la pestaña Interacción), footprints=`--accent-visitas`
   (el mismo token que ya usa el ícono de "Visitas totales" en esta
   misma vista).

3. **Mapas y trayectorias** -- YA estaba bien: sus dos paneles (plano +
   heatmap) contienen imágenes, no datos categorizables por color --
   tintarlos habría sido inventar un patrón sin sentido (el color ya
   vive DENTRO de la imagen del heatmap). Sin cambios.

4. **Interacción con producto** -- YA tenía el tratamiento
   (`.category-card` con `--category-color: var(--color-cold)`, fijo
   para todas sus tarjetas porque representan la MISMA categoría de
   dato -- interacción física -- no una clasificación de zona variable
   como en Resumen). Sin cambios, y confirma que el cold/teal reusado en
   el punto 2 es coherente con lo que esta pestaña ya venía haciendo.

5. **Tendencias** -- el gráfico Chart.js, sus selectores y el panel de
   "ver fecha archivada" ya estaban bien (controles de formulario, no
   tarjetas de categoría). Lo desactualizado: las tarjetas de
   comparación detallada (`.panel.card-info`) seguían con el patrón
   viejo de "panel plano + borde de color" en vez del fondo tintado ya
   establecido -- ver punto 7, mismo fix que en Recomendaciones.
   **Limitación de datos honesta**: ninguna cámara de este proyecto
   (`merl_demo`, `snaks`, `dulces`, `aseo`, `embutidos`) tiene 2+ fechas
   archivadas, así que esta tarjeta específica no se pudo capturar
   renderizada con datos reales en las 9 capturas -- se verificó por
   inspección de código + cálculo WCAG (mismo color/mecanismo que
   Recomendaciones, ver punto 7), no visualmente en pantalla.

6. **Simulador** -- el formulario (selects + botón) y el resultado
   (`.panel` + `.metric-row`) ya son consistentes con el resto del
   dashboard (paneles opacos para formularios, sin tarjetas de
   categoría porque no hay una "categoría" que tintar aquí, solo un
   antes/después de una métrica). Sin cambios -- y, deliberadamente, NO
   se convirtió `.metric-row` en tarjetas KPI: es un layout de
   comparación distinto a propósito, no una versión desactualizada del
   mismo patrón. **Limitación de datos**: ninguna cámara tiene 2+ zonas
   calibradas, así que el formulario del simulador tampoco se pudo
   capturar en su estado "con datos" -- solo se ve el aviso de "necesitas
   2 zonas".

7. **Recomendaciones** -- ERA la pantalla más desactualizada de las 9:
   `.card-accent` (tarjetas de recomendación) y `.card-info` (usada en
   Tendencias, punto 5) solo tenían un borde izquierdo de color sobre
   un `.panel` liso -- el único lugar del dashboard que seguía con el
   lenguaje visual "borde de acento" de antes de esta serie de tareas
   (sección 27), en vez del fondo tintado ya establecido. Se agregó
   `background: color-mix(in srgb, COLOR var(--category-tint-pct),
   var(--color-panel))` a ambas clases -- mismo mecanismo exacto que
   `.category-card` y las tarjetas KPI no-hero, sin inventar nada.
   Verificado WCAG: `--color-ink` (el color de texto que vive
   directamente sobre este fondo) da 14.25:1/10.99:1 (accent,
   claro/oscuro) y 14.46:1/10.36:1 (info) -- de sobra; el único texto
   muted que cae sobre este fondo (`.metric-label` dentro de
   `.card-info` en Tendencias) da 4.93:1/4.68:1, con margen cómodo (no
   al límite como el caso ya corregido de las tarjetas KPI en la
   sección 42).

8. **Gestión de datos** -- YA estaba bien: sus 4 paneles son listas de
   acciones destructivas (borrar video/resultados/fecha/cámara), no
   datos categorizables -- opacos por diseño, correcto. Los diálogos de
   confirmación ya tenían el vidrio esmerilado real (sección 6b, portado
   en la tarea de Liquid Glass). Sin cambios, confirmado que el diálogo
   sigue abriendo/cerrando bien tras todos los cambios de esta ronda.

9. **Asistente de configuración** -- YA estaba bien: es un wizard de
   formularios (subir, recortar, checkboxes, fecha), no un dashboard de
   métricas -- ni el `.dropzone`, ni `#calibration-canvas`, ni
   `.progress-card` (indicador del hámster) debían tintarse por
   categoría, y de hecho `.progress-card` se mantiene opaca a propósito
   desde la sección 41 (así lo define la propia referencia de Liquid
   Glass). Sin cambios de CSS. **Nota de captura**: la vista por
   defecto de `/setup` (sesión nueva) solo muestra el paso 1 (subir
   video) porque `video_path` vive en la sesión de Flask, no en el
   video crudo ya guardado en disco -- comportamiento existente, no
   tocado. Para capturar más del wizard (pasos 2-4) se volvió a subir
   el mismo video ya existente (`data/raw/merl_demo.mp4`, mismo archivo,
   sin cambiar su contenido) a través del propio formulario -- esto
   avanzó la sesión y permitió capturar la vista previa de video, el
   estado "ya existen zonas calibradas", y el formulario de
   procesamiento completos. El canvas de calibración y el indicador con
   el hámster son condicionales (solo aparecen al recalibrar o mientras
   un job de procesamiento está corriendo de verdad) y no se forzaron
   -- lanzar un procesamiento real solo para la captura se habría
   salido del alcance de "solo CSS" de esta tarea.

**Verificación:** 9 capturas en `docs/screenshots/`
(`audit-01-resumen-oscuro.png` a `audit-09-setup-oscuro.png`),
inspeccionadas una por una. Cero errores de consola en toda la
auditoría; Simulador, diálogo de confirmación y Setup siguen
funcionando tras los cambios.

## 45. Segunda reducción de `--toggle-size` -- el piso real es la legibilidad del SVG, no el objetivo teórico

El usuario confirmó que 16px (90x40px, sección 43) seguía viéndose
grande -- casi igualaba el alto del título "Space Management" en 2
líneas (~56px). Objetivo pedido: que el interruptor termine
aproximadamente a la altura de UNA línea de texto normal (la línea de
`.tagline`, 18px de alto real).

**Se probó, no se calculó a ciegas:** 8px (45x20px) -- el objetivo
teórico más cercano a "una línea" -- pero ahí los cráteres de la luna y
las estrellas desaparecen por completo, el círculo queda liso; 10px
(56x25px) y 11px (62x27.5px) -- mismo problema, apenas un cráter
insinuado; 12px (67.5x30px) -- ahí los 3 cráteres ya se distinguen como
manchas separadas y las estrellas se ven como puntos reales, no una
mancha. Se fijó **12px** como valor final: no llega al objetivo teórico
exacto de "una línea de `.tagline`" (18px) porque a esa escala el SVG
deja de ser legible, pero sí queda claramente más cerca de la escala de
texto que del título -- 30px de alto contra 55.78px del título (2
líneas) y 18px de una línea de `.tagline` / ~28px de una línea del
título mismo (`.brand`, `--text-lg`). El piso real de este componente
es la legibilidad de su propio detalle SVG, no un número de diseño
elegido de antemano -- se documenta así en el comentario de la sección
3b de `main.css` para que una futura reducción no repita la misma
prueba desde cero.

**Verificación:** Playwright -- tamaño renderizado real 67.5x30px
(confirmado con `getBoundingClientRect()`, no solo `em`×`px` a mano);
clic sobre el interruptor a este tamaño reducido sigue cambiando
`data-theme` correctamente (claro→oscuro→claro); capturas de
`.brand-row` y de la sidebar completa en ambos temas
(`docs/screenshots/sky-toggle-final-{brand-row,sidebar}-{claro,oscuro}.png`)
confirmando que ya no iguala el alto del título y que los cráteres de
la luna, las estrellas y las nubes siguen siendo reconocibles a este
tamaño. Simulador sigue funcionando, cero errores de consola.

## 46. Dropzone real (drag-and-drop) para "1. Sube tu video" del asistente

Reemplaza el `<input type="file">` desnudo del paso 1 por el patrón de
dropzone ya validado en el proyecto de prueba, adaptado a los tokens de
color propios en vez de copiarlo con colores genéricos.

**1. Archivos modificados:** `dashboard/templates/setup.html` (el
`<input>` suelto pasa a vivir dentro de un `<label class="custom-file-
upload form-field">` con el ícono SVG inline y el texto invitando a
arrastrar, exactamente la estructura que trajo el usuario, solo con
`id="video-upload"` conectado vía `for`); `dashboard/static/css/main.css`
(sección 12 reescrita: `.dropzone` -- que no se usaba en ningún otro
lugar del proyecto, confirmado por búsqueda -- se reemplazó por
`.custom-file-upload` con sus estados `:hover`/`.is-dragover`/
`.has-file`, más la referencia a `.dropzone` en la lista de
`.theme-colors-ready` actualizada al nuevo nombre); `dashboard/static/js/setup.js`
(nueva función `initVideoDropzone()`, agregada a la lista de `init*()`
en `DOMContentLoaded`).

**2. Colores: reutilizados, no genéricos.** El chip circular del ícono
usa el mismo mecanismo `color-mix(in srgb, COLOR 18%, var(--color-panel))`
que ya usa `.kpi-icon-chip` (sección 3), con `--color-accent` (el
acento principal de la app) en vez de un color inventado; el ícono en
sí usa `--color-accent-text` (el mismo token que ya usan otras
superficies tintadas de acento, ej. `.field-badge-accent`). El fondo
del dropzone es un lavado sutil de `--color-accent` sobre
`--color-bg-alt` (6% en reposo, 12% en hover, 22% en dragover -- misma
progresión de intensidad que ya usaba el `.dropzone` viejo en su único
estado, solo con un escalón más para el drop). Cuando ya hay un
archivo elegido, el chip cambia a `--color-success` (mismo verde que
"Visitas totales"/`.accent-visitas`), señalando "listo" con un color ya
establecido para ese significado en el resto del dashboard.

**3. Deliberadamente SIN `backdrop-filter`.** El pedido original
describía esto como "fondo con leve efecto de vidrio consistente con
el resto de paneles" -- pero el resto de paneles (`.panel`,
`.progress-card`, ahora también este dropzone) se mantienen
EXPLÍCITAMENTE opacos por diseño desde la sección 41: el vidrio
esmerilado real (blur de verdad) queda reservado para la sidebar, la
tarjeta hero y el diálogo de confirmación. Se interpretó "vidrio" como
el lenguaje visual de superficie tintada translúcida-por-color (mismo
mecanismo que `.category-card`/`.card-accent`), no como blur literal,
para no contradecir una decisión ya tomada y documentada.

**4. El input real sigue en el DOM, oculto con `opacity:0` +
`position:absolute` cubriendo el `<label>` entero (nunca `display:none`)
-- por eso también es el que recibe físicamente los eventos de drag
nativos del navegador (está encima de todo, aunque sea invisible), y
los listeners en `initVideoDropzone()` los capturan por bubbling desde
el contenedor `.custom-file-upload`.

**5. Una sola fuente de verdad para el texto/ícono.** En vez de
duplicar la lógica de "mostrar nombre de archivo" en el handler de
`change` (clic) Y en el de `drop` (arrastre), el handler de `drop`
solo hace `input.files = event.dataTransfer.files` y despacha un
evento `change` sintético (`input.dispatchEvent(new Event('change',
{bubbles:true}))`) -- así el mismo listener de `change` actualiza la UI
sin importar por cuál camino llegó el archivo. Nota técnica: asignar
`.files` por script NO dispara `change` automáticamente (solo lo hace
una selección real hecha por el usuario) -- de ahí la necesidad del
evento sintético.

**6. Verificación -- drag-and-drop real probado, no solo el flujo de
clic.** Con Playwright SÍ fue posible simular un `drop` real: se
construyó un `DataTransfer` de verdad en el navegador (`new
DataTransfer(); dt.items.add(file)`) con un `File` real (obtenido
leyendo `input.files[0]` tras un `setInputFiles()` previo, luego
reseteando el input a vacío para simular que el usuario todavía no
había elegido nada) y se despachó como evento `drop` sobre el
`.custom-file-upload` -- confirmado que el input real terminó con el
archivo (`input.files.length === 1`) y que el texto/ícono se
actualizaron igual que por clic. También se verificó `dragover`
(agrega `.is-dragover`) y `dragleave` (la quita). Capturas en
`docs/screenshots/dropzone-{default,hover,dragover,archivo-elegido}-{claro,oscuro}.png`.
Envío de formulario de punta a punta confirmado sin regresión: subir
el video real avanza el asistente al paso siguiente (aparece la
vista previa del video), cero errores de consola.

## 47. Overlay de pantalla completa unificado (3 indicadores de progreso -> 1) + bug real del hámster corregido

Unifica los 3 indicadores de progreso inconsistentes del asistente
(vista previa de calor, procesar video, recortar video) en un solo
overlay de pantalla completa, y corrige un bug visual real reportado
por el usuario con capturas reales.

**1. Causa raíz del bug del hámster -- confirmada con Playwright, no
supuesta.** El contenedor `.wheel-and-hamster` vivía a `56x56px` con
`font-size:7px` (un disco de 8em de diámetro), pero las partes internas
del hámster tienen medidas FIJAS en `em` (el hámster mide `7em` de
ancho, calibrado por el propio diseño de origen para un disco de
`12em`). A 8em de diámetro, el hámster ocupaba 87.6% del ancho del
disco en vez del 58.7% previsto -- confirmado renderizando el markup
real antes/después con `getBoundingClientRect()` (49.07px de 56px vs.
84.46px de 144px). El resultado visual: el hámster se salía del
círculo y tapaba el `.spoke`, dejando lo que el usuario describió como
"un círculo con una raya diagonal" en vez del hámster corriendo dentro
de la rueda. Se descartaron las otras dos hipótesis que planteaba la
tarea: NO había `overflow:hidden` en ningún ancestro recortando nada
(`.progress-card` no lo tenía, y agregarlo de prueba -- con la
animación en pausa para comparar en igualdad de condiciones -- no
cambió el resultado visual en absoluto); y NO faltaba ningún
`@keyframes` (los 10, incluido `spoke`, ya estaban completos y
correctamente referenciados). **Fix:** contenedor a `12em` de ancho/alto
(la proporción real del diseño de origen), con `font-size` ajustable
libremente para el tamaño final en px sin romper la proporción interna
-- en el overlay se usó `14px` (168x168px). Verificado en múltiples
frames de la animación corriendo (no solo un frame pausado) que el
hámster se ve bien proporcionado dentro de la rueda en ambos temas.

**2. Overlay reutilizable: `showLoadingOverlay(title, desc)` /
`updateLoadingOverlay(title, desc)` / `hideLoadingOverlay()`** en
`static/js/setup.js`, sobre un único `<div id="loading-overlay" hidden>`
estático en `setup.html` (no se genera dinámicamente por acción --
las 3 acciones comparten el mismo elemento). Fondo: EXACTAMENTE el
mismo `rgba(0,0,0,.45)` + `backdrop-filter: blur(6px)` que ya usa
`dialog.confirm-dialog::backdrop` (sección 6b) -- no se inventó un
"vidrio" nuevo. `z-index:950`, por encima del widget de ayuda flotante
(900). Las 3 acciones lo invocan igual:
- `initGeneratePreview()`: `showLoadingOverlay("En curso", "Preparando...")`
  antes del fetch, luego `pollJob(...)` actualiza el mensaje (fijo,
  igual que antes -- este job no reporta pasos numerados) y lo
  esconde al terminar.
- `initProcess()`: mismo patrón, pero `pollJob` SÍ recibe pasos
  numerados reales del backend (`Paso X de 6: ...`) y los refleja en
  vivo -- la lógica de sondeo (`fetch` a `/status` cada 1.5s) no
  cambió en absoluto, solo A DÓNDE se pinta el resultado.
- `initTrim()` (antes: solo texto plano sin animación) -- ahora
  también llama `showLoadingOverlay("En curso", "Recortando video...")`
  antes del fetch de recorte, y `updateLoadingOverlay(null, "...")`
  al terminar, antes de armar y enviar el `<form>` que navega a
  `/setup/use-trimmed` (la navegación real destruye el overlay junto
  con el resto del documento -- no hace falta esconderlo a mano en el
  camino de éxito, solo en el de error).

**3. Decisión sobre errores: el overlay se cierra, el error se muestra
en la página normal (no dentro del overlay).** Las 3 acciones llaman
`hideLoadingOverlay()` apenas detectan un error (falla el POST inicial,
o `pollJob` recibe `status:"error"`), y el mensaje de error se escribe
en el `<div>` de la página que ya existía para eso (`#preview-progress`,
`#process-progress`, `#trim-status`) usando el mismo `alertHtml("error", ...)`
que el resto del proyecto. Razón: un overlay de pantalla completa que
bloquea toda interacción es apropiado mientras algo está EN CURSO, pero
mantenerlo bloqueando la pantalla para mostrar un error (que el usuario
puede necesitar leer con calma, o que puede requerir que intente de
nuevo con otros datos) se sentiría atrapante -- devolver el control a
la página normal, con el error visible ahí, es más consistente con cómo
ya se manejan errores en el resto del dashboard (alertas inline, nunca
modales bloqueantes).

**4. "Ver registro detallado" eliminado de la interfaz, NO del
backend.** Se quitó el `<details><summary>Ver registro detallado</summary>...`
que `pollJob()` generaba (con el log crudo en `<pre class="log-output">`)
-- `job.log_lines` lo sigue devolviendo `/status` y lo sigue registrando
`job_manager.py` sin ningún cambio, la interfaz simplemente ya no lo
lee. Limpieza de código muerto asociada: `pre.log-output` (CSS) y los
tokens `--color-terminal-bg`/`--color-terminal-text` (solo se usaban
ahí) se eliminaron por no tener ya ningún consumidor.

**5. Verificación -- las 3 acciones probadas de punta a punta con
datos/video reales, no solo simuladas:**
- *Recortar*: overlay visible con "Recortando video...", confirmado
  que se oculta tras la navegación real a la página nueva (`document`
  distinto, no solo el mismo `hidden` reseteado).
- *Vista previa de calor*: overlay visible con "Preparando..." (mensaje
  fijo, tal como pide la tarea para esta acción). El job real tardó
  mucho más de lo esperado (~8 min) porque el intento inicial con
  OpenVINO falló (código 3221225477, el mismo crash ya documentado en
  la sección 40) y reintentó sin aceleración sobre el video COMPLETO
  de merl_demo (~148s, no el clip corto de otras pruebas) -- confirmado
  con `Get-Process` que el proceso de reintento SÍ estaba activo
  (682s de CPU acumulados, no colgado). Confirmado por separado,
  contra el job ya terminado en el servidor, que `pollJob` esconde el
  overlay y dispara `onDone()` correctamente.
- *Procesar video*: usando un clip recortado a 10s (para no esperar
  minutos), se observaron 3 mensajes de paso DISTINTOS en vivo dentro
  de la ventana de la prueba ("Paso 1 de 6" -> "Paso 2 de 6" -> "Paso 3
  de 6"), confirmando el avance en tiempo real pedido explícitamente;
  el job siguió y terminó solo (6/6, `returncode:0`) después de que la
  prueba de Playwright ya había cerrado por su propio límite de tiempo
  -- confirmado por separado, igual que con la vista previa, que
  `pollJob` esconde el overlay y dispara `onDone()` para ese job ya
  terminado.
- Las 3: cero errores de consola, "Ver registro detallado" ausente del
  DOM en todo momento.

**6. Efecto secundario real de esta ronda de pruebas, señalado en vez
de ocultado: los datos de demo de `merl_demo` quedaron con los
resultados del clip de prueba de 10s, no los originales.** La prueba
de "Procesar video" necesitaba un video corto para no esperar minutos,
así que se recortó `merl_demo.mp4` a 10s y se procesó ese clip contra
el store real `merl_demo` (con "Guardar en historial" tildado por
defecto) -- esto sobreescribió `data/output/zone_summary_merl_demo.csv`
(y los demás archivos de `data/output/*merl_demo*`) con los números del
clip de prueba (1 visita, 0% detención, 0.17s de permanencia) en vez de
los reales (6 visitas, 83%, 18.5s, vistos en capturas de tareas
anteriores), y creó una entrada de historial fechada hoy
(`data/history/merl_demo/2026-09-08/`) que no existía antes. El usuario
pidió explícitamente NO tocar `data/` y encargarse manualmente --
quedó sin corregir a propósito. Pendiente para quien lo resuelva:
borrar `data/history/merl_demo/2026-09-08/` y volver a procesar
`data/raw/merl_demo.mp4` (el video COMPLETO, sin recortar, con detección
de manos activada -- así se generaron los números originales) para
restaurar `data/output/zone_summary_merl_demo.csv` y el resto. También
quedaron sueltos en disco los artefactos de la prueba misma
(`data/raw/merl_demo_recortado.webm` y los `data/processed/`
`data/output/` correspondientes a `*_recortado*`), sin tocar por la
misma instrucción.

## 48. Regresión real: el video de verificación de manos mostraba caja en vez de punto -- causa raíz en el DATO, no en la invocación

El usuario reportó, con capturas reales, que el video de manos volvía a
mostrar un rectángulo grande cubriendo a toda la persona -- igual que
el de cuerpo -- en vez del punto pequeño en la muñeca que ya funcionaba
antes. La hipótesis de la tarea (un `--mode caja` forzado, o el
argumento `--mode` roto/renombrado) se descartó por completo tras
inspeccionar el código real, y la causa real resultó estar un nivel
más abajo: en cómo se GENERAN los datos de mano, no en cómo se
renderiza el video.

**1. `detect_mode()` y `--mode` en `render_stitched_preview.py`: intactos,
sin alterar.** El umbral (<40px de ancho promedio = "punto") y el
`argparse` (`default="auto"`) están exactamente como se describen.
Confirmado además que NINGUNA de las dos invocaciones reales en
`run_pipeline.py` (paso 3, verificación de cuerpo; paso 9, verificación
de manos) pasa `--mode` -- ambas dejan el default `"auto"`. Este ángulo
de la hipótesis original quedó descartado por inspección directa del
código, no por suposición.

**2. Causa raíz real, confirmada con datos reales antes de tocar
nada:** se calculó el ancho promedio real de `hands_14_1_crop_stitched.csv`
y `hands_1_2_crop_stitched.csv` (dos CSV de manos ya existentes, de
antes de esta tarea) -- **175-190px de ancho promedio**, muy por encima
del umbral de 40px, NO los "pocos píxeles" que `detect_mode()` espera.
El dato en sí ya estaba mal, no la detección de modo. Rastreando el
origen: `pipeline/detect_hand_positions.py` línea 120 (antes de esta
corrección) escribía `x1, y1, x2, y2 = boxes[i]` -- la caja de LA
PERSONA COMPLETA que devuelve el modelo de pose (`result.boxes.xyxy`,
la misma caja que usa YOLOv8-pose para detectar a la persona antes de
ubicarle los keypoints) -- en vez de una caja sintética chica alrededor
de la muñeca detectada. `x_center`/`y_center` sí guardaban la posición
real de la muñeca (correctos, por eso zoning/heatmap/interacción -- que
solo leen esas dos columnas, nunca x1/x2/y1/y2, confirmado por grep en
los 3 archivos -- nunca se vieron afectados). Los únicos consumidores
reales de x1/x2/y1/y2 en todo el pipeline son `render_stitched_preview.py`
(para dibujar y para `detect_mode()`) -- confirmado que `track_stitching.py`
tampoco las usa (solo x_center/y_center/timestamp/track_id), así que
el fix no tiene ningún efecto secundario aguas abajo.

**3. Corrección:** en `detect_hand_positions.py`, `x1/y1/x2/y2` ahora
se calculan como una caja sintética de `HAND_BOX_HALF_SIZE=15px` de
medio-lado alrededor de `(wrist_x, wrist_y)` (30px de ancho final, bien
por debajo del umbral de 40px, con margen) -- se eliminó la línea que
leía `boxes[i]` (la caja de persona, que ya no se usa para nada en este
archivo) y se agregó un comentario explícito junto a la constante
explicando por qué debe quedarse chica (referenciando `detect_mode()`)
para que una futura refactorización no vuelva a introducir el mismo
problema sin darse cuenta.

**4. Verificación visual real, en 2 cámaras distintas.** Se extrajeron
clips cortos de 15s de `1_2_crop.mp4` y `14_1_crop.mp4` (para no
esperar los ~2 min completos de cada video), se corrió
`detect_hand_positions.py` (con `DISABLE_OPENVINO=1` -- el mismo modelo
de pose gatilló el crash ya documentado en la sección 40 al usar
OpenVINO directamente sin pasar por la red de seguridad de reintento
de `job_manager.py`, algo a tener en cuenta para pruebas manuales
futuras de este script fuera del pipeline completo), `track_stitching.py`,
y `render_stitched_preview.py` con `--mode auto` (default). Confirmado
por consola: **"Modo de dibujo: punto (keypoint)"** en ambas cámaras
(antes habría dicho "caja"). Se generó también el video de cuerpo
equivalente (reusando los tracks de cuerpo ya existentes de esas mismas
cámaras) para comparar lado a lado. Frames extraídos e inspeccionados
directamente (no solo confiado en el log):
- Cámara `1_2_crop`: video de manos -- un punto celeste chico sobre la
  mano de la persona; video de cuerpo -- un rectángulo azul completo
  rodeando a la persona entera, con la letra "A" arriba.
- Cámara `14_1_crop`: mismo contraste -- punto chico en la mano vs.
  rectángulo completo con letra "A" sobre la persona entera.

Ambos modos quedan claramente distinguibles entre sí en las 2 cámaras,
confirmando la corrección visualmente, no solo por el log de consola.
Artefactos de esta verificación (clips cortos, CSVs de prueba con
basename `clip_1_2`/`clip_14_1`, videos y frames extraídos) quedaron en
`data/processed/` y en el scratchpad de la sesión -- no se tocó ningún
archivo de cámara real preexistente (los basenames de prueba no
colisionan con ninguna cámara real del proyecto).

## 49. Navegación sin recarga completa (pjax) entre las pantallas del dashboard

Implementa fetch() + History API para que navegar por la barra lateral
ya no dispare una recarga completa de página (sin el parpadeo de ~1s
reportado) -- SIN ningún framework de frontend, solo Flask + Jinja2 +
JS vanilla, tal como ya establece el proyecto.

**1. Backend -- diferenciar petición parcial de completa: un
`context_processor` global, no un header revisado en cada vista.**
`dashboard/app.py:inject_partial_base()` inyecta la variable
`partial_base` en TODAS las plantillas (`"layout_fragment.html"` si el
header `X-Requested-With: fetch-nav` está presente, si no
`"layout.html"`), y las 8 plantillas de página que antes hacían
`{% extends "layout.html" %}` ahora hacen `{% extends partial_base %}`
-- ninguna vista tuvo que enterarse de esto ni tocar su
`render_template(...)`. `layout_fragment.html` (nueva) es la base
"hermana" de `layout.html`: sin `<html>/<head>/<body>`, solo un
`<title>` + `#pjax-main` (el `page-hero` + `{% block content %}`) +
`#pjax-sidebar` (la zona dinámica de la barra lateral) -- el mismo
fragmento sirve para CUALQUIER página porque son las MISMAS
`{% block %}` que ya existían.

**2. Duplicación deliberada, no accidental -- confirmada con una
prueba real antes de escribir el código.** El plan original era usar
`{% include %}` para no repetir el markup del "page hero" y de la zona
dinámica de la sidebar entre `layout.html` y `layout_fragment.html`.
Antes de construirlo así se probó con un caso mínimo real (Jinja2, no
supuesto): un `{% block %}` colocado DENTRO de un `{% include %}` NO
se puede sobreescribir desde el template hijo que hace `{% extends %}`
-- Jinja renderiza el default del `{% block %}`, ignorando lo que el
hijo definió. Confirmado el problema, la alternativa real evaluada era
reescribir los 8 templates de página para usar macros con
`{% call %}` en vez de `{% block %}` -- mucho más invasivo para un
beneficio menor. Se optó por duplicar ese markup (chico, mayormente
estático) entre las dos plantillas base, con comentarios cruzados
explícitos en ambas.

**3. `#sidebar-dynamic` -- toda la zona de la sidebar que puede cambiar,
reemplazada como una sola unidad.** No solo la clase "activa": el
selector de tienda, la lista de cámaras (distinta por tienda), los
chips Calibrada/Procesada/Historial, y el `{% block sidebar_nav %}` de
cada página (que es ESTRUCTURALMENTE distinto -- results.html trae
Resumen/Historia/Mapas/...; data_management.html trae "Volver al
panel"/Datos; tienda_combinada.html y setup.html no traen nada) viven
todos dentro de `#sidebar-dynamic`. Reemplazarlo entero evita tener que
diferenciar "esto es solo un toggle de clase" de "esto es una
estructura distinta" -- un solo mecanismo para los dos casos.

**4. Scripts de página: se cargan TODOS en toda página, no cada
plantilla pide el suyo.** `layout.html` ahora carga los 5 scripts de
página (`results.js`, `setup.js`, `calibration.js`,
`data_management.js`, `tienda_combinada.js`) incondicionalmente, y se
quitaron los `{% block extra_scripts %}` de cada plantilla que solo
cargaban su propio script. Alternativa considerada y descartada:
inyectar dinámicamente el `<script>` que falte en cada navegación --
técnicamente viable, pero mucho más frágil (orden de carga asíncrono,
evitar duplicados, esperar el `onload` antes de llamar al init) para
un beneficio real muy chico: los 5 scripts son JS vanilla escrito a
mano, sin build ni dependencias pesadas, y los 5 YA se protegían con
un `if (!elementoRaíz) return;` al principio (confirmado leyendo los
5, no asumido) -- cargar de más es inofensivo.

**5. Cada script de página expone una función de init re-ejecutable,
con su propio ancla de detección:**
| Script | Función | Ancla (elemento SIEMPRE presente en esa página) |
|---|---|---|
| results.js | `window.initResultsPage()` | `#tab-resumen` |
| setup.js | `window.initSetupPage()` | `#loading-overlay` |
| calibration.js | `window.initCalibrationPage()` | `#calibration-root` (además de su propia guarda por `data-video`) |
| data_management.js | `window.initDataManagementPage()` | `#datos-feedback` |
| tienda_combinada.js | `window.initTiendaCombinadaPage()` | `.kpi-panorama-grid` |

`data_management.js` dejó de depender de `window.DATOS_CAMARA_NOMBRE`
(una variable global que solo se fijaba en la carga completa -- se
quedaba desactualizada al navegar sin recarga a OTRA cámara) -- ahora
lee `data-store` del propio `#datos-feedback`, actualizado en cada
fragmento igual que el resto del contenido.

**6. Bug real corregido -- singleton de Chart.js.**
`results.js:_trendsChart` asumía que la página de resultados se
inicializaba UNA sola vez en toda la vida de la app (`if
(_trendsChart) return;` dentro de `initTrendsChart()`). Con la
navegación sin recarga eso deja de ser cierto: navegar de la cámara A
(con Tendencias ya abierta) a la B dejaba un chart "fantasma" apuntando
al `<canvas>` viejo y ya destruido de A, y la guarda impedía crear uno
nuevo sobre el canvas nuevo de B -- el usuario se quedaba con un
gráfico vacío. `window.initResultsPage()` ahora destruye
(`_trendsChart.destroy()`) y resetea a `null` cualquier instancia
previa ANTES de re-inicializar la página. **Verificado de forma
directa, no solo con datos reales** (ninguna cámara del proyecto tiene
hoy 2+ fechas archivadas para que el gráfico real se renderice --
limitación de datos existente, no de este cambio): se inyectó vía
Playwright el DOM mínimo que el template SÍ genera cuando
`history_series.has_data` es verdadero, se creó un chart, se navegó
afuera y de vuelta, y se confirmó con la propia API de Chart.js
(`Chart.getChart(canvas)`) que (a) el chart viejo quedó realmente
destruido y (b) se creó una instancia NUEVA (id interno distinto)
sobre el canvas nuevo -- no una reutilización silenciosa.

**7. `initLiquidSidebar()` partida en dos, por una razón real de
duplicación de listeners.** `<aside class="sidebar">` NUNCA se
reemplaza (solo su contenido, `#sidebar-dynamic`), así que el listener
de `pointermove` del efecto de brillo debe agregarse UNA sola vez en
toda la vida de la página -- `initSidebarGlare()`, con una guarda
propia (`sidebar.dataset.glareInit`), se llama solo en la carga
inicial. El efecto de "pill" deslizante de cada `.tabs-nav`
(`initTabsNavPills()`) sí se re-ejecuta después de cada navegación,
porque esos nodos SÍ se destruyen y recrean enteros dentro de
`#sidebar-dynamic` en cada intercambio -- confirmado que esto no
duplica listeners porque los nodos viejos ya no existen para cuando se
vuelve a llamar. `initThemeToggle()` (el interruptor de tema, fuera de
`#sidebar-dynamic`, nunca se reemplaza) explícitamente NO se
re-ejecuta tras navegar, por la misma razón inversa.

**8. Bug real encontrado y corregido durante la verificación: la URL
de una redirección del servidor no se reflejaba en la barra de
direcciones.** `fetch()` sigue redirecciones (302) por defecto -- una
cámara sin resultados que pide `/store/results?store=X` es
redirigida server-side a `/setup?store=X`, y el contenido mostrado YA
era el correcto, pero `history.pushState()` usaba la URL
ORIGINALMENTE pedida, no `resp.url` (la URL final ya resuelta por el
navegador) -- la barra de direcciones mentía. Confirmado con
Playwright navegando a una cámara sin resultados, corregido usando
`resp.url` para el `pushState()`.

**9. `window.cancelActivePoll()` -- un caso límite real, no
hipotético.** El overlay de pantalla completa (sección 47) ya bloquea
el clic a la sidebar mientras un job corre, pero el botón ATRÁS del
navegador no pasa por un clic -- sin esto, volver atrás durante un
"Procesar video" habría dejado el sondeo de `pollJob()` corriendo
sobre una página ya reemplazada, y su redirect final habría secuestrado
la navegación del usuario sin aviso. `navigateTo()` llama a
`window.cancelActivePoll()` (expuesto por `setup.js`) al principio de
cada navegación, sea por clic o por `popstate`.

**10. Alcance explícitamente dejado afuera, y por qué:**
- Los formularios con `<form method="post">`/`form.submit()` real
  (subir video, recortar, crear/vincular cámara, eliminar datos) NO se
  interceptan -- la tarea los excluye explícitamente, y convertirlos
  también habría significado replicar la lógica de manejo de
  respuesta/errores de cada uno sin necesidad real.
- El formulario de "+ Nueva tienda" (`<input name="tienda">` +
  submit) tampoco se convirtió a `navigateTo()` -- técnicamente
  trivial (mismo patrón que el `<select>`), pero fuera del pedido
  explícito ("el selector de tienda"), así que se dejó como
  navegación tradicional.
- Los enlaces sueltos DENTRO del contenido de una página (ej. "Ver
  Tendencias" desde Datos, las tarjetas de tienda en welcome.html) NO
  se interceptan -- la tarea pide específicamente `.tabs-nav` del
  sidebar, "+ Agregar cámara", y el breadcrumb; ampliar el alcance sin
  que se pidiera era más riesgo que beneficio.

**11. Verificación real con Playwright, no solo revisión de código**
(sin datos de prueba nuevos en `data/`, todo con las cámaras/tiendas
que ya existían): clic en cámara/Vista combinada/breadcrumb/"Agregar
cámara"/selector de tienda -- confirmado con un contador real de
eventos `load` de `window` que NINGUNO de estos disparó una recarga
completa (0 en todos los casos); URL de la barra de direcciones
correcta en cada caso, incluida una redirección del servidor (punto 8);
atrás/adelante del navegador funcionando y mostrando el contenido
correcto; singleton de Chart.js corregido (punto 6); dropzone de
subida de video reaccionando correctamente a una selección de archivo
DESPUÉS de llegar por navegación sin recarga (no solo en carga
directa); diálogo de confirmación de Gestión de Datos abriendo
correctamente tras navegar sin recarga, con el `data-store` correcto;
F5 y pegar una URL interna directamente sirviendo la página COMPLETA
en ambos casos (con `<!DOCTYPE>`, sidebar y main-content reales, sin
los ids `#pjax-main`/`#pjax-sidebar` visibles como si fuera un
fragmento sin envolver); Ctrl+clic sobre un enlace de la sidebar
abriendo una pestaña nueva real (con el `href` real) sin afectar la
página original. Cero errores de consola en toda la sesión de pruebas.

## 50. Reporte PDF ampliado -- de "resumen de una página" a documento multi-página con todo lo que ya existía en el dashboard

**Motivación:** `dashboard/report_generator.py` se escribió al inicio
del proyecto y nunca se actualizó -- generaba un PDF de 1 página con
solo la tabla de zonas y un heatmap, mientras el dashboard ya incluía
desde hace varias tareas: narrativa agregada (Historia), heatmap de
interacción de manos, diagrama de espagueti, tabla de interacción por
zona, y comparación de tendencias entre fechas archivadas. El PDF
compartible había quedado desactualizado frente al propio dashboard.

**Regla explícita de la tarea, seguida al pie de la letra: esto es
ENSAMBLAJE, no negocio nuevo.** Ninguna función de `ai_insights.py`,
`storytelling.py` o `trends.py` se tocó -- `report_generator.py` solo
llama a las funciones ya existentes (`storytelling.build_story()`,
`trends.get_trends_data()`, `layout_view.classify_zones()`,
`tienda_service.find_tienda_de_camara()`) y reordena/formatea sus
resultados ya validados por el dashboard en vivo.

**Estructura nueva (multi-página, sin límite de 1 página):**
1. Portada + KPIs de una línea (reusa `store_service`).
2. Resumen ejecutivo: el resumen de `ai_insights` + el párrafo
   narrativo de `storytelling.build_story()["narrative"]` (idéntico al
   que se ve en la pestaña Historia -- no se redactó texto nuevo).
3. Resumen por zona (tabla ya existente, sin cambios).
4. Mapas de calor: ahora hasta 3 imágenes (flujo, interacción de mano,
   espagueti) en vez de 1 sola, cada una con su caption -- la sección
   entera se omite si ninguna imagen existe en disco para esa cámara.
5. Interacción con producto (tabla ya existente).
6. Tendencia -- **solo si `trends.get_trends_data()` devuelve
   `has_enough_dates=True`, `same_dates=False` y `cards` no vacío**;
   si no, la sección se omite por completo (ni encabezado vacío ni
   placeholder). Ver punto siguiente sobre por qué es una tabla y no
   un gráfico.
7. Diagnóstico y recomendaciones (contenido ya existente, sin cambios,
   solo reubicado).
8. Notas de alcance: las 3 notas de alcance ya validadas en
   `results.html` (pestañas Historia e Interacción) y
   `help-content.js`, copiadas **verbatim**, consolidadas en un solo
   lugar visible al final del documento en vez de estar dispersas.

**Decisión: tabla de tendencia, no gráfico matplotlib nuevo.** La
tarea permite ambas opciones ("si es razonable, una imagen estática de
matplotlib; si no, preséntalo como tabla"). Se eligió tabla porque
`trends.get_trends_data()` ya devuelve una estructura de "cards" con
métrica/valor A/valor B/delta que el dashboard en vivo ya muestra tal
cual en "Comparación detallada" -- reusar esa estructura ya validada
es más fiel al pedido de "ensamblaje, no invención" que escribir un
generador de gráficos nuevo para un solo caso de uso, y evita
introducir una dependencia de renderizado adicional solo para el PDF.

**Decisión: NO se incluyó una afirmación de "100% local".** Se
buscó en todo el texto orientado al usuario del dashboard
(`results.html`, `help-content.js`, tooltips) y esa frase exacta NO
existe -- solo aparece en `docs/architecture.md` (documentación
interna). Como la regla de la tarea es reusar texto ya validado y
NO redactar afirmaciones nuevas, se omitió esa claim en vez de
inventarla; las 3 notas de alcance que sí se incluyeron sí tienen
un origen textual verbatim localizable.

**Corrección real, no pedida explícitamente pero necesaria:**
`_fitted_image()` reemplaza un supuesto anterior de aspect ratio fijo
16:9 -- lee las dimensiones reales de cada imagen con Pillow antes de
escalarla. Necesario porque ahora se embeben 3 imágenes distintas
(flujo, manos, espagueti) que no necesariamente comparten el aspect
ratio del frame de video original; con el supuesto anterior una
imagen con proporciones distintas se habría visto estirada o
recortada sin que hubiera error alguno en consola.

**Verificación real (no "corrió sin error" == "contenido correcto"):**
se instalaron `pypdf` y `pymupdf` en el venv (solo para verificación
de esta sesión, NO agregados a `requirements.txt` -- no son
dependencia de la app en ejecución) y se generaron 2 PDFs reales vía
`app.test_client().get('/api/store/<camara>/report.pdf')`:
- **`dulces`** (1 sola fecha archivada): 5 páginas. Texto extraído
  confirma narrativa, contexto de tienda ("Tienda: demo, 1 de 3
  cámaras"), KPIs, y las 3 notas de alcance consolidadas al final.
  3 imágenes de heatmap/espagueti presentes, una por página, cada una
  con su caption distinto. Sección "Tendencia" **ausente** del texto
  extraído, confirmando que se omite correctamente cuando solo hay 1
  fecha. Render a PNG de las 5 páginas confirmó visualmente que
  ninguna imagen está en blanco, distorsionada o rota.
- **`aseo`** (bootstrapeada para esta verificación: zonas creadas vía
  `calibration_service.save_zones_config()` -- equivalente real a
  "Guardar zonas" en la UI -- y 2 corridas reales de
  `pipeline/run_pipeline.py --record-history` con `--run-date
  2026-08-25` y `--run-date 2026-09-01` sobre el mismo video de
  prueba, para producir 2 fechas archivadas genuinas en
  `history_db`): 5 páginas. La sección "Tendencia" aparece
  correctamente con una tabla real de 2 filas por zona comparando
  ambas fechas -- como ambas corridas procesaron el mismo video, los
  deltas son "+0%" en todas las métricas (limitación honesta del
  dato de prueba sintético, no del código: el propósito era validar
  que la rama condicional SÍ renderiza la tabla con datos reales
  cuando corresponde, no producir una tendencia con cambio real).
  Render a PNG confirmó visualmente ambos heatmaps (flujo e
  interacción de mano) y la tabla de tendencia con los valores y
  fechas correctos.
- Los caracteres acentuados se ven como "�" al imprimir en la consola
  de Bash de este entorno -- confirmado con
  `'Cámara' in texto_extraído` (`True`) que es un artefacto del
  codepage de la consola de Windows, no un defecto real del PDF (ver
  también la sección 48 y otras de esta sesión con el mismo patrón).

**Datos de prueba creados, no limpiados automáticamente:**
`config/zones_aseo.json`, los resultados de `aseo` en
`data/output/*aseo*`, y las 2 entradas de historial
(`data/history/aseo/2026-08-25/`, `data/history/aseo/2026-09-01/`)
quedaron en el proyecto como una cámara más con datos reales (aunque
de fecha sintética) -- no se borraron porque son aditivos y no
sobrescriben nada preexistente, pero se marcaron como creados en esta
tarea para que el usuario decida si los conserva. Los PDFs de prueba
(`data/output/reporte_dulces_test.pdf`, `reporte_aseo_test.pdf`)
son artefactos de verificación, no parte de la app.

## 51. Lightbox (visor de imagen ampliada) para las imágenes de resultados

**Qué es y dónde vive:** clic en una imagen de resultados/análisis -->
overlay de pantalla completa con esa imagen ampliada (hasta 90vw/90vh,
`object-fit: contain`, nunca deformada), sobre el mismo fondo "vidrio"
oscuro + blur ya usado en `.loading-overlay` (sección 14) y
`dialog.confirm-dialog::backdrop` (sección 6b) -- reutilizado tal
cual, no un vidrio nuevo. CSS en `main.css` sección 20 (justo antes
del apéndice de verificación WCAG, al final del archivo). JS en
`static/js/main.js:initLightbox()`.

**Selector explícito, no detección implícita:** clase `.lightbox-img`
agregada a mano en las 2 imágenes de resultados que existen hoy en
`templates/results.html` (pestaña "Mapas y trayectorias"): el plano
de la tienda (`api.layout_plot`) y `#heatmap-img` (que ya alternaba
entre flujo/interacción de mano/espagueti vía radio buttons, sin
crear ni destruir el `<img>` -- la delegación de eventos lee
`trigger.src` en el momento del clic, así que siempre abre la
variante que esté mostrando en ese momento, sin lógica adicional).
Deliberadamente NO se aplicó a `#trim-start-thumb`/`#trim-end-thumb`
(miniaturas de recorte de video en `setup.html`, ya tienen su propio
propósito de vista previa pequeña) ni a ningún ícono/logo -- se
revisó `grep <img` en todo `templates/` y esas fueron las únicas 2
imágenes de resultados/análisis que existen en el proyecto hoy.

**Un solo overlay, creado una vez, sin re-inicialización tras
pjax.** `initLightbox()` corre una sola vez en `DOMContentLoaded`
(guardada con `if (document.getElementById("lightbox-overlay"))
return;`), crea el overlay y lo cuelga de `<body>` -- que, igual que
`<aside class="sidebar">` (ver sección 49, navegación sin recarga),
NUNCA se reemplaza por `navigateTo()` (solo `.main-content` y
`#sidebar-dynamic` lo hacen). El clic que abre el lightbox se captura
por delegación de eventos sobre `document` (mismo patrón ya
establecido para los enlaces de la sidebar en la sección 49), así que
cubre automáticamente cualquier `.lightbox-img` que llegue en
contenido cargado dinámicamente después de una navegación sin recarga
-- **no hace falta llamar a `initLightbox()` de nuevo en
`reinitAfterNavigation()`**, a diferencia de `initTabsNavPills()` o
`initResultsPage()`, que sí operan sobre nodos que se destruyen y
recrean enteros en cada intercambio de contenido.

**3 formas de cerrar, las 3 sin conflicto entre sí:** un solo
listener de `click` en `document` cubre el botón X (delegado por su
clase `.lightbox-close`) y el fondo oscuro (comparando
`event.target === overlay` -- un clic en la imagen misma tiene
`event.target === <img>`, distinto del overlay, así que NO cierra, a
propósito). Escape se maneja aparte con un listener de `keydown` en
`document`, condicionado a que el overlay esté con la clase
`is-open`.

**Bloqueo de scroll de fondo:** clase `lightbox-no-scroll` en
`document.documentElement` (`html.lightbox-no-scroll { overflow:
hidden; }`), agregada al abrir y quitada al cerrar. Verificado con
Playwright que esto bloquea específicamente la ENTRADA de scroll de
un usuario real (rueda del mouse en ambas direcciones, tecla
PageDown) -- NO se probó (ni hacía falta) contra `window.scrollTo()`
invocado directamente desde JS, porque `overflow: hidden` en Chromium
deliberadamente no bloquea eso (comportamiento estándar del
navegador, no relevante para un usuario real interactuando con la
página).

**Verificación real con Playwright** (servidor Flask real vía
`flask run`, cámaras `dulces` y `aseo` con datos reales, sin datos de
prueba nuevos para esta tarea): clic en el heatmap abre el overlay
con el `src` correcto; los 3 métodos de cierre (botón X, clic en el
fondo, Escape) confirmados uno por uno, cada uno reabriendo el
lightbox antes del siguiente; confirmado que un clic sobre la imagen
misma NO cierra; scroll de fondo bloqueado con un scroll conocido de
partida (150px) que ni la rueda del mouse en ninguna dirección ni
PageDown lograron mover, y que vuelve a funcionar normalmente
apenas se cierra; navegación sin recarga (pjax) de `dulces` a `aseo`
confirmada (`page.url` cambia sin evento `load` de página completa),
con el lightbox funcionando de inmediato sobre el `#heatmap-img`
recién insertado por esa navegación, sin ninguna re-inicialización
adicional; probado también sobre la imagen "Plano de la tienda";
capturas de pantalla confirmando visualmente el overlay en modo claro
y en modo oscuro (el botón X usa blanco fijo en ambos temas, igual
que `.loading-overlay__title`, porque el fondo detrás siempre es el
overlay oscuro, sea cual sea el tema activo); cero errores de consola
en toda la sesión de pruebas.

## 52. Eliminar tienda completa -- reusa `delete_camera_completely()`, no la reimplementa

**Qué es y dónde vive:** una zona de peligro nueva al final de
`templates/tienda_combinada.html` ("Vista combinada" de una tienda,
solo se renderiza con 2+ cámaras -- ver `main_routes.py:tienda_home()`)
-- mismo tratamiento visual "zona de peligro" ya usado para "Eliminar
cámara completa" en `data_management.html` (`.panel` con
`border-color: var(--color-error)`, título en rojo), reusado tal cual,
sin inventar un lenguaje visual nuevo.

**Reuso real, no reimplementación:** `data_management_service.py`
agrega `delete_tienda_completa(tienda_id)`, que llama a
`delete_camera_completely()` -- LA MISMA función que ya usa "Eliminar
cámara completa" -- una vez por cada cámara de
`tienda_service.get_camaras_de_tienda(tienda_id)`, y al final borra la
entrada de la tienda con `tienda_service.delete_tienda()` (función
nueva, CRUD simple simétrica a `create_tienda()`) -- SOLO si TODAS
las cámaras se borraron sin error. Ningún paso de borrado de
archivos se reimplementó: `delete_tienda_completa()` es puro
orquestador.

**Mejor esfuerzo, no aborta en el primer error.** Si una cámara falla
a mitad de camino, el loop SIGUE con el resto (no corta ahí) -- las
que sí se pudieron borrar quedan borradas (cada
`delete_camera_completely()` ya es irreversible por sí sola, no hay
rollback posible), y la tienda NO se borra del registro si quedó
alguna cámara sin eliminar (para no dejar cámaras huérfanas sin
tienda). La ruta (`POST /api/tienda/<tienda_id>/eliminar`) devuelve
HTTP 500 con `{"ok": false, "eliminadas": [...], "fallidas":
[{"camara_id":, "error":}, ...], "tienda_eliminada": false}` -- el
frontend (`tienda_combinada.js:initEliminarTiendaDialog()`) arma un
mensaje que lista explícitamente ambas listas por nombre, no un
"algo falló" genérico.

**Confirmación reforzada, mismo patrón que "eliminar cámara" pero
contra el LABEL de la tienda** (el nombre visible en la interfaz, no
el id interno -- pueden diferir, ej. label "Demo Store" -> id
"demo_store"): `<dialog class="confirm-dialog" id="dialog-confirm-tienda">`
renderizado server-side con Jinja (no armado dinámicamente por JS,
a diferencia del diálogo "simple" reusado para varios mensajes en
`data_management.js`) -- muestra el nombre de la tienda Y la lista
completa de cámaras a eliminar por nombre ANTES de pedir la
confirmación escrita, y el botón de confirmar permanece
`disabled` hasta que el texto escrito coincide EXACTAMENTE con el
label (comparado en JS vía `input.value.trim() === tiendaLabel`,
re-validado también server-side contra `tienda.get("label")` --
igual en espíritu a como ya valida `eliminar_camara_completa()`,
nunca confiando solo en el frontend).

**El botón de confirmar vive fuera del `if (!runBtn) return;` del
simulador:** `initTiendaCombinadaPage()` en
`static/js/tienda_combinada.js` llama a `initEliminarTiendaDialog()`
ANTES de esa guarda -- el simulador multi-cámara puede no existir si
la tienda no tiene 2+ zonas con datos de interacción
(`has_two_or_more_zone_options`/`has_interaction_data`), pero la zona
de peligro SIEMPRE se renderiza, así que enganchar su diálogo después
de esa guarda la habría dejado sin funcionar en tiendas sin
simulador.

**Verificación real con Playwright + inspección directa de
filesystem/`tiendas.json`** (servidor Flask real vía `flask run`,
2 tiendas de prueba sintéticas creadas y destruidas para esta
verificación, sin tocar la tienda real "demo"/"entrada principal"):
- **Camino feliz** (`tienda_prueba_borrado`, 2 cámaras de prueba con
  `config/zones_*.json` + un CSV de resultados cada una): el panel de
  peligro lista ambos nombres de cámara y la cantidad (2); el diálogo
  al abrir muestra el nombre de la tienda, la lista de cámaras, y la
  advertencia de "no se puede deshacer"; el botón de confirmar
  arranca deshabilitado, sigue deshabilitado con un texto incorrecto
  ("nombre incorrecto"), y se habilita solo al escribir el label
  exacto ("Tienda Prueba Borrado"); tras confirmar, mensaje de éxito
  visible y redirección real a `/tienda` (confirmada por
  `page.url`, no asumida). Confirmado DESPUÉS, leyendo el filesystem
  directamente (no solo el mensaje de la UI): los 4 archivos de
  prueba (`config/zones_camara_test_a.json`,
  `config/zones_camara_test_b.json`, y sus 2 CSV de resultados) ya no
  existen, y `config/tiendas.json` ya no tiene la entrada
  `tienda_prueba_borrado` -- mientras que `demo`/`entrada principal`
  permanecen exactamente iguales.
- **Camino de falla parcial** (`tienda_prueba_falla`, 2 cámaras,
  sabotaje real: se reemplazó `config/zones_camara_falla_b.json` por
  un DIRECTORIO del mismo nombre para forzar un `PermissionError` real
  al intentar `os.remove()` sobre él -- no un mock, una falla de
  filesystem genuina): la ruta devolvió HTTP 500 con
  `"eliminadas": ["camara_falla_a"]`,
  `"fallidas": [{"camara_id": "camara_falla_b", "error": "[Errno 13]
  Permission denied: ..."}]`, `"tienda_eliminada": false`. Confirmado
  en disco: `camara_falla_a` completamente borrada, el directorio-trampa
  de `camara_falla_b` intacto (nunca se tocó), y `config/tiendas.json`
  conservó la entrada de la tienda con la cámara restante
  (`"camaras": ["camara_falla_b"]`) -- ni huérfana ni perdida, el
  estado real quedó reflejado con precisión.
- Cero errores de consola en toda la sesión de pruebas del camino
  feliz. Ambas tiendas de prueba y sus archivos se limpiaron por
  completo al terminar (confirmado con un `tienda_service.list_tiendas()`
  final: solo queda `demo`).