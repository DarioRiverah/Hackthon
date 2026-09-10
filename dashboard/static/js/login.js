// Lógica de la página de login (templates/login.html): registro inicial
// (primer arranque, sin cuenta todavía), login por contraseña, y login
// por patrón de manos (captura vía window.HandPatternCapture, ver
// static/js/hand_pattern.js). Página standalone (no pasa por
// navigateTo()/pjax), así que usa fetch() + redirect normal.

document.addEventListener("DOMContentLoaded", () => {
    initRegisterForm();
    initPasswordLogin();
    initPatternLogin();
});

// Mismo markup que window.alertHtml en static/js/main.js -- login.html
// es una página standalone (sin sidebar/pjax) que no carga main.js, así
// que se reconstruye acá para que la alerta se vea igual que en el
// resto del dashboard.
function alertHtml(kind, messageHtml) {
    const icons = { info: "info", success: "circle-check", warning: "triangle-alert", error: "circle-x" };
    return `<div class="alert alert-${kind}"><i data-lucide="${icons[kind] || "info"}" class="icon" style="--icon-size:18px;"></i><div>${messageHtml}</div></div>`;
}

function showAlert(kind, text) {
    const el = document.getElementById("auth-alert");
    if (!el) return;
    el.innerHTML = alertHtml(kind, escapeHtml(text));
    if (window.lucide) window.lucide.createIcons();
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
}

function initRegisterForm() {
    const form = document.getElementById("register-form");
    if (!form) return;
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const username = document.getElementById("register-username").value.trim();
        const password = document.getElementById("register-password").value;
        try {
            const resp = await fetch("/login/register-account", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password }),
            });
            const data = await resp.json();
            if (!data.ok) { showAlert("warning", data.error); return; }
            window.location.href = "/";
        } catch (err) {
            showAlert("error", "No se pudo crear la cuenta. Intenta de nuevo.");
        }
    });
}

function initPasswordLogin() {
    const form = document.getElementById("login-form");
    if (!form) return;
    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const username = document.getElementById("login-username").value.trim();
        const password = document.getElementById("login-password").value;
        try {
            const resp = await fetch("/login/password", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ username, password }),
            });
            const data = await resp.json();
            if (!data.ok) { showAlert("warning", data.error); return; }
            window.location.href = "/";
        } catch (err) {
            showAlert("error", "No se pudo iniciar sesión. Intenta de nuevo.");
        }
    });
}

function initPatternLogin() {
    const showBtn = document.getElementById("show-pattern-login-btn");
    const usePasswordBtn = document.getElementById("use-password-btn");
    const captureBtn = document.getElementById("pattern-capture-btn");
    const passwordView = document.getElementById("password-login-view");
    const patternView = document.getElementById("pattern-login-view");
    if (!showBtn || !patternView) return; // sin patrón registrado, este bloque ni existe en el DOM.

    const statusEl = document.getElementById("pattern-status");
    const dots = document.querySelectorAll("#pattern-progress .dot");
    let capture = null;

    function updateProgress(count) {
        dots.forEach((d, i) => d.classList.toggle("done", i < count));
    }

    function backToPassword() {
        if (capture) { capture.stop(); capture = null; }
        patternView.hidden = true;
        passwordView.hidden = false;
    }

    async function handlePatternDone(poses) {
        try {
            const resp = await fetch("/login/pattern", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ poses }),
            });
            const data = await resp.json();
            if (!data.ok) {
                backToPassword();
                showAlert("warning", data.error);
                return;
            }
            window.location.href = "/";
        } catch (err) {
            backToPassword();
            showAlert("error", "No se pudo iniciar sesión con el patrón. Intenta de nuevo.");
        }
    }

    showBtn.addEventListener("click", () => {
        passwordView.hidden = true;
        patternView.hidden = false;
        updateProgress(0);
        capture = new window.HandPatternCapture({
            video: document.getElementById("pattern-video"),
            canvas: document.getElementById("pattern-canvas"),
            onStatus: (text) => { statusEl.textContent = text; },
            onProgress: (count) => updateProgress(count),
            onDone: handlePatternDone,
            onError: (text) => { backToPassword(); showAlert("error", text); },
        });
        capture.start();
    });

    if (captureBtn) captureBtn.addEventListener("click", () => { if (capture) capture.captureNow(); });
    usePasswordBtn.addEventListener("click", backToPassword);
}
