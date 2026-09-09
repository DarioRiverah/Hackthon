# Docker -- retail-vision-mvp

Corre el proyecto completo (pipeline de visión computacional + dashboard
Flask) en cualquier máquina con Docker, sin instalar Python, PyTorch,
OpenCV ni ninguna otra dependencia manualmente.

**Camino soportado y probado: CPU.** Es el que se documenta y verifica a
fondo abajo -- funciona en cualquier máquina con Docker Desktop, tenga o
no GPU. Hay una variante GPU opcional documentada al final de este
archivo, mucho más rápida si tu máquina la tiene disponible, pero no es
el camino garantizado para la demo.

## Requisitos previos

- [Docker Desktop](https://www.docker.com/products/docker-desktop/)
  instalado y corriendo. Nada más -- no hace falta Python, pip, ni
  ninguna librería instalada en la máquina host.

## Arrancar (un solo comando)

Desde la raíz del proyecto, la forma más simple -- detecta sola si tu
máquina tiene una GPU NVIDIA utilizable desde Docker y elige la variante
correcta (ver "Selección automática CPU/GPU" más abajo):

```bash
./docker-run.sh          # macOS/Linux/Git-Bash en Windows
```
```powershell
.\docker-run.ps1         # PowerShell en Windows
```

O, si preferís elegir vos mismo el camino CPU explícitamente (el
soportado y probado a fondo):

```bash
docker-compose up --build
```

- La primera vez construye la imagen (descarga la base de Python,
  instala PyTorch CPU + OpenCV + el resto de `requirements.txt`,
  descarga los dos modelos YOLO que usa el pipeline, y los convierte a
  OpenVINO para acelerar la inferencia en CPU -- ver "Qué se hornea en
  la imagen" y "Optimización con OpenVINO" abajo). Tarda varios
  minutos; las siguientes veces reutiliza la cache de capas de Docker y
  es casi inmediato si no cambiaste `requirements.txt` ni el Dockerfile.
- Cuando termine, el dashboard queda disponible en
  **http://localhost:5000**.
- Para pararlo: `Ctrl+C`, o `docker-compose down` desde otra terminal.
- Para volver a levantarlo sin reconstruir: `docker-compose up`.
- Tamaño real de la imagen construida: **~728 MB** (medido con
  `docker inspect --format='{{.Size}}'` -- la columna `SIZE` de
  `docker images` puede mostrar un número mayor e inflado si la misma
  imagen queda taggeada más de una vez en tu Docker local, por cómo
  cuenta capas compartidas entre tags; no la uses como referencia).

## Selección automática CPU/GPU

Dos niveles distintos de "automático", que no hay que confundir:

1. **Dentro del pipeline (nativo, YOLO/PyTorch)**: esto YA es el
   comportamiento por defecto de Ultralytics -- no se agregó código
   nuevo para esto. `pipeline/detect_and_track.py` y
   `pipeline/detect_hand_positions.py` instancian `YOLO(...)` y llaman
   a `.track(...)` sin pasar ningún argumento `device=`; la propia
   documentación de `ultralytics.utils.torch_utils.select_device()`
   (verificado leyendo el código fuente instalado, no de memoria) dice
   textualmente: *"Defaults to auto-selecting the first available GPU,
   or CPU if no GPU is available"*. Si mañana corrés esto en una
   máquina con GPU y PyTorch con soporte CUDA instalado (ej. la imagen
   `Dockerfile.gpu`), el pipeline usa la GPU automáticamente sin tocar
   una línea de código.
2. **Para elegir QUÉ IMAGEN de Docker construir/correr** (CPU vs. GPU):
   esto SÍ es código nuevo -- `docker-run.sh` / `docker-run.ps1` (ver
   contenido completo de ambos en la raíz del proyecto). Prueban de
   verdad el passthrough de GPU (no solo si existe `nvidia-smi` en el
   PATH) con:
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
   ```
   Si eso funciona, levantan `docker-compose.gpu.yml`; si no, levantan
   el `docker-compose.yml` de CPU. Ninguno de los dos scripts asume
   nada -- si el chequeo real falla por cualquier motivo (sin GPU, sin
   drivers, Docker Desktop sin el backend WSL2/GPU activado), caen
   directo al camino CPU.

## Dónde persisten tus datos

`config/` y `data/` (tiendas, zonas calibradas, videos subidos, CSVs
procesados, resultados, historial de tendencias -- incluyendo
`data/output/history.db`) se montan como **volúmenes** desde las mismas
carpetas del proyecto en tu máquina, definidos en `docker-compose.yml`.
Esto significa:

- Todo lo que subas, calibres o proceses **dentro** del contenedor
  aparece directamente en `config/` y `data/` de tu checkout local, y
  viceversa.
- `docker-compose down` seguido de `docker-compose up` (o incluso
  `docker-compose up --build`, que reconstruye la imagen desde cero)
  **no borra nada** de esas dos carpetas -- solo se reconstruye el
  entorno de ejecución (Python + dependencias + modelos), nunca tus
  datos.
- Los modelos `.pt` (YOLO) **no** son un volumen -- viven horneados
  dentro de la imagen (ver siguiente sección), así que el contenedor
  nunca necesita conexión a internet para arrancar ni para procesar un
  video, ni la primera vez ni ninguna después.

## Qué se hornea en la imagen (y por qué)

El `Dockerfile` ejecuta, en tiempo de **build** (no de arranque):

```dockerfile
RUN python -c "from ultralytics import YOLO; YOLO('yolo26n.pt'); YOLO('yolov8n-pose.pt')"
```

Esos son los dos únicos modelos que usa la cadena de producción real del
pipeline (confirmado leyendo `pipeline/run_pipeline.py`, que es lo que
`dashboard/job_manager.py` termina ejecutando al presionar "Procesar
video"): `yolo26n.pt` para detección de cuerpo
(`pipeline/detect_and_track.py`) y `yolov8n-pose.pt` para detección de
manos (`pipeline/detect_hand_positions.py`). `ultralytics.YOLO(...)`
descarga el peso oficial la primera vez que se instancia si no lo
encuentra ya en cache -- forzar esa descarga durante el build (y no en el
primer arranque del contenedor) es lo que garantiza que la demo del
hackathon nunca dependa de la conexión a internet del lugar donde se
presente.

Otros scripts del repo (`pipeline/heatmap_ultralytics.py`,
`pipeline/experimental_yoloe_product_test.py`) referencian otros pesos
(`yolo26s.pt`, `yoloe-26s-seg.pt`) pero **no** forman parte de la cadena
que arranca el dashboard -- son exploratorios/legacy, así que no se
hornean (mantiene la imagen más chica).

## Optimización con OpenVINO (build-time, con red de seguridad)

Además de hornear los `.pt`, el `Dockerfile` los **convierte** a formato
OpenVINO (IR: `.xml` + `.bin`) en la misma etapa de build, vía
`pipeline/export_openvino.py`:

```dockerfile
RUN python pipeline/export_openvino.py
```

OpenVINO acelera la inferencia en CPU reoptimizando el grafo del modelo
(fusión de operadores, mejor uso de instrucciones vectoriales) -- sigue
siendo 100% CPU, no reemplaza ni compite con la variante GPU.

**Red de seguridad (obligatoria, no opcional)**: la conversión es
PURAMENTE una optimización de velocidad, nunca una dependencia dura.
`pipeline/export_openvino.py` SIEMPRE termina con código de salida 0,
pase lo que pase -- si falla, simplemente no deja el directorio
`<modelo>_openvino_model/`. En tiempo de inferencia,
`pipeline/detect_and_track.py:load_model()` revisa si ese directorio
existe; si no existe (porque nunca se creó, o porque existe pero falla
al cargar), usa el `.pt` original sin ningún cambio de comportamiento
visible para el usuario. Además, como una falla de OpenVINO puede
manifestarse como una caída NATIVA del proceso (ver más abajo) que
ningún `try/except` de Python puede atrapar, hay una segunda capa de
red de seguridad a nivel de PROCESO: `pipeline/run_pipeline.py:run_step()`
y `dashboard/job_manager.py:start_job()` reintentan automáticamente UNA
vez, con la variable de entorno `DISABLE_OPENVINO=1`, cualquier paso de
detección que termine con código de salida distinto de cero.

**Prueba real del fallo forzado** (no teórica -- se construyó una
imagen a propósito con la conversión rota):

```bash
docker build --build-arg OPENVINO_EXPORT_FORMAT=formato_invalido_de_prueba -t retail-vision-mvp:cpu-broken-openvino .
```

Resultado real: ambos modelos fallaron la conversión con
`ValueError: Invalid export format=...` (capturado y logueado por
`export_openvino.py`), **el build terminó con código de salida 0**
igual que siempre, la imagen se construyó completa, y un contenedor
levantado desde ella:
- No tiene ningún directorio `*_openvino_model/` (confirmado con `ls`).
- Arranca el dashboard normalmente (`200`/`302` en el puerto mapeado).
- Corriendo `pipeline/detect_and_track.py` sobre un video real de
  prueba, procesó de punta a punta **sin ningún error visible**,
  usando el `.pt` original en silencio (ni un mensaje de `[OpenVINO]`
  en el log, porque `load_model()` ni intenta cargarlo si el
  directorio no existe) -- mismo resultado exacto que con OpenVINO
  activo: **69 detecciones, 3 IDs únicos**.

**Hallazgo real durante el desarrollo de esta red de seguridad**:
probando en Windows (fuera de Docker), cargar el modelo OpenVINO y
correr `.track()` (ByteTrack) produjo un **segfault** (el proceso de
Python moría con `Segmentation fault`, código de salida 139) -- no una
excepción de Python. Esto NO se reprodujo corriendo el mismo modelo
dentro del contenedor Linux (ver mediciones abajo, funcionó sin
problema), pero es la razón concreta por la que la red de seguridad
tiene la capa de reintento a nivel de PROCESO además del `try/except`
al cargar el modelo: un `try/except` normal no puede atrapar un
segfault, pero `subprocess.run(...).returncode != 0` sí lo detecta
(en POSIX, una señal como SIGSEGV se refleja como código de salida
negativo/distinto de cero), permitiendo reintentar limpio con el `.pt`.

**Tiempos de inferencia reales, medidos DENTRO del contenedor** (mismo
clip de 15s/449 frames, `pipeline/detect_and_track.py`, cuerpo
solamente, CPU Intel Core i5-10300H -- 2 corridas limpias por
configuración, sin otros builds de Docker compitiendo por CPU al mismo
tiempo, que sí distorsionó una medición inicial descartada):

| Configuración | Corrida 1 | Corrida 2 | Promedio |
|---|---|---|---|
| Con OpenVINO | 43.1s | 35.5s | **39.3s** |
| Sin OpenVINO (`DISABLE_OPENVINO=1`, `.pt` puro) | 57.5s | 73.6s | **65.6s** |

**Speedup real: ~1.7x** (rango 1.3x-2.1x entre corridas individuales --
hay variación normal de scheduling en la VM de WSL2, pero OpenVINO fue
consistentemente más rápido en las 4 mediciones, nunca al revés).

**Equivalencia de resultados**: se compararon los CSV de tracks fila por
fila. Con OpenVINO vs. sin OpenVINO, sobre el mismo video:
- Mismo número de filas (69 = 69).
- Secuencia `frame`+`track_id` **idéntica**, fila por fila (el tracking
  y la asignación de IDs no cambiaron en absoluto).
- Coordenadas de las cajas (`x1,y1,x2,y2,x_center,y_center`): diferencia
  máxima de 4.5px, promedio 0.2px -- la variación numérica esperable de
  cualquier conversión de formato de modelo (cuantización/fusión de
  operadores), sin ningún impacto práctico observado en la
  clasificación de zona ni el conteo de visitas.

## CPU vs. GPU en la imagen

`requirements.txt` no fija una versión de PyTorch -- si se instalara tal
cual con `pip install -r requirements.txt` en Linux, pip resolvería por
defecto una build de PyTorch que incluye los binarios CUDA embebidos
(pesa varios GB extra) aunque la máquina no tenga GPU. El `Dockerfile`
evita esto instalando explícitamente la build CPU-only desde el índice
oficial de PyTorch **antes** de `pip install -r requirements.txt`:

```dockerfile
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision
```

Esto mantiene la imagen en un tamaño razonable y no asume GPU disponible
en la máquina donde se corra la demo.

## Variante GPU (opcional, secundaria -- no es el camino garantizado)

Si tu máquina tiene una GPU NVIDIA y Docker Desktop configurado con el
backend WSL2 + soporte de GPU, PODÉS acelerar el pipeline (~3x más
rápido según lo medido en `docs/architecture.md` sección 13) corriendo
una variante con PyTorch CUDA en vez de la imagen CPU de arriba.

**Estado real de esta variante** (no especulado -- probado de punta a
punta en la máquina de desarrollo de este proyecto, Windows 11 + Docker
Desktop + WSL2 + RTX 3050 Laptop):

- El passthrough de GPU de Docker Desktop funciona en esta máquina --
  confirmado con
  `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi`.
- `Dockerfile.gpu` (imagen base `nvidia/cuda:12.4.1-runtime-ubuntu22.04`
  + Python 3.13 vía deadsnakes + PyTorch con CUDA 12.4) se construyó
  **con éxito** -- tamaño real **~8.0 GB** (medido con `docker inspect
  --format='{{.Size}}'`; igual que con la imagen CPU, la columna `SIZE`
  de `docker images` puede mostrar un número mayor, no uses esa
  columna).
- Corriendo el contenedor (tanto con `docker run --gpus all` como con
  `docker compose -f docker-compose.gpu.yml up`, ver abajo), se
  confirmó que `torch.cuda.is_available()` devuelve `True` y
  `torch.cuda.get_device_name(0)` devuelve correctamente
  `"NVIDIA GeForce RTX 3050 Laptop GPU"` -- la GPU es real y accesible
  desde dentro del contenedor, no solo desde el host. También se
  confirmó que el dashboard Flask arranca normalmente bajo esta imagen
  (responde `200`/`302` en el puerto mapeado, igual que la imagen CPU).
- **Corrección sobre una afirmación anterior de este mismo documento**:
  se dijo en un primer borrador que Compose "clásico" no soporta pedir
  GPU sin un plugin aparte de NVIDIA, y que por eso la única forma
  práctica era `docker run --gpus all` directo. Eso resultó ser
  **incorrecto** -- se probó de verdad y `docker-compose.gpu.yml` (con
  el bloque estándar `deploy.resources.reservations.devices` de la
  Compose Specification) funciona sin ningún plugin extra con Docker
  Desktop + Compose v2 (`docker compose -f docker-compose.gpu.yml up
  --build`): el contenedor arranca, ve la GPU, y el dashboard responde
  igual que con `docker run`. Se deja documentado el `docker run`
  también como alternativa (sección "Cómo armarla" abajo), pero el
  compose file es la forma recomendada -- es lo que usan
  `docker-run.sh`/`docker-run.ps1`.
- **Lo que NO se verificó**: no se corrió el pipeline completo de 11
  pasos con un video real dentro de esta variante GPU (sí se hizo a
  fondo con la imagen CPU) -- se acotó el alcance a confirmar que CUDA
  queda armado y accesible, por tratarse de un camino explícitamente
  secundario. La construcción de esta imagen fue notablemente más
  lenta que la CPU (~10-15 min vs. unos pocos minutos, dominado por la
  descarga de PyTorch+CUDA, ~2 GB de wheels de NVIDIA) -- normal para
  esta variante, no un error.
- **Dos bugs reales que aparecieron y se corrigieron en `Dockerfile.gpu`
  al construirla por primera vez** (documentados como comentarios en el
  archivo): (1) sin `DEBIAN_FRONTEND=noninteractive`, `apt-get install`
  se cuelga esperando un prompt interactivo de configuración de
  `tzdata` que nunca llega en un build no interactivo; (2) la imagen
  base de NVIDIA trae `blinker` preinstalado por `apt` como paquete de
  sistema, y `pip install` se queda colgado (no solo falla) al intentar
  reemplazarlo -- se resolvió con `pip install --ignore-installed`.

### Cómo armarla (si tu máquina la soporta)

**La forma recomendada es `./docker-run.sh` / `.\docker-run.ps1`** (ver
"Selección automática CPU/GPU" arriba) -- detectan el passthrough real y
levantan `docker-compose.gpu.yml` solos. Manualmente:

1. **Prerrequisito de Windows**: Docker Desktop con el backend WSL2
   activado (Settings → General → "Use the WSL 2 based engine") y, en
   Settings → Resources → WSL Integration, tu distro habilitada. Los
   drivers de NVIDIA para WSL2 se instalan en Windows (no dentro de la
   distro Linux) -- ver la guía oficial de NVIDIA para "CUDA on WSL".
2. Verificá el passthrough antes de construir nada:
   ```bash
   docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi
   ```
   Si esto no muestra tu GPU, la variante GPU no va a funcionar --
   quedate con la imagen CPU.
3. Levantá `docker-compose.gpu.yml` (usa `Dockerfile.gpu`: imagen base
   `nvidia/cuda` en vez de `python:3.13-slim`, y PyTorch con soporte
   CUDA en vez de la build CPU-only):
   ```bash
   docker compose -f docker-compose.gpu.yml up --build
   ```
   Alternativa equivalente sin Compose, si preferís `docker run` directo:
   ```bash
   docker build -f Dockerfile.gpu -t retail-vision-mvp:gpu .
   docker run --rm --gpus all -p 5000:5000 \
       -v "$(pwd)/config:/app/config" -v "$(pwd)/data:/app/data" \
       retail-vision-mvp:gpu
   ```

**Por qué esto es secundario y no el `docker-compose.yml` por defecto**:
pedir GPU en una máquina sin esa GPU o sin el runtime de NVIDIA
configurado hace que el contenedor **no arranque en absoluto** (falla
el `up`/`run` completo, no solo la aceleración) -- inaceptable para una
demo de hackathon en una máquina que no controlás de antemano. El
`docker-compose.yml` de este proyecto por eso es 100% CPU sin ninguna
bandera especial: es el que funciona igual en la laptop del jurado, en
la del equipo, o en cualquier otra. `docker-run.sh`/`docker-run.ps1`
existen precisamente para automatizar esta elección sin que el usuario
tenga que saber nada de esto de antemano.

## Problemas conocidos / limitaciones

- El servidor de desarrollo de Flask (`debug=True`) es el mismo que se
  usa en local -- no es un servidor de producción (WSGI real), pero es
  exactamente el mismo comportamiento que tenía el proyecto antes de
  dockerizarlo, así que no es una regresión introducida por Docker.
- `MAX_CONTENT_LENGTH` (2 GB, ver `dashboard/app.py`) sigue aplicando
  igual dentro del contenedor -- videos más grandes que eso se
  rechazan, igual que en local.
- Vas a ver el warning `OpenCV: FFMPEG: tag 0x30385056/'VP80' is not
  supported with codec id 139` en el log del contenedor mientras se
  generan los videos de verificación (`.webm`) -- es un warning ya
  conocido y confirmado inofensivo de antes de Docker (ver
  `docs/architecture.md`, sección sobre el bug de códec de video):
  `libvpx` igual codifica VP8 válido a pesar del mensaje. No indica que
  algo se rompió.
- `requirements.txt` incluye `lap` explícitamente (necesario para el
  tracker ByteTrack de `ultralytics`) -- se agregó como parte de esta
  dockerización porque construir la imagen desde cero expuso que
  faltaba (en desarrollo local nunca se notó porque `ultralytics` lo
  auto-instalaba silenciosamente la primera vez que hacía falta, con
  internet disponible). Si en algún momento ves en el log del
  contenedor un mensaje de `ultralytics` diciendo `attempting
  AutoUpdate` para CUALQUIER paquete, es señal de que falta algo nuevo
  en `requirements.txt` -- agregalo ahí y reconstruí la imagen, nunca
  dependas de que el AutoUpdate funcione en el lugar de la demo.
- La conversión a OpenVINO (ver sección dedicada arriba) es una
  optimización de velocidad con red de seguridad de dos capas -- si en
  algún momento el log muestra `[OpenVINO] No se pudo cargar...` o un
  `AVISO: ... reintentando UNA vez con el modelo original`, es la red
  de seguridad actuando correctamente, no un error a resolver.
- Ver el resumen de la tarea de dockerización (o el historial de este
  chat) para cualquier limitación adicional detectada durante la
  verificación real del contenedor.
