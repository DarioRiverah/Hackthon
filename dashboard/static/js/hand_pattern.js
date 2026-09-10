// Captura del "patrón de manos" (4 poses en secuencia) vía MediaPipe
// Hand Landmarker -- runtime JS para NAVEGADOR (@mediapipe/tasks-vision,
// CDN), NO el paquete de Python `mediapipe` (retirado del proyecto a
// propósito, ver docs/architecture.md). Detección EN VIVO, de cerca y
// de frente (la propia webcam del usuario) -- el caso de uso normal
// para el que este modelo funciona bien, distinto del intento anterior
// con video de vigilancia cenital a distancia (no aplica acá).
//
// Expone window.HandPatternCapture -- clase chica que, dado un <video>
// + <canvas> de overlay ya en el DOM, corre detección continua, detecta
// estabilidad de la mano (~1s sin cambios significativos) para
// auto-capturar, permite captura manual (captureNow()), y normaliza
// cada vector de landmarks (traslada usando la muñeca como origen,
// escala por la distancia muñeca -> nudillo medio del dedo medio) ANTES
// de entregarlo -- así la comparación en el backend nunca depende de
// qué tan cerca esté la mano de la cámara.
//
// Usado tanto por login.js (login con patrón) como por settings.js
// (registrar/cambiar el patrón) -- misma clase, mismo flujo de captura.

