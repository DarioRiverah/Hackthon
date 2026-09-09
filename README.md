# Retail Vision MVP — Space Management por Visión Computacional

Prototipo de visión computacional que analiza video de una tienda para
detectar y cuantificar la dinámica de los clientes alrededor de las
góndolas (flujo, permanencia, interacción física con productos) y
generar recomendaciones accionables de space management — todo
respetando privacidad por diseño (sin identificar personas, sin
inferir emociones, sin almacenar biometría).

## Principios de diseño

- **100% local**: todo el procesamiento de video corre en la máquina
  local. El video nunca sale del dispositivo ni se sube a ningún
  servidor. Solo métricas agregadas (números, no imágenes) podrían
  eventualmente sincronizarse a la nube si el negocio lo requiere.
- **Privacidad por diseño**: no se guarda ninguna imagen de personas ni
  dato biométrico. Los identificadores de persona son efímeros (solo
  viven durante el procesamiento de un video, no permiten
  re-identificación entre videos distintos).
- **Honestidad técnica**: el sistema no promete más de lo que puede
  sostener. En particular, la detección de interacción con producto
  cuenta y mide la interacción física (aproximación, duración), pero
  **no distingue con certeza si el resultado fue tomar o devolver un
  producto** — esa distinción requeriría reconocimiento de acciones
  especializado, fuera del alcance de este MVP.
- **Escalable sin fricción**: cada tienda/cámara nueva solo requiere
  una calibración de zonas de unos minutos — nada está "quemado" en el
  código para una tienda específica.
- **100% gratuito / open source**: todos los modelos y librerías usados
  son gratuitos, sin dependencia de APIs de pago.

## Instalación

```powershell
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

**Alternativa sin instalar nada de Python/CV a mano**: con Docker
Desktop instalado, `docker-compose up --build` levanta todo (pipeline +
dashboard) en un solo comando -- ver [DOCKER.md](DOCKER.md) para el
detalle completo (dónde persisten los datos, requisitos, variante GPU
opcional).

## Estructura del proyecto

```
retail-vision-mvp/
├── config/                    Configuración de zonas por tienda (JSON)
├── data/
│   ├── raw/                   Videos originales (nunca se procesan sin copia)
│   ├── processed/             CSVs de tracking intermedios
│   └── output/                Métricas agregadas finales (lo único persistente)
├── pipeline/                  Scripts de procesamiento de video
├── dashboard/                 App web (Flask + Jinja2 + HTML/CSS/JS propio)
│   ├── routes/                 Blueprints (páginas, asistente de config., API/AJAX)
│   ├── templates/               Plantillas Jinja2
│   ├── static/                  CSS y JavaScript propios (sin frameworks de terceros)
│   └── *.py                     Lógica de negocio pura (reutilizable sin Flask)
├── docs/                      Documentación técnica y de privacidad
└── _legacy_streamlit/         Versión anterior (Streamlit) -- histórica, ver docs/architecture.md sección 25
```

## Cómo usarlo

### Opción A: interfaz web (recomendada)

```powershell
python dashboard\app.py
```

Abre `http://127.0.0.1:5000` en el navegador.

La barra lateral es un panel de control persistente: ahí eliges una
tienda existente o creas una nueva ("+ Nueva tienda / cámara"), y su
estado (calibrada / procesada / con historial) queda siempre visible.

- Si la tienda todavía no tiene resultados, se abre el asistente de
  configuración: sube tu video, opcionalmente recórtalo, marca tus
  góndolas, y procesa todo con un clic.
- Si ya tiene resultados, se muestra directamente el panel con 6
  pestañas (Historia, Mapas y trayectorias, Interacción con producto,
  Tendencias, Simulador, Recomendaciones), con la opción de agregar una
  nueva grabación o recalibrar sin perder los resultados existentes.

### Opción B: línea de comandos, paso a paso

Útil para depurar un módulo específico o para correr el pipeline sin
interfaz gráfica.

```powershell
# 1. Calibrar zonas (una sola vez por cámara/tienda)
python pipeline\calibrate_zones.py --video data\raw\mi_video.mp4 --store-name mi_tienda

# 2. Correr el pipeline completo (detección, tracking, zonificación, interacción, heatmap)
python pipeline\run_pipeline.py --video data\raw\mi_video.mp4 --store-name mi_tienda

# 3. Ver resultados
python dashboard\app.py
```

### Opción C: módulos individuales (para depuración)

```powershell
python pipeline\detect_and_track.py --video data\raw\mi_video.mp4
python pipeline\track_stitching.py --input data\processed\tracks_mi_video.csv --diagnose
python pipeline\track_stitching.py --input data\processed\tracks_mi_video.csv --max-gap-seconds 2 --max-speed-px-per-s 500
python pipeline\zoning.py --tracks data\processed\tracks_mi_video_stitched.csv --zones config\zones_mi_tienda.json
python pipeline\heatmap.py --video data\raw\mi_video.mp4 --tracks data\processed\tracks_mi_video.csv
python pipeline\detect_hand_positions.py --video data\raw\mi_video.mp4
python pipeline\interaction_events.py --hands data\processed\hands_mi_video_stitched.csv --zones config\zones_mi_tienda.json
```

## Modelos usados

| Módulo | Modelo | Por qué |
|---|---|---|
| Detección/tracking de cuerpo | YOLO26n | Mejor desempeño medido en vista cenital (72% más detecciones que YOLOv8 en nuestras pruebas) |
| Detección de manos/pose | YOLOv8n-pose | Mejor precisión/recall contra las etiquetas reales de MERL que YOLO26s-pose en nuestras pruebas (ver `docs/architecture.md` sección 16) |

Ver `docs/architecture.md` (secciones 2 y 16) para el detalle de por qué se eligió esta
combinación híbrida en vez de un solo modelo para todo.

## Limitaciones conocidas

- La calibración de zonas se hace marcando puntos sobre un `<canvas>`
  HTML5 en el navegador (JavaScript propio, sin librerías de terceros).
  El polígono en progreso se dibuja enteramente en el cliente, sin
  recargar la página en cada clic. Una calibración por canvas equivalente
  se había evaluado y descartado durante la era Streamlit por depender
  de una librería sin mantenimiento activo (`streamlit-drawable-canvas`,
  ver `docs/architecture.md` sección 10) -- al migrar a un frontend
  propio esa limitación dejó de aplicar.
- La detección de interacción con producto es una **estimación de
  frecuencia/intensidad**, no una medición certera de compra o
  devolución (ver sección de Honestidad técnica arriba).
- El procesamiento no es en tiempo real: un video de ~2 minutos tarda
  aproximadamente 10-12 minutos en CPU, o ~3.5 minutos con GPU NVIDIA
  (probado en RTX 3050) -- ver `docs/architecture.md` sección 13. La
  mayoría del tiempo lo consume la detección YOLO, no la lógica de
  negocio. El sistema funciona correctamente en ambos casos; GPU es
  una mejora de velocidad opcional, no un requisito.

## Documentación adicional

- `docs/architecture.md` — decisiones técnicas y su justificación
- `docs/privacy_checklist.md` — cumplimiento de privacidad por diseño y Ley 1581