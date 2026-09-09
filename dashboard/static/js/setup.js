document.addEventListener("DOMContentLoaded", () => {
    window.initSetupPage();
});

// #loading-overlay es el ancla de "esta es la página del asistente de
// configuración" para static/js/main.js:navigateTo() -- se renderiza
// siempre, sin importar en qué paso está el asistente (subir/recortar/
// calibrar/procesar), a diferencia de cualquier botón de un paso
// específico que solo existe condicionalmente.
window.initSetupPage = function initSetupPage() {
    if (!document.getElementById("loading-overlay")) return;
    initVideoDropzone();
    initTrim();
    initGeneratePreview();
    initRecordHistoryToggle();
    initProcess();
};

// Overlay de pantalla completa compartido por las 3 acciones con
// progreso de este asistente (vista previa de calor, procesar,
// recortar) -- antes cada una tenía su propio indicador inconsistente
// (una tarjeta con el hámster, otra con pasos numerados, otra solo
// texto plano sin animación). Una sola fuente de verdad para mostrar/
// actualizar/esconder evita que se repita esa inconsistencia si se
// agrega una cuarta acción más adelante.
function showLoadingOverlay(title, desc) {
    const overlay = document.getElementById("loading-overlay");
    if (!overlay) return;
    document.getElementById("loading-overlay-title").textContent = title;
    document.getElementById("loading-overlay-desc").textContent = desc;
    overlay.hidden = false;
}
function updateLoadingOverlay(title, desc) {
    const overlay = document.getElementById("loading-overlay");
    if (!overlay || overlay.hidden) return;
    if (title != null) document.getElementById("loading-overlay-title").textContent = title;
    if (desc != null) document.getElementById("loading-overlay-desc").textContent = desc;
}
function hideLoadingOverlay() {
    const overlay = document.getElementById("loading-overlay");
    if (overlay) overlay.hidden = true;
}

// Dropzone del paso "1. Sube tu video" (.custom-file-upload en setup.html):
// el <input type="file"> real sigue siendo el elemento funcional (oculto
// con opacity:0, cubriendo todo el <label> -- ver main.css sección 12),
// esto solo agrega la retroalimentación visual de arrastrar-y-soltar y
// actualiza el ícono/texto cuando ya hay un archivo elegido, sea por
// clic (selector nativo) o por drop real.
function initVideoDropzone() {
    const dropzone = document.querySelector(".custom-file-upload");
    if (!dropzone) return;
    const input = dropzone.querySelector('input[type="file"]');
    const textSpan = dropzone.querySelector(".text span");
    const iconWrap = dropzone.querySelector(".icon");
    const uploadIconSvg = iconWrap.innerHTML;
    const checkIconSvg = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 12.5L9.5 17.5L19.5 6.5" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/></svg>';

    // Cubre AMBOS caminos (clic con selector nativo, y drop real que
    // dispara "change" a mano más abajo) con una sola fuente de verdad.
    input.addEventListener("change", () => {
        if (input.files && input.files.length > 0) {
            textSpan.textContent = input.files[0].name;
            iconWrap.innerHTML = checkIconSvg;
            dropzone.classList.add("has-file");
        } else {
            textSpan.textContent = "Arrastra o selecciona tu video";
            iconWrap.innerHTML = uploadIconSvg;
            dropzone.classList.remove("has-file");
        }
    });

    ["dragenter", "dragover"].forEach((evtName) => {
        dropzone.addEventListener(evtName, (e) => {
            e.preventDefault();
            dropzone.classList.add("is-dragover");
        });
    });
    ["dragleave", "dragend"].forEach((evtName) => {
        dropzone.addEventListener(evtName, () => dropzone.classList.remove("is-dragover"));
    });
    dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.classList.remove("is-dragover");
        const files = e.dataTransfer.files;
        if (files && files.length > 0) {
            input.files = files;
            input.dispatchEvent(new Event("change", { bubbles: true }));
        }
    });
}

