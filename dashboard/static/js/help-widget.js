// Widget de ayuda flotante (botón "?" visible en toda la app, ver
// templates/layout.html). Preguntas frecuentes 100% predefinidas --
// el contenido vive en static/js/help-content.js, este archivo solo
// sabe abrir/cerrar el panel y dibujar lista <-> respuesta.
//
// Estado simple a propósito (pedido explícito): si el usuario cierra el
// panel a mitad de una respuesta y lo vuelve a abrir, arranca de nuevo
// en la lista de preguntas -- no hace falta recordar dónde iba.
(function () {
    function renderBlocks(blocks) {
        return blocks.map((block) => {
            if (block.type === "ol") {
                return `<ol class="help-steps">${block.items.map((i) => `<li>${i}</li>`).join("")}</ol>`;
            }
            if (block.type === "ul") {
                return `<ul class="help-steps help-steps-plain">${block.items.map((i) => `<li>${i}</li>`).join("")}</ul>`;
            }
            return `<p>${block.text}</p>`;
        }).join("");
    }

    function renderList(content) {
        const questionsHtml = content.questions.map((q) =>
            `<button type="button" class="help-question-btn" data-qid="${q.id}">${q.question}</button>`
        ).join("");
        return `
            <p class="help-greeting">${content.greeting}</p>
            <div class="help-question-list">${questionsHtml}</div>
        `;
    }

    function renderAnswer(question) {
        return `
            <button type="button" class="help-back-btn" id="help-back-btn">
                <i data-lucide="chevron-left" class="icon" style="--icon-size:14px;"></i> Volver a preguntas
            </button>
            <h5 class="help-answer-title">${question.question}</h5>
            <div class="help-answer-body">${renderBlocks(question.blocks)}</div>
        `;
    }

    function initHelpWidget() {
        const toggleBtn = document.getElementById("help-widget-toggle");
        const panel = document.getElementById("help-widget-panel");
        const body = document.getElementById("help-widget-body");
        const closeBtn = document.getElementById("help-widget-close");
        if (!toggleBtn || !panel || !body || !closeBtn) return;

        const content = window.HELP_CONTENT;

        function showList() {
            body.innerHTML = renderList(content);
            body.querySelectorAll(".help-question-btn").forEach((btn) => {
                btn.addEventListener("click", () => {
                    const q = content.questions.find((item) => item.id === btn.dataset.qid);
                    if (q) showAnswer(q);
                });
            });
        }

        function showAnswer(question) {
            body.innerHTML = renderAnswer(question);
            window.refreshIcons();
            document.getElementById("help-back-btn").addEventListener("click", showList);
            body.scrollTop = 0;
        }

        function isOpen() {
            return panel.style.display !== "none";
        }

        function openPanel() {
            panel.style.display = "flex";
            toggleBtn.setAttribute("aria-expanded", "true");
            showList();
        }

        function closePanel() {
            panel.style.display = "none";
            toggleBtn.setAttribute("aria-expanded", "false");
        }

        toggleBtn.addEventListener("click", () => {
            if (isOpen()) closePanel(); else openPanel();
        });
        closeBtn.addEventListener("click", closePanel);
        document.addEventListener("keydown", (evt) => {
            if (evt.key === "Escape" && isOpen()) closePanel();
        });
    }

    document.addEventListener("DOMContentLoaded", initHelpWidget);
})();
