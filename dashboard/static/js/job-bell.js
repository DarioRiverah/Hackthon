// Campana de notificaciones (botón "🔔" en la barra lateral, ver
// templates/layout.html) -- reemplaza el antiguo overlay de pantalla
// completa que bloqueaba la navegación mientras corría una vista previa
// de calor, un procesamiento de video, o un recorte (ver
// docs/architecture.md). Vive FUERA de #sidebar-dynamic/#pjax-main (ver
// layout.html) para sobrevivir a la navegación sin recarga -- igual que
// el widget de ayuda (help-widget.js), del que este archivo copia el
// patrón de abrir/cerrar panel.
//
// Dos formas de anunciar una tarea acá:
//   window.startJobPolling(store, jobType, label, {onDone, onError, resultUrl})
//       Para jobs de dashboard/job_manager.py (vista previa, procesar):
//       sondea GET /api/store/<store>/status?job=<jobType> cada 1.5s y
//       refleja step_num/step_total en la barra de progreso -- MISMA
//       lógica de sondeo que antes vivía en setup.js:pollJob(), solo que
//       ahora corre acá (nivel global) en vez de atada a la página del
//       asistente de configuración.
//   window.addBellNotification(label) / window.finishBellNotification(id, status)
//       Para acciones que NO pasan por job_manager (ej. recortar video,
//       que es una sola petición síncrona) pero igual queremos que
//       aparezcan en la campana si el usuario navega lejos mientras
//       esperan una respuesta.
(function () {
    const JOB_LABELS = {
        preview: "Generando vista previa de calor",
        process: "Procesando video",
    };

    // id -> { id, mode: "poll"|"local", store, jobType, label, status,
    //         stepNum, stepTotal, stepDescription, unseen, resultUrl,
    //         onDone, onError }
    const notifications = new Map();
    let pollTimer = null;
    let localIdSeq = 0;

    function ensurePollTimer() {
        if (pollTimer) return;
        pollTimer = setInterval(pollRunningJobs, 1500);
        pollRunningJobs(); // primer chequeo inmediato, no esperar 1.5s
    }

    async function pollRunningJobs() {
        const running = [...notifications.values()].filter((n) => n.mode === "poll" && n.status === "running");
        if (!running.length) {
            clearInterval(pollTimer);
            pollTimer = null;
            return;
        }
        await Promise.all(running.map(async (n) => {
            let job;
            try {
                const resp = await fetch(`/api/store/${encodeURIComponent(n.store)}/status?job=${n.jobType}`);
                job = await resp.json();
            } catch (e) {
                return; // red caída momentáneamente -- se reintenta en el próximo tick
            }
            n.stepNum = job.step_num || 0;
            n.stepTotal = job.step_total || 0;
            n.stepDescription = job.step_description || "";
            if (job.status === "done") {
                n.status = "done";
                n.unseen = true;
                if (n.onDone) n.onDone();
            } else if (job.status === "error") {
                n.status = "error";
                n.unseen = true;
                if (n.onError) n.onError();
            }
        }));
        render();
        updateIndicator();
    }

    window.startJobPolling = function startJobPolling(store, jobType, label, callbacks) {
        const id = `${store}:${jobType}`;
        const existing = notifications.get(id);
        if (existing && existing.status === "running") return id; // ya en curso, no duplicar

        callbacks = callbacks || {};
        notifications.set(id, {
            id, mode: "poll", store, jobType,
            label: label || JOB_LABELS[jobType] || "Procesando",
            status: "running", stepNum: 0, stepTotal: 0, stepDescription: "Preparando...",
            unseen: false,
            resultUrl: callbacks.resultUrl || null,
            onDone: callbacks.onDone || null,
            onError: callbacks.onError || null,
        });
        render();
        updateIndicator();
        ensurePollTimer();
        return id;
    };

    window.addBellNotification = function addBellNotification(label) {
        const id = `local:${++localIdSeq}`;
        notifications.set(id, { id, mode: "local", label, status: "running", unseen: false });
        render();
        updateIndicator();
        return id;
    };

    window.finishBellNotification = function finishBellNotification(id, status) {
        const n = notifications.get(id);
        if (!n) return;
        n.status = status;
        n.unseen = true;
        render();
        updateIndicator();
    };

    function hasRunning() {
        return [...notifications.values()].some((n) => n.status === "running");
    }
    function hasUnseenFinished() {
        return [...notifications.values()].some((n) => n.status !== "running" && n.unseen);
    }

    // El punto (activo/terminado) y la sacudida de la campana son la
    // señal #4/#5 del pedido: un job corriendo se ve distinto de uno
    // recién terminado, y el indicador de "terminado" se queda prendido
    // hasta que el usuario realmente abra el panel (ver markSeen()).
    function updateIndicator() {
        const dot = document.getElementById("job-bell-dot");
        const toggleBtn = document.getElementById("job-bell-toggle");
        if (!dot || !toggleBtn) return;

        const unseenFinished = hasUnseenFinished();
        const running = hasRunning();

        if (unseenFinished) {
            dot.hidden = false;
            dot.classList.remove("is-active");
            dot.classList.add("is-done");
            toggleBtn.classList.remove("is-shaking");
            void toggleBtn.offsetWidth; // reinicia la animación aunque ya estuviera "sacudiéndose"
            toggleBtn.classList.add("is-shaking");
        } else if (running) {
            dot.hidden = false;
            dot.classList.add("is-active");
            dot.classList.remove("is-done");
        } else {
            dot.hidden = true;
            dot.classList.remove("is-active", "is-done");
        }
    }

    function statusLabel(n) {
        if (n.status === "running") {
            if (n.mode === "poll" && n.stepTotal > 0) return `Paso ${n.stepNum} de ${n.stepTotal}: ${n.stepDescription}`;
            if (n.mode === "poll" && n.stepDescription) return n.stepDescription;
            return "En curso...";
        }
        return n.status === "done" ? "Completado" : "No se pudo completar";
    }

    function renderItem(n) {
        const pct = n.stepTotal > 0 ? Math.min(100, Math.max(0, (n.stepNum / n.stepTotal) * 100)) : null;
        const icon = n.status === "running" ? "loader-circle" : n.status === "done" ? "circle-check" : "circle-x";
        const statusClass = n.status === "running" ? "is-running" : n.status === "done" ? "is-done" : "is-error";
        const showLink = n.status === "done" && n.resultUrl;
        return `
            <div class="job-bell-item ${statusClass}">
                <div class="job-bell-item-row">
                    <i data-lucide="${icon}" class="icon job-bell-item-icon" style="--icon-size:16px;"></i>
                    <div class="job-bell-item-text">
                        <div class="job-bell-item-label">${escapeHtml(n.label)}</div>
                        <div class="job-bell-item-status">${escapeHtml(statusLabel(n))}</div>
                    </div>
                </div>
                ${n.status === "running" && pct !== null ? `
                <div class="job-bell-progress"><div class="job-bell-progress-fill" style="width:${pct}%;"></div></div>
                ` : ""}
                ${showLink ? `<a href="${n.resultUrl}" class="job-bell-item-link" data-bell-nav="${n.resultUrl}">Ver resultados <i data-lucide="arrow-right" class="icon" style="--icon-size:13px;"></i></a>` : ""}
            </div>`;
    }

    function render() {
        const body = document.getElementById("job-bell-body");
        if (!body) return;
        const list = [...notifications.values()].reverse(); // más reciente primero
        if (!list.length) {
            body.innerHTML = '<p class="caption job-bell-empty">Sin tareas por ahora. Acá vas a ver el progreso de recortes, vistas previas y procesamientos de video.</p>';
            return;
        }
        body.innerHTML = list.map(renderItem).join("");
        window.refreshIcons();
    }

    function escapeHtml(str) {
        const div = document.createElement("div");
        div.textContent = str == null ? "" : String(str);
        return div.innerHTML;
    }

    // El botón + panel ahora viven DENTRO de .page-hero (ver
    // templates/layout.html y layout_fragment.html) -- a diferencia de
    // la barra lateral, .page-hero SÍ se reemplaza por completo en cada
    // navegación sin recarga (main.js:navigateTo() reescribe
    // .main-content entero), así que estas referencias hay que
    // refrescarlas en cada init, no capturarlas una sola vez.
    let toggleBtn = null;
    let panel = null;
    let closeBtn = null;

    function isOpen() {
        return !!panel && panel.style.display !== "none";
    }

    // Se limpia el indicador de "terminado" recién cuando el usuario
    // ABRE el panel y lo ve -- pedido explícito (punto 5), no basta con
    // que el job termine.
    function markSeen() {
        let changed = false;
        notifications.forEach((n) => {
            if (n.status !== "running" && n.unseen) {
                n.unseen = false;
                changed = true;
            }
        });
        if (changed) updateIndicator();
    }

    function openPanel() {
        if (!panel || !toggleBtn) return;
        panel.style.display = "flex";
        toggleBtn.setAttribute("aria-expanded", "true");
        render();
        markSeen();
    }

    function closePanel() {
        if (!panel || !toggleBtn) return;
        panel.style.display = "none";
        toggleBtn.setAttribute("aria-expanded", "false");
    }

    // Se registran UNA sola vez a nivel módulo (document y el atajo de
    // teclado nunca se destruyen con la navegación) -- usan las
    // variables de arriba, que window.initJobBell() actualiza cada vez
    // que .page-hero se vuelve a renderizar, así siempre apuntan al
    // panel/botón vigentes en vez de a nodos ya removidos del DOM.
    document.addEventListener("keydown", (evt) => {
        if (evt.key === "Escape" && isOpen()) closePanel();
    });

    window.initJobBell = function initJobBell() {
        toggleBtn = document.getElementById("job-bell-toggle");
        panel = document.getElementById("job-bell-panel");
        const body = document.getElementById("job-bell-body");
        closeBtn = document.getElementById("job-bell-close");
        if (!toggleBtn || !panel || !body || !closeBtn) return;

        toggleBtn.addEventListener("click", () => { if (isOpen()) closePanel(); else openPanel(); });
        toggleBtn.addEventListener("animationend", () => toggleBtn.classList.remove("is-shaking"));
        closeBtn.addEventListener("click", closePanel);

        // Clic en "Ver resultados": navega con el mismo mecanismo sin
        // recarga que el resto de la app (ver main.js:navigateTo()) en
        // vez de una recarga completa.
        body.addEventListener("click", (evt) => {
            const link = evt.target.closest("[data-bell-nav]");
            if (!link) return;
            evt.preventDefault();
            closePanel();
            window.navigateTo(link.dataset.bellNav);
        });

        render();
        updateIndicator();
    };

    document.addEventListener("DOMContentLoaded", window.initJobBell);
})();