function initTrim() {
    const wantTrim = document.getElementById("want-trim");
    const trimSection = document.getElementById("trim-section");
    if (!wantTrim) return;

    wantTrim.addEventListener("change", () => {
        trimSection.style.display = wantTrim.checked ? "block" : "none";
    });

    const startSlider = document.getElementById("trim-start");
    const endSlider = document.getElementById("trim-end");
    const durationLabel = document.getElementById("trim-duration-label");
    const rangeLabel = document.getElementById("trim-range-label");
    const startThumb = document.getElementById("trim-start-thumb");
    const endThumb = document.getElementById("trim-end-thumb");
    const applyBtn = document.getElementById("trim-apply-btn");
    const video = applyBtn.dataset.video;

    durationLabel.textContent = formatSeconds(parseFloat(endSlider.max));

    function updateThumbs() {
        const s = parseFloat(startSlider.value);
        const e = parseFloat(endSlider.value);
        rangeLabel.textContent = `Seleccionado: ${formatSeconds(s)} a ${formatSeconds(e)} (duración: ${formatSeconds(e - s)})`;
        startThumb.src = `/api/frame?video=${encodeURIComponent(video)}&at=${s}`;
        endThumb.src = `/api/frame?video=${encodeURIComponent(video)}&at=${Math.max(e - 0.2, 0)}`;
    }
    startSlider.addEventListener("change", updateThumbs);
    endSlider.addEventListener("change", updateThumbs);
    updateThumbs();

    applyBtn.addEventListener("click", async () => {
        const statusDiv = document.getElementById("trim-status");
        statusDiv.textContent = "";
        showLoadingOverlay("En curso", "Recortando video...");
        const resp = await fetch(`/api/store/${encodeURIComponent(currentStoreName())}/trim`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ input_path: video, start_sec: startSlider.value, end_sec: endSlider.value }),
        });
        const data = await resp.json();
        if (!data.ok) {
            hideLoadingOverlay();
            statusDiv.innerHTML = `<span style="color:var(--color-error)">${data.error}</span>`;
            return;
        }
        updateLoadingOverlay(null, `Video recortado guardado (${data.n_frames} frames). Aplicando...`);

        const form = document.createElement("form");
        form.method = "post";
        form.action = "/setup/use-trimmed";
        form.innerHTML = `<input type="hidden" name="store" value="${currentStoreName()}">
                           <input type="hidden" name="trimmed_path" value="${data.output_path}">`;
        document.body.appendChild(form);
        form.submit();
    });
}

function currentStoreName() {
    const root = document.getElementById("calibration-root") || document.getElementById("process-btn");
    return root ? root.dataset.store : "";
}

function formatSeconds(totalSeconds) {
    const m = Math.floor(totalSeconds / 60);
    const s = Math.floor(totalSeconds % 60);
    return `${m}:${String(s).padStart(2, "0")}`;
}

function initGeneratePreview() {
    const btn = document.getElementById("generate-preview-btn");
    if (!btn) return;
    btn.addEventListener("click", async () => {
        btn.disabled = true;
        const progressDiv = document.getElementById("preview-progress");
        progressDiv.innerHTML = "";
        showLoadingOverlay("En curso", "Preparando...");
        await fetch(`/api/store/${encodeURIComponent(btn.dataset.store)}/generate-preview`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ video_path: btn.dataset.video }),
        });
        pollJob(btn.dataset.store, "preview", progressDiv, () => window.location.reload());
    });
}

