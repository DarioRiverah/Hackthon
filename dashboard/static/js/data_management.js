// Gestión de datos: cada botón "Eliminar" abre un <dialog> real de
// confirmación (nunca borra con un solo clic) -- ver
// docs/architecture.md sección 35.

document.addEventListener("DOMContentLoaded", () => {
    window.initDataManagementPage();
});

// #datos-feedback es el ancla de "esta es la página de Gestión de
// datos" para static/js/main.js:navigateTo() -- también carga ahí el
// nombre de la cámara actual (data-store), en vez del antiguo
// window.DATOS_CAMARA_NOMBRE global: una variable global quedaba
// desactualizada al navegar sin recarga a OTRA cámara, porque el
// <script> inline que la fijaba solo se ejecutaba en la carga
// completa de la página, no en cada intercambio de contenido.
window.initDataManagementPage = function initDataManagementPage() {
    const feedback = document.getElementById("datos-feedback");
    if (!feedback) return;
    const store = feedback.dataset.store;

    const simpleDialog = document.getElementById("dialog-confirm-simple");
    const simpleTitle = document.getElementById("dialog-simple-title");
    const simpleBody = document.getElementById("dialog-simple-body");
    const simpleCancel = document.getElementById("dialog-simple-cancel");
    const simpleConfirm = document.getElementById("dialog-simple-confirm");

    simpleCancel.addEventListener("click", () => simpleDialog.close());

    // Abre el diálogo simple, y arma la acción a ejecutar si se confirma.
    function askSimple(title, body, onConfirm) {
        simpleTitle.textContent = title;
        simpleBody.textContent = body;
        simpleConfirm.onclick = async () => {
            simpleDialog.close();
            await onConfirm();
        };
        simpleDialog.showModal();
    }

    async function postJson(url, body) {
        const resp = await fetch(url, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(body || {}),
        });
        return resp.json();
    }

    function showFeedback(kind, message) {
        feedback.innerHTML = window.alertHtml(kind, message);
        window.refreshIcons();
    }

    const btnVideo = document.getElementById("btn-eliminar-video");
    if (btnVideo) {
        btnVideo.addEventListener("click", () => {
            askSimple(
                "Eliminar video(s) crudo(s)",
                "Sin el video original, esta cámara no se podrá reprocesar hasta que subas uno nuevo. Los resultados ya procesados y el historial archivado NO se ven afectados. ¿Continuar?",
                async () => {
                    const data = await postJson(`/api/store/${encodeURIComponent(store)}/datos/eliminar-video`);
                    if (data.ok) {
                        showFeedback("success", `Video(s) crudo(s) eliminado(s) (${data.n_files} archivo(s)).`);
                        setTimeout(() => window.location.reload(), 1200);
                    } else {
                        showFeedback("error", data.error || "No se pudo eliminar el video.");
                    }
                }
            );
        });
    }

    const btnResultados = document.getElementById("btn-eliminar-resultados");
    if (btnResultados) {
        btnResultados.addEventListener("click", () => {
            askSimple(
                "Eliminar resultados actuales",
                "La cámara quedará calibrada pero sin procesar, como si nunca se hubiera corrido el pipeline. El video crudo y el historial archivado NO se ven afectados. ¿Continuar?",
                async () => {
                    const data = await postJson(`/api/store/${encodeURIComponent(store)}/datos/eliminar-resultados`);
                    if (data.ok) {
                        showFeedback("success", `Resultados eliminados (${data.n_files} archivo(s)).`);
                        setTimeout(() => window.location.reload(), 1200);
                    } else {
                        showFeedback("error", data.error || "No se pudieron eliminar los resultados.");
                    }
                }
            );
        });
    }

    document.querySelectorAll(".btn-eliminar-fecha").forEach((btn) => {
        btn.addEventListener("click", () => {
            const fecha = btn.dataset.fecha;
            askSimple(
                `Eliminar fecha archivada "${fecha}"`,
                "Se borra tanto la carpeta archivada como su registro en el historial de Tendencias. Esta fecha ya no aparecerá para comparar ni para ver en modo lectura. ¿Continuar?",
                async () => {
                    const data = await postJson(`/api/store/${encodeURIComponent(store)}/datos/eliminar-fecha`, { fecha });
                    if (data.ok) {
                        showFeedback("success", `Fecha "${fecha}" eliminada.`);
                        setTimeout(() => window.location.reload(), 1200);
                    } else {
                        showFeedback("error", data.error || "No se pudo eliminar esa fecha.");
                    }
                }
            );
        });
    });

    const camaraDialog = document.getElementById("dialog-confirm-camara");
    const camaraInput = document.getElementById("dialog-camara-input");
    const camaraConfirmBtn = document.getElementById("dialog-camara-confirm");
    const camaraCancelBtn = document.getElementById("dialog-camara-cancel");
    const btnCamara = document.getElementById("btn-eliminar-camara");

    if (btnCamara) {
        btnCamara.addEventListener("click", () => {
            camaraInput.value = "";
            camaraConfirmBtn.disabled = true;
            camaraDialog.showModal();
            camaraInput.focus();
        });
    }
    camaraCancelBtn.addEventListener("click", () => camaraDialog.close());
    camaraInput.addEventListener("input", () => {
        camaraConfirmBtn.disabled = camaraInput.value.trim() !== store;
    });
    camaraConfirmBtn.addEventListener("click", async () => {
        if (camaraInput.value.trim() !== store) return;
        camaraDialog.close();
        const data = await postJson(`/api/store/${encodeURIComponent(store)}/datos/eliminar-camara`, {
            confirmacion: camaraInput.value.trim(),
        });
        if (data.ok) {
            showFeedback("success", "Cámara eliminada por completo. Redirigiendo...");
            setTimeout(() => { window.location.href = "/tienda"; }, 1500);
        } else {
            showFeedback("error", data.error || "No se pudo eliminar la cámara.");
        }
    });
};
