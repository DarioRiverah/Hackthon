// Simulador multi-cámara (vista combinada de tienda) -- misma mecánica
// que el simulador de una sola cámara (results.js:initSimulator), pero
// llama a /api/tienda/<id>/simulate con claves compuestas
// "camara::zone_id", y agrega la advertencia de comparabilidad +
// fecha/duración de referencia de cada cámara cuando el origen y el
// destino NO son de la misma cámara (ver docs/architecture.md sección 32).

document.addEventListener("DOMContentLoaded", () => {
    window.initTiendaCombinadaPage();
});

// .kpi-panorama-grid es el ancla de "esta es la vista combinada de
// tienda" para static/js/main.js:navigateTo() -- se renderiza siempre
// (a diferencia de #tienda-sim-run-btn, que solo existe si hay 2+
// zonas con datos de interacción).
window.initTiendaCombinadaPage = function initTiendaCombinadaPage() {
    if (!document.querySelector(".kpi-panorama-grid")) return;

    // Independiente del simulador de abajo (que puede no existir si la
    // tienda no tiene 2+ zonas con datos de interacción) -- la zona de
    // peligro SIEMPRE se renderiza en esta página, así que se engancha
    // antes del `if (!runBtn) return;` de más abajo, no después.
    initEliminarTiendaDialog();

    const runBtn = document.getElementById("tienda-sim-run-btn");
    if (!runBtn) return;

    runBtn.addEventListener("click", async () => {
        const tienda = runBtn.dataset.tienda;
        const fromKey = document.getElementById("tienda-sim-from").value;
        const toKey = document.getElementById("tienda-sim-to").value;
        const resultDiv = document.getElementById("tienda-sim-result");

        if (fromKey === toKey) {
            resultDiv.innerHTML = window.alertHtml("warning", "Elige dos zonas distintas.");
            window.refreshIcons();
            return;
        }

        resultDiv.innerHTML = '<p class="caption">Simulando...</p>';
        try {
            const resp = await fetch(`/api/tienda/${encodeURIComponent(tienda)}/simulate`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ from_id: fromKey, to_id: toKey }),
            });
            const data = await resp.json();

            if (!data.ok) {
                let html = window.alertHtml("warning", escapeHtmlTienda(data.error));
                if (data.same_camara === false) html += comparabilidadHtml(data);
                resultDiv.innerHTML = html;
                window.refreshIcons();
                return;
            }

            resultDiv.innerHTML = buildTiendaSimResultHtml(data);
            window.refreshIcons();
        } catch (err) {
            resultDiv.innerHTML = window.alertHtml("error", "No se pudo calcular la simulación. Intenta de nuevo.");
            window.refreshIcons();
        }
    });

    const recommendBtn = document.getElementById("tienda-sim-recommend-btn");
    if (!recommendBtn) return;

    recommendBtn.addEventListener("click", async () => {
        const tienda = recommendBtn.dataset.tienda;
        const fromKey = document.getElementById("tienda-sim-from").value;
        const toSelect = document.getElementById("tienda-sim-to");
        const resultDiv = document.getElementById("tienda-sim-result");

        resultDiv.innerHTML = '<p class="caption">Comparando contra todas las zonas candidatas de todas las cámaras...</p>';
        try {
            const resp = await fetch(`/api/tienda/${encodeURIComponent(tienda)}/simulate/recommend`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ from_id: fromKey }),
            });
            const data = await resp.json();

            if (!data.ok) {
                // no_improvement: zona ya bien ubicada, no es un error real.
                let html = window.alertHtml(data.no_improvement ? "info" : "warning", escapeHtmlTienda(data.error));
                if (data.same_camara === false) html += comparabilidadHtml(data);
                resultDiv.innerHTML = html;
                window.refreshIcons();
                return;
            }

            // Auto-completa el selector manual con el destino recomendado
            // (puede quedar en otra cámara) -- el control manual sigue
            // disponible para elegir otra combinación después.
            if (data.to_key != null && toSelect) toSelect.value = data.to_key;

            let html = buildTiendaSimResultHtml(data, { nEvaluados: data.n_candidatos_evaluados });
            if (!data.same_camara) html += comparabilidadHtml(data);

            resultDiv.innerHTML = html;
            window.refreshIcons();
        } catch (err) {
            resultDiv.innerHTML = window.alertHtml("error", "No se pudo calcular la recomendación. Intenta de nuevo.");
            window.refreshIcons();
        }
    });
};

