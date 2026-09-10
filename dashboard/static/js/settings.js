// Página de Configuración (templates/settings.html, protegida por
// sesión): cambiar contraseña, y registrar/reemplazar el patrón de
// manos (misma captura que login.js, vía window.HandPatternCapture,
// ver static/js/hand_pattern.js). Cargado globalmente (ver
// templates/layout.html) e re-inicializado en cada navegación pjax
// (ver static/js/main.js:reinitAfterNavigation()) -- se protege solo
// con el "if (!anchor) return" de abajo, igual que las demás páginas.

document.addEventListener("DOMContentLoaded", () => {
    window.initSettingsPage();
});

window.initSettingsPage = function initSettingsPage() {
    const startBtn = document.getElementById("start-pattern-btn");
    if (!startBtn) return; // no estamos en /settings.

    initChangePassword();
    initPatternRegistration();
};

function initChangePassword() {
    const form = document.getElementById("change-password-form");
    if (!form) return;
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const alertDiv = document.getElementById("password-alert");
        const current_password = document.getElementById("current-password").value;
        const new_password = document.getElementById("new-password").value;
        try {
            const resp = await fetch("/settings/password", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ current_password, new_password }),
            });
            const data = await resp.json();
            alertDiv.innerHTML = window.alertHtml(data.ok ? "success" : "warning",
                data.ok ? "Contraseña actualizada." : escapeHtmlSettings(data.error));
            if (data.ok) form.reset();
            window.refreshIcons();
        } catch (err) {
            alertDiv.innerHTML = window.alertHtml("error", "No se pudo cambiar la contraseña. Intenta de nuevo.");
            window.refreshIcons();
        }
    });
}

function initPatternRegistration() {
    const startBtn = document.getElementById("start-pattern-btn");
    const idleView = document.getElementById("pattern-idle-view");
    const captureView = document.getElementById("pattern-capture-view");
    const captureBtn = document.getElementById("settings-capture-btn");
    const cancelBtn = document.getElementById("settings-cancel-btn");
    const statusEl = document.getElementById("settings-pattern-status");
    const alertDiv = document.getElementById("pattern-alert");
    const dots = document.querySelectorAll("#settings-pattern-progress .dot");
    let capture = null;

    function updateProgress(count) {
        dots.forEach((d, i) => d.style.background = i < count ? "var(--color-success)" : "var(--color-line)");
    }

    function backToIdle() {
        if (capture) { capture.stop(); capture = null; }
        captureView.hidden = true;
        idleView.hidden = false;
    }

    async function handleDone(poses) {
        try {
            const resp = await fetch("/settings/pattern", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ poses }),
            });
            const data = await resp.json();
            backToIdle();
            alertDiv.innerHTML = window.alertHtml(data.ok ? "success" : "warning",
                data.ok ? "Patrón de manos guardado." : escapeHtmlSettings(data.error));
            window.refreshIcons();
        } catch (err) {
            backToIdle();
            alertDiv.innerHTML = window.alertHtml("error", "No se pudo guardar el patrón. Intenta de nuevo.");
            window.refreshIcons();
        }
    }

    startBtn.addEventListener("click", () => {
        alertDiv.innerHTML = "";
        idleView.hidden = true;
        captureView.hidden = false;
        updateProgress(0);
        capture = new window.HandPatternCapture({
            video: document.getElementById("settings-pattern-video"),
            canvas: document.getElementById("settings-pattern-canvas"),
            onStatus: (text) => { statusEl.textContent = text; },
            onProgress: (count) => updateProgress(count),
            onDone: handleDone,
            onError: (text) => { backToIdle(); alertDiv.innerHTML = window.alertHtml("error", text); window.refreshIcons(); },
        });
        capture.start();
    });

    captureBtn.addEventListener("click", () => { if (capture) capture.captureNow(); });
    cancelBtn.addEventListener("click", backToIdle);
}

function escapeHtmlSettings(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
}