function initRecordHistoryToggle() {
    const check = document.getElementById("record-history-check");
    const dateInput = document.getElementById("run-date-input");
    const field = document.getElementById("run-date-field");
    if (!check || !dateInput) return;

    // Fecha de HOY real del navegador del usuario (no del servidor -- así
    // "hoy" siempre coincide con la zona horaria de quien está frente a
    // la pantalla), en formato YYYY-MM-DD que espera <input type="date">.
    const today = new Date();
    const todayStr = `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
    dateInput.value = todayStr;
    dateInput.max = todayStr; // un video no puede ser "de mañana"

    function syncDateFieldState() {
        dateInput.disabled = !check.checked;
        field.classList.toggle("field-disabled", !check.checked);
    }

    check.addEventListener("change", syncDateFieldState);
    syncDateFieldState(); // estado inicial: checkbox marcado por defecto -> fecha habilitada
}

function initProcess() {
    const btn = document.getElementById("process-btn");
    if (!btn) return;
    btn.addEventListener("click", async () => {
        btn.disabled = true;
        const progressDiv = document.getElementById("process-progress");
        progressDiv.innerHTML = "";
        showLoadingOverlay("En curso", "Iniciando procesamiento...");
        const payload = {
            video_path: document.getElementById("calibration-root")?.dataset.video || "",
            skip_hands: document.getElementById("skip-hands-check").checked,
            record_history: document.getElementById("record-history-check").checked,
            run_date: document.getElementById("run-date-input").value || null,
            body_max_gap: parseFloat(document.getElementById("body-max-gap").value),
            body_max_speed: parseFloat(document.getElementById("body-max-speed").value),
            hand_max_gap: parseFloat(document.getElementById("hand-max-gap").value),
            hand_max_speed: parseFloat(document.getElementById("hand-max-speed").value),
        };
        const resp = await fetch(`/api/store/${encodeURIComponent(btn.dataset.store)}/process`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!data.ok) {
            hideLoadingOverlay();
            progressDiv.innerHTML = window.alertHtml("error", escapeHtmlSetup(data.error));
            window.refreshIcons();
            btn.disabled = false;
            return;
        }
        pollJob(btn.dataset.store, "process", progressDiv, () => {
            window.location.href = `/store/results?store=${encodeURIComponent(btn.dataset.store)}`;
        }, () => { btn.disabled = false; });
    });
}

// Sondea /status cada 1.5s y refleja el progreso en el overlay
// compartido (ver showLoadingOverlay/updateLoadingOverlay arriba) --
// misma logica de sondeo de siempre, solo cambia DONDE se pinta el
// resultado. job.log_lines lo sigue registrando el backend (util para
// depuracion nuestra) pero la interfaz ya no lo lee ni lo renderiza --
// se quito el expander "Ver registro detallado" a pedido del usuario.
//
// window.cancelActivePoll(): el overlay de pantalla completa ya
// bloquea el clic a la barra lateral mientras un job corre, pero el
// botón "atrás" del navegador NO pasa por ahí (ver
// navigateTo()/popstate en main.js) -- sin esto, volver atrás durante
// un procesamiento dejaría el sondeo corriendo "fantasma" sobre una
// página ya reemplazada, y el redirect final de onDone() secuestraría
// la navegación del usuario sin aviso.
window.cancelActivePoll = function cancelActivePoll() {};

function pollJob(store, jobType, progressDiv, onDone, onError) {
    let cancelled = false;
    const interval = setInterval(async () => {
        const resp = await fetch(`/api/store/${encodeURIComponent(store)}/status?job=${jobType}`);
        const job = await resp.json();
        if (cancelled) return; // se navegó lejos de esta página mientras la petición estaba en vuelo

        const stepLabel = job.step_total > 0
            ? `Paso ${job.step_num} de ${job.step_total}: ${job.step_description}`
            : (job.step_description || "Procesando...");
        const title = job.status === "running" ? "En curso" : job.status;
        updateLoadingOverlay(title, stepLabel);

        if (job.status === "done") {
            clearInterval(interval);
            window.cancelActivePoll = function cancelActivePoll() {};
            updateLoadingOverlay("Completo", stepLabel);
            hideLoadingOverlay();
            onDone();
        } else if (job.status === "error") {
            clearInterval(interval);
            window.cancelActivePoll = function cancelActivePoll() {};
            hideLoadingOverlay();
            progressDiv.innerHTML = window.alertHtml("error", "El procesamiento no se pudo completar. Intenta de nuevo.");
            window.refreshIcons();
            if (onError) onError();
        }
    }, 1500);
    window.cancelActivePoll = function cancelActivePoll() {
        cancelled = true;
        clearInterval(interval);
        window.cancelActivePoll = function noop() {};
    };
}

function escapeHtmlSetup(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
}