// Arma el panel de resultado -- compartido entre "Simular" (destino
// elegido a mano) y "Recomendarme el mejor destino". recommendMeta
// (opcional): { nEvaluados } -- cuando viene, antepone un aviso
// explícito de qué zona (y cámara) se recomendó y contra cuántas
// candidatas se comparó, nunca solo el resultado numérico.
function buildTiendaSimResultHtml(data, recommendMeta) {
    const r = data.result;
    const positive = r.cambio_pct > 0;
    const messageKind = positive ? "success" : "info";
    const message = positive
        ? `Si el producto de '${data.from_label}' generara el mismo interés por visitante en ` +
          `'${data.to_label}' (que tiene más tráfico: ${data.visits_to.toFixed(0)} vs ${data.visits_from.toFixed(0)} ` +
          `visitas), podría pasar de ${r.interacciones_actuales.toFixed(0)} a ${r.interacciones_simuladas.toFixed(1)} ` +
          `interacciones -- un aumento estimado de ${r.cambio_pct.toFixed(0)}%.`
        : `'${data.to_label}' tiene menos tráfico que '${data.from_label}' ` +
          `(${data.visits_to.toFixed(0)} vs ${data.visits_from.toFixed(0)} visitas), así que este movimiento ` +
          `probablemente reduciría la interacción total, no la aumentaría.`;

    const recommendBanner = recommendMeta
        ? `<div style="margin-bottom:var(--space-4);">${window.alertHtml(
              "success",
              `Recomendación: comparamos '${escapeHtmlTienda(data.from_label)}' contra ${recommendMeta.nEvaluados} ` +
              `zona(s) candidata(s) de todas las cámaras de la tienda -- el mejor destino encontrado es ` +
              `<strong>'${escapeHtmlTienda(data.to_label)}'</strong> (cámara ${escapeHtmlTienda(data.to_camara)}).`
          )}</div>`
        : "";

    return `
        <div class="panel">
            <h4>Resultado de la simulación</h4>
            ${recommendBanner}
            <div class="metric-row">
                <div class="metric"><div class="metric-label">Interacciones actuales</div><div class="metric-value">${r.interacciones_actuales.toFixed(0)}</div></div>
                <div class="metric"><div class="metric-label">Interacciones estimadas en '${escapeHtmlTienda(data.to_label)}'</div><div class="metric-value">${r.interacciones_simuladas.toFixed(1)}</div></div>
                <div class="metric"><div class="metric-label">Cambio estimado</div><div class="metric-value">${r.cambio_pct >= 0 ? "+" : ""}${r.cambio_pct.toFixed(0)}%</div></div>
            </div>
            <div style="margin-top:var(--space-4);">${window.alertHtml(messageKind, message)}</div>
            <p class="caption">Recuerda: esta es una extrapolación basada en el patrón de tráfico observado, asumiendo que el interés del producto por visitante no cambia entre zonas.</p>
        </div>`;
}