const MEDIAPIPE_VERSION = "0.10.14";
const MEDIAPIPE_MODULE_URL = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MEDIAPIPE_VERSION}/vision_bundle.mjs`;
const MEDIAPIPE_WASM_BASE = `https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@${MEDIAPIPE_VERSION}/wasm`;
const MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";

const WRIST = 0;
const MIDDLE_MCP = 9; // nudillo medio (base del dedo medio) -- la distancia muñeca->acá es la referencia de escala.
export const POSE_COUNT = 4;
const STABILITY_MS = 1000;
// Movimiento máximo tolerado entre frames consecutivos (landmarks CRUDOS
// de MediaPipe, normalizados 0..1 relativo al cuadro de video) para
// considerar la mano "quieta" -- no confundir con el umbral de
// comparación del backend (hand_pattern.py), que opera sobre la pose ya
// re-normalizada por muñeca/escala.
const STABILITY_THRESHOLD = 0.015;

const HAND_CONNECTIONS = [
    [0, 1], [1, 2], [2, 3], [3, 4],
    [0, 5], [5, 6], [6, 7], [7, 8],
    [5, 9], [9, 10], [10, 11], [11, 12],
    [9, 13], [13, 14], [14, 15], [15, 16],
    [13, 17], [17, 18], [18, 19], [19, 20],
    [0, 17],
];

function normalizePose(landmarks) {
    const wrist = landmarks[WRIST];
    const mcp = landmarks[MIDDLE_MCP];
    const scale = Math.hypot(mcp.x - wrist.x, mcp.y - wrist.y, mcp.z - wrist.z) || 1;
    return landmarks.map((p) => [
        (p.x - wrist.x) / scale,
        (p.y - wrist.y) / scale,
        (p.z - wrist.z) / scale,
    ]);
}

function maxMovement(a, b) {
    let max = 0;
    for (let i = 0; i < a.length; i++) {
        const d = Math.hypot(a[i].x - b[i].x, a[i].y - b[i].y, a[i].z - b[i].z);
        if (d > max) max = d;
    }
    return max;
}

function drawSkeleton(ctx, landmarks, width, height) {
    ctx.strokeStyle = "#9083FF";
    ctx.lineWidth = 2;
    HAND_CONNECTIONS.forEach(([a, b]) => {
        ctx.beginPath();
        ctx.moveTo(landmarks[a].x * width, landmarks[a].y * height);
        ctx.lineTo(landmarks[b].x * width, landmarks[b].y * height);
        ctx.stroke();
    });
    ctx.fillStyle = "#5B4FD6";
    landmarks.forEach((p) => {
        ctx.beginPath();
        ctx.arc(p.x * width, p.y * height, 3.5, 0, Math.PI * 2);
        ctx.fill();
    });
}

export class HandPatternCapture {
    // callbacks: onStatus(text), onProgress(capturedCount, total), onDone(poses), onError(text)
    constructor({ video, canvas, onStatus, onProgress, onDone, onError }) {
        this.video = video;
        this.canvas = canvas;
        this.ctx = canvas.getContext("2d");
        this.onStatus = onStatus || (() => {});
        this.onProgress = onProgress || (() => {});
        this.onDone = onDone || (() => {});
        this.onError = onError || (() => {});
        this.poses = [];
        this.landmarker = null;
        this.stream = null;
        this._raf = null;
        this._lastLandmarks = null;
        this._stableSinceMs = null;
        this._running = false;
    }

    async start() {
        try {
            this.onStatus("Cargando el detector de manos...");
            const { HandLandmarker, FilesetResolver } = await import(MEDIAPIPE_MODULE_URL);
            const filesetResolver = await FilesetResolver.forVisionTasks(MEDIAPIPE_WASM_BASE);
            try {
                this.landmarker = await HandLandmarker.createFromOptions(filesetResolver, {
                    baseOptions: { modelAssetPath: MODEL_URL, delegate: "GPU" },
                    runningMode: "VIDEO",
                    numHands: 1,
                });
            } catch (gpuErr) {
                // Delegate GPU puede fallar en máquinas/navegadores sin
                // WebGL utilizable -- reintenta en CPU antes de rendirse.
                this.landmarker = await HandLandmarker.createFromOptions(filesetResolver, {
                    baseOptions: { modelAssetPath: MODEL_URL, delegate: "CPU" },
                    runningMode: "VIDEO",
                    numHands: 1,
                });
            }

            this.onStatus("Pidiendo acceso a la cámara...");
            this.stream = await navigator.mediaDevices.getUserMedia({ video: { width: 480, height: 360 }, audio: false });
            this.video.srcObject = this.stream;
            await this.video.play();
            this.canvas.width = this.video.videoWidth || 480;
            this.canvas.height = this.video.videoHeight || 360;

            this.poses = [];
            this._running = true;
            this.onProgress(0, POSE_COUNT);
            this.onStatus(`Mostrá la pose 1 de ${POSE_COUNT} frente a la cámara y mantenela quieta ~1 segundo.`);
            this._loop();
        } catch (err) {
            this.onError(
                err && err.name === "NotAllowedError"
                    ? "No se pudo acceder a la cámara -- revisa los permisos del navegador."
                    : "No se pudo iniciar la detección de manos. Intenta de nuevo."
            );
            this.stop();
        }
    }

    stop() {
        this._running = false;
        if (this._raf) cancelAnimationFrame(this._raf);
        this._raf = null;
        if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
        this.stream = null;
        if (this.video) this.video.srcObject = null;
        if (this.landmarker) { this.landmarker.close(); this.landmarker = null; }
    }

    // Captura manual: usa el último frame detectado, sin esperar
    // estabilidad. No hace nada si no hay ninguna mano en cuadro.
    captureNow() {
        if (this._lastLandmarks) this._commitPose(this._lastLandmarks);
        else this.onStatus("No se detecta ninguna mano en cuadro todavía.");
    }

    _commitPose(landmarks) {
        this.poses.push(normalizePose(landmarks));
        this._stableSinceMs = null;
        this._lastLandmarks = null;
        this.onProgress(this.poses.length, POSE_COUNT);
        if (this.poses.length >= POSE_COUNT) {
            this.onStatus("¡Las 4 poses quedaron capturadas!");
            const poses = this.poses;
            this.stop();
            this.onDone(poses);
        } else {
            this.onStatus(`Pose ${this.poses.length} capturada. Mostrá la pose ${this.poses.length + 1} de ${POSE_COUNT}.`);
        }
    }

    _loop() {
        if (!this._running) return;
        const now = performance.now();
        const result = this.landmarker.detectForVideo(this.video, now);

        this.ctx.clearRect(0, 0, this.canvas.width, this.canvas.height);
        this.ctx.drawImage(this.video, 0, 0, this.canvas.width, this.canvas.height);

        if (result.landmarks && result.landmarks.length > 0) {
            const landmarks = result.landmarks[0];
            drawSkeleton(this.ctx, landmarks, this.canvas.width, this.canvas.height);

            if (this._lastLandmarks) {
                const movement = maxMovement(landmarks, this._lastLandmarks);
                if (movement < STABILITY_THRESHOLD) {
                    if (this._stableSinceMs == null) this._stableSinceMs = now;
                    const heldMs = now - this._stableSinceMs;
                    const heldS = Math.min(heldMs, STABILITY_MS) / 1000;
                    this.onStatus(`Quieta... (${heldS.toFixed(1)}s / 1.0s)`);
                    if (heldMs >= STABILITY_MS) {
                        this._commitPose(landmarks);
                        if (this._running) this._raf = requestAnimationFrame(() => this._loop());
                        return;
                    }
                } else {
                    this._stableSinceMs = null;
                }
            }
            this._lastLandmarks = landmarks;
        } else {
            this._lastLandmarks = null;
            this._stableSinceMs = null;
        }

        this._raf = requestAnimationFrame(() => this._loop());
    }
}

window.HandPatternCapture = HandPatternCapture;
