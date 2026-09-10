document.addEventListener("DOMContentLoaded", () => {
    window.initSetupPage();
});

// #setup-page-root es el ancla de "esta es la página del asistente de
// configuración" para static/js/main.js:navigateTo() -- se renderiza
// siempre, sin importar en qué paso está el asistente (subir/recortar/
// calibrar/procesar), a diferencia de cualquier botón de un paso
// específico que solo existe condicionalmente.
window.initSetupPage = function initSetupPage() {
    if (!document.getElementById("setup-page-root")) return;
    initVideoDropzone();
    initTrim();
    initGeneratePreview();
    initRecordHistoryToggle();
    initProcess();
};

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
        const store = currentStoreName();
        applyBtn.disabled = true;
        statusDiv.innerHTML = '<p class="caption">Recortando video...</p>';
        // Recortar es una sola petición síncrona (no pasa por job_manager,
        // ver dashboard/api_routes.py:trim), pero igual se anuncia en la
        // campana -- si el usuario ya se fue de esta página mientras
        // recortaba, sigue viendo el resultado ahí en vez de perderlo.
        const notifId = window.addBellNotification(`Recortando video: ${store}`);
        const resp = await fetch(`/api/store/${encodeURIComponent(store)}/trim`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ input_path: video, start_sec: startSlider.value, end_sec: endSlider.value }),
        });
        const data = await resp.json();
        if (!data.ok) {
            window.finishBellNotification(notifId, "error");
            applyBtn.disabled = false;
            statusDiv.innerHTML = `<span style="color:var(--color-error)">${data.error}</span>`;
            return;
        }
        window.finishBellNotification(notifId, "done");

        // Si el usuario navegó a otra página mientras se recortaba (ya
        // posible ahora que esto no bloquea con un overlay), este botón
        // ya no está en el DOM -- no tiene sentido enviar el form que
        // avanza AL SIGUIENTE PASO de un asistente que ya no se ve.
        if (!document.body.contains(applyBtn)) return;

        statusDiv.innerHTML = `<p class="caption">Video recortado guardado (${data.n_frames} frames). Aplicando...</p>`;
        const form = document.createElement("form");
        form.method = "post";
        form.action = "/setup/use-trimmed";
        form.innerHTML = `<input type="hidden" name="store" value="${store}">
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
        const resp = await fetch(`/api/store/${encodeURIComponent(btn.dataset.store)}/generate-preview`, {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ video_path: btn.dataset.video }),
        });
        const data = await resp.json();
        if (!data.ok) {
            btn.disabled = false;
            progressDiv.innerHTML = window.alertHtml("error", escapeHtmlSetup(data.error));
            window.refreshIcons();
            return;
        }
        progressDiv.innerHTML = window.alertHtml(
            "info",
            "Generando la vista previa en segundo plano -- revisa la campana de notificaciones (arriba) para ver el progreso. Podés seguir navegando mientras tanto."
        );
        window.refreshIcons();
        window.startJobPolling(btn.dataset.store, "preview", `Vista previa de calor: ${btn.dataset.store}`, {
            // Si el usuario se quedó en esta página, refresca para mostrar
            // la vista previa recién generada -- si ya se fue, no tiene
            // sentido recargar una página que ya no está viendo.
            onDone: () => { if (document.getElementById("generate-preview-btn")) window.location.reload(); },
            onError: () => { btn.disabled = false; },
        });
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
        const payload = {
            video_path: document.getElementById("calibration-root")?.dataset.video || "",
            skip_hands: document.getElementById("skip-hands-check").checked,
            record_history: document.getElementById("record-history-check").checked,
            run_date: document.getElementById("run-date-input").value || null,
            body_max_gap: parseFloat(document.getElementById("body-max-gap").value),
            body_max_speed: parseFloat(document.getElementById("body-max-speed").value),
            hand_max_gap: parseFloat(document.getElementById("hand-max-gap").value),
            hand_max_speed: parseFloat(document.getElementById("hand-max-speed").value),
            device: document.getElementById("device-select")?.value || "auto",
        };
        const resp = await fetch(`/api/store/${encodeURIComponent(btn.dataset.store)}/process`, {
            method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
        });
        const data = await resp.json();
        if (!data.ok) {
            progressDiv.innerHTML = window.alertHtml("error", escapeHtmlSetup(data.error));
            window.refreshIcons();
            btn.disabled = false;
            return;
        }
        progressDiv.innerHTML = window.alertHtml(
            "info",
            "Procesando en segundo plano -- revisa la campana de notificaciones (arriba) para ver el progreso. Podés seguir navegando mientras tanto."
        );
        window.refreshIcons();
        const resultsUrl = `/store/results?store=${encodeURIComponent(btn.dataset.store)}`;
        window.startJobPolling(btn.dataset.store, "process", `Procesando video: ${btn.dataset.store}`, {
            resultUrl: resultsUrl,
            // Si el usuario se quedó en el asistente, lo lleva a resultados
            // igual que antes -- si ya navegó a otro lado, la notificación
            // en la campana le ofrece el mismo link ("Ver resultados") sin
            // secuestrar la página que esté viendo en ese momento.
            onDone: () => { if (document.getElementById("process-btn")) window.location.href = resultsUrl; },
            onError: () => { const b = document.getElementById("process-btn"); if (b) b.disabled = false; },
        });
    });
}

// El sondeo de /status (antes pollJob() acá mismo) ahora vive a nivel
// global en static/js/job-bell.js (window.startJobPolling) -- así
// sobrevive a la navegación entre páginas en vez de cortarse cada vez
// que el usuario se va de este asistente. Este archivo solo dispara el
// job y le pasa un nombre legible + callbacks opcionales.

function escapeHtmlSetup(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
}