// "Eliminar tienda completa" -- mismo patrón de diálogo real
// (<dialog>) + confirmación por nombre escrito ya usado para "Eliminar
// cámara completa" en static/js/data_management.js:dialog-confirm-camara,
// pero comparando contra el LABEL de la tienda en vez del id de una
// cámara. El backend (dashboard/routes/api_routes.py:eliminar_tienda_completa)
// reusa data_management_service.delete_camera_completely() una vez por
// cámara -- esta función solo arma el diálogo y llama a esa ruta.
function initEliminarTiendaDialog() {
    const btn = document.getElementById("btn-eliminar-tienda");
    const dialog = document.getElementById("dialog-confirm-tienda");
    const feedback = document.getElementById("tienda-eliminar-feedback");
    if (!btn || !dialog || !feedback) return;

    const input = document.getElementById("dialog-tienda-input");
    const confirmBtn = document.getElementById("dialog-tienda-confirm");
    const cancelBtn = document.getElementById("dialog-tienda-cancel");
    const tiendaId = feedback.dataset.tienda;
    const tiendaLabel = btn.dataset.tiendaLabel;

    btn.addEventListener("click", () => {
        input.value = "";
        confirmBtn.disabled = true;
        dialog.showModal();
        input.focus();
    });
    cancelBtn.addEventListener("click", () => dialog.close());
    input.addEventListener("input", () => {
        confirmBtn.disabled = input.value.trim() !== tiendaLabel;
    });
    confirmBtn.addEventListener("click", async () => {
        if (input.value.trim() !== tiendaLabel) return;
        dialog.close();
        try {
            const resp = await fetch(`/api/tienda/${encodeURIComponent(tiendaId)}/eliminar`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ confirmacion: input.value.trim() }),
            });
            const data = await resp.json();
            if (data.ok) {
                feedback.innerHTML = window.alertHtml("success", "Tienda eliminada por completo. Redirigiendo...");
                window.refreshIcons();
                setTimeout(() => { window.location.href = "/tienda"; }, 1500);
                return;
            }
            // Reporte explícito de qué se pudo borrar y qué no -- ver
            // data_management_service.delete_tienda_completa(): si
            // falló a mitad de camino, "eliminadas"/"fallidas" traen el
            // detalle cámara por cámara, no solo un mensaje genérico.
            let msg = data.error || "No se pudo eliminar la tienda.";
            if (data.eliminadas && data.eliminadas.length) {
                msg += ` Cámaras eliminadas: ${data.eliminadas.map(escapeHtmlTienda).join(", ")}.`;
            }
            if (data.fallidas && data.fallidas.length) {
                msg += ` Cámaras que fallaron: ${data.fallidas.map((f) => escapeHtmlTienda(f.camara_id)).join(", ")}.`;
            }
            feedback.innerHTML = window.alertHtml("error", msg);
            window.refreshIcons();
        } catch (err) {
            feedback.innerHTML = window.alertHtml("error", "No se pudo eliminar la tienda. Intenta de nuevo.");
            window.refreshIcons();
        }
    });
}

// Advertencia OBLIGATORIA (no oculta en un tooltip) cuando origen y
// destino son de cámaras distintas -- muestra explícitamente ambas
// fechas/duraciones de referencia, no solo el resultado numérico.
function comparabilidadHtml(data) {
    const fmtDur = (s) => (s || s === 0) ? `${Math.round(s)}s` : "N/D";
    const fmtFecha = (f) => f || "N/D";
    const msg = `
        <strong>'${escapeHtmlTienda(data.from_label)}'</strong> (cámara ${escapeHtmlTienda(data.from_camara)},
        grabación de referencia: ${fmtFecha(data.from_fecha_referencia)}, duración: ${fmtDur(data.from_duracion_referencia)})
        y <strong>'${escapeHtmlTienda(data.to_label)}'</strong> (cámara ${escapeHtmlTienda(data.to_camara)},
        grabación de referencia: ${fmtFecha(data.to_fecha_referencia)}, duración: ${fmtDur(data.to_duracion_referencia)})
        vienen de cámaras distintas, con distinta duración/fecha de grabación -- compará este resultado con
        cuidado, no son necesariamente períodos equivalentes.`;
    return `<div style="margin-top:var(--space-3);">${window.alertHtml("warning", msg)}</div>`;
}

function escapeHtmlTienda(str) {
    const div = document.createElement("div");
    div.textContent = str == null ? "" : String(str);
    return div.innerHTML;
}
