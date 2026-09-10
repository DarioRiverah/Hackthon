// JS compartido por todas las páginas. Cada página carga además su
// propio script (results.js, setup.js, calibration.js) con la lógica
// específica que necesita.

// Lucide se carga con `defer` en el <head> (ver templates/layout.html);
// window.refreshIcons() es el punto único para (re)pintar los <i
// data-lucide="..."> presentes en el DOM en ese momento -- hace falta
// llamarlo de nuevo después de cualquier innerHTML dinámico que agregue
// íconos nuevos (los otros scripts lo hacen).
window.refreshIcons = function refreshIcons() {
    if (window.lucide) window.lucide.createIcons();
};

// Construye el mismo markup de alerta que templates/_macros.html (con
// ícono), para el HTML armado desde JS -- llamar a window.refreshIcons()
// después de insertar el resultado en el DOM.
window.alertHtml = function alertHtml(kind, messageHtml) {
    const icons = { info: "info", success: "circle-check", warning: "triangle-alert", error: "circle-x" };
    return `<div class="alert alert-${kind}"><i data-lucide="${icons[kind] || "info"}" class="icon" style="--icon-size:18px;"></i><div>${messageHtml}</div></div>`;
};

function prefersReducedMotion() {
    return window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}
window.prefersReducedMotion = prefersReducedMotion;

// Animación 1: conteo de KPIs -- solo para valores puramente numéricos
// (ej. NO la etiqueta de zona en "Zona con más tráfico"). Se salta por
// completo si el usuario pide menos movimiento.
function initKpiCountUp() {
    if (prefersReducedMotion()) return;
    document.querySelectorAll(".kpi-value").forEach((el) => {
        const raw = el.textContent.trim();
        const target = Number(raw);
        if (raw === "" || !Number.isFinite(target)) return;
        const duration = 700;
        const start = performance.now();
        function tick(now) {
            const progress = Math.min((now - start) / duration, 1);
            const eased = 1 - Math.pow(1 - progress, 3);
            el.textContent = progress < 1 ? String(Math.round(eased * target)) : raw;
            if (progress < 1) requestAnimationFrame(tick);
        }
        el.textContent = "0";
        requestAnimationFrame(tick);
    });
}

// Animación 2 (aparición escalonada de tarjetas KPI/zona) es 100% CSS
// -- @keyframes aparecer-tarjeta con fill-mode "backwards" (ver
// main.css), se dispara sola al cargar la página y cede el control a
// :hover (elevación, animación 3) en cuanto termina, sin JS.

// Animación 4: transición suave de expanders (<details>/<summary>) --
// el navegador no anima abrir/cerrar <details> de forma nativa, así que
// se anima `height` con la Web Animations API (nativa, sin librería).
function initExpanders() {
    document.querySelectorAll("details.expander").forEach((details) => {
        const summary = details.querySelector(":scope > summary");
        const body = details.querySelector(":scope > .expander-body");
        if (!summary || !body) return;

        let animation = null;
        let isClosing = false;
        let isExpanding = false;
        const duration = prefersReducedMotion() ? 1 : 220;

        summary.addEventListener("click", (event) => {
            event.preventDefault();
            details.style.overflow = "hidden";
            if (isClosing || !details.open) {
                openDetails();
            } else if (isExpanding || details.open) {
                shrink();
            }
        });

        function shrink() {
            isClosing = true;
            const startHeight = `${details.offsetHeight}px`;
            const endHeight = `${summary.offsetHeight}px`;
            if (animation) animation.cancel();
            animation = details.animate({ height: [startHeight, endHeight] }, { duration, easing: "ease-out" });
            animation.onfinish = () => onFinish(false);
            animation.oncancel = () => { isClosing = false; };
        }

        function openDetails() {
            details.style.height = `${details.offsetHeight}px`;
            details.open = true;
            requestAnimationFrame(expand);
        }

        function expand() {
            isExpanding = true;
            const startHeight = `${details.offsetHeight}px`;
            const endHeight = `${summary.offsetHeight + body.offsetHeight}px`;
            if (animation) animation.cancel();
            animation = details.animate({ height: [startHeight, endHeight] }, { duration, easing: "ease-out" });
            animation.onfinish = () => onFinish(true);
            animation.oncancel = () => { isExpanding = false; };
        }

        function onFinish(open) {
            details.open = open;
            animation = null;
            isClosing = false;
            isExpanding = false;
            details.style.height = "";
            details.style.overflow = "";
        }
    });
}

// Interruptor de tema claro/oscuro (checkbox #darkmode-toggle + interruptor
// animado de luna/nubes/estrellas SVG, ver .sky-toggle en main.css --
// portado de Uiverse.io, ver docs/architecture.md). El
// data-theme inicial ya lo puso el script inline en el <head> de
// layout.html (antes del primer pintado, para evitar flash) -- esto
// sincroniza el checkbox con ese estado, maneja el cambio, y guarda la
// preferencia explícita en localStorage para visitas futuras.
function initThemeToggle() {
    const toggle = document.getElementById("darkmode-toggle");
    if (!toggle) return;
    const root = document.documentElement;
    if (!root.hasAttribute('data-theme')) {
        root.setAttribute('data-theme', window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    }
    // Colores tipados (CSS.registerProperty): el navegador interpola
    // también los tonos de degradados/mezclas derivadas de estos tokens
    // durante la transición de tema (ver sección 18 de main.css), en vez
    // de saltar de golpe. Sin soporte, cae a `.theme-colors-fallback`
    // (transition clásica, ya definida en main.css).
    if (window.CSS && CSS.registerProperty) {
        const colors = ['bg', 'bg-alt', 'panel', 'ink', 'ink-muted', 'line',
            'accent', 'accent-text', 'on-accent', 'hot', 'hot-text', 'cold',
            'cold-text', 'zone-paso', 'zone-nicho', 'zone-none',
            'info', 'success', 'warning', 'error'];
        colors.forEach((name) => {
            try {
                CSS.registerProperty({ name: `--color-${name}`, syntax: '<color>', inherits: true, initialValue: 'transparent' });
            } catch (e) { /* Un token registrado previamente se puede reutilizar. */ }
        });
        ['category-tint-pct', 'hero-tint-pct'].forEach((name) => {
            try {
                CSS.registerProperty({ name: `--${name}`, syntax: '<percentage>', inherits: true, initialValue: '0%' });
            } catch (e) { /* Ya registrado. */ }
        });
        root.classList.add('theme-colors-ready');
    } else {
        root.classList.add('theme-colors-fallback');
    }
    let settleTimer;
    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const settle = () => {
        clearTimeout(settleTimer);
        root.classList.remove('theme-transition');
    };
    reducedMotion.addEventListener('change', settle);
    toggle.checked = root.getAttribute("data-theme") === "dark";
    toggle.addEventListener('change', () => {
        const next = toggle.checked ? 'dark' : 'light';
        settle();
        if (!reducedMotion.matches) {
            root.classList.add('theme-transition');
            settleTimer = setTimeout(settle, 720);
        }
        root.setAttribute('data-theme', next);
        try { localStorage.setItem('theme', next); } catch (e) { /* localStorage bloqueado -- el cambio sigue funcionando para esta visita, solo no persiste. */ }
    });
}

document.addEventListener("DOMContentLoaded", () => {
    window.refreshIcons();
    initKpiCountUp();
    initExpanders();
    initThemeToggle();
    initSidebarGlare();
    initTabsNavPills();
    initLightbox();
    initLogoutButton();
});

// #logout-btn vive en .brand-row (ver templates/layout.html), que --
// igual que <aside class="sidebar"> -- nunca se reemplaza por
// navigateTo(), así que se engancha UNA sola vez acá (mismo criterio
// que initThemeToggle()/initSidebarGlare(), no en reinitAfterNavigation()).
function initLogoutButton() {
    const btn = document.getElementById("logout-btn");
    if (!btn) return;
    btn.addEventListener("click", async () => {
        try {
            await fetch("/logout", { method: "POST" });
        } catch (err) {
            // Falla de red al cerrar sesión: igual mandamos al login --
            // si la cookie no se pudo borrar server-side, el antiguo
            // token puede seguir sirviendo hasta que expire, pero no
            // dejamos al usuario "atascado" en la página actual.
        }
        window.location.href = "/login";
    });
}

// =============================================================================
// Lightbox (visor de imagen ampliada) -- ver .lightbox-overlay/.lightbox-img
// en main.css sección 20. Se aplica a mano en cada template (clase
// "lightbox-img" en el <img>, ver results.html) a las imágenes de
// resultados/análisis (heatmaps, espagueti, plano de la tienda) -- nunca a
// íconos ni miniaturas.
//
// El overlay se crea UNA sola vez y se cuelga de <body>, que -- igual que
// <aside class="sidebar"> -- nunca se reemplaza por navigateTo() (solo
// .main-content y #sidebar-dynamic lo hacen, ver el bloque de navegación sin
// recarga más abajo). El clic que abre el lightbox se captura por
// delegación de eventos sobre `document` (mismo patrón que el listener de
// enlaces de la sidebar, más abajo en este archivo), así que cubre también
// imágenes .lightbox-img que lleguen en contenido cargado dinámicamente
// después de una navegación -- por eso initLightbox() NO se vuelve a llamar
// en reinitAfterNavigation(): tanto el overlay como el listener de clic ya
// existen y siguen funcionando sin re-inicialización.
function initLightbox() {
    if (document.getElementById("lightbox-overlay")) return;

    const overlay = document.createElement("div");
    overlay.id = "lightbox-overlay";
    overlay.className = "lightbox-overlay";
    overlay.innerHTML =
        '<button type="button" class="lightbox-close" aria-label="Cerrar imagen ampliada">' +
        '<i data-lucide="x" class="icon" style="--icon-size:22px;"></i></button>' +
        '<img alt="">';
    document.body.appendChild(overlay);
    window.refreshIcons();

    const img = overlay.querySelector("img");

    function openLightbox(trigger) {
        img.src = trigger.currentSrc || trigger.src;
        img.alt = trigger.alt || "";
        overlay.classList.add("is-open");
        document.documentElement.classList.add("lightbox-no-scroll");
    }
    function closeLightbox() {
        overlay.classList.remove("is-open");
        document.documentElement.classList.remove("lightbox-no-scroll");
    }

    // Un solo listener cubre los 2 métodos de cierre por clic: el botón X
    // (delegado por su clase) y el fondo oscuro fuera de la imagen -- un
    // clic en la imagen misma tiene event.target === <img>, distinto del
    // propio overlay, así que NO cierra (el clic en la imagen no hace nada,
    // a propósito).
    document.addEventListener("click", (event) => {
        const trigger = event.target.closest("img.lightbox-img");
        if (trigger) {
            openLightbox(trigger);
            return;
        }
        if (event.target === overlay || event.target.closest(".lightbox-close")) {
            closeLightbox();
        }
    });

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && overlay.classList.contains("is-open")) closeLightbox();
    });
}

// Capa visual: observa la selección existente sin modificar clases, enlaces,
// eventos de negocio ni estructura HTML. Los efectos viven en pseudoelementos
// (ver sección 19 de main.css). Portado desde el proyecto de prueba de
// diseño/interacción, tal cual -- opera únicamente sobre .sidebar y
// .tabs-nav .tab-btn, que ya existían.
//
// Separado en dos funciones (antes era una sola, initLiquidSidebar())
// por la navegación sin recarga (ver navigateTo() más abajo): <aside
// class="sidebar"> NUNCA se reemplaza (solo su contenido dinámico,
// #sidebar-dynamic, ver docs/architecture.md) -- así que el listener de
// "pointermove" del brillo debe agregarse UNA sola vez en toda la vida
// de la página (initSidebarGlare(), con guarda propia) para no
// duplicarse en cada navegación, mientras que el efecto de "pill"
// deslizante de cada .tabs-nav SÍ debe volver a engancharse después de
// cada navegación, porque esos nodos (dentro de #sidebar-dynamic) se
// destruyen y se recrean enteros en cada intercambio de contenido.
// Compartido por initSidebarGlare() e initTabsNavPills() -- antes vivía
// declarado adentro de la función única de la que ambas salieron.
const _finePointer = window.matchMedia('(hover: hover) and (pointer: fine)');

function initSidebarGlare() {
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar || sidebar.dataset.glareInit === 'true') return;
    sidebar.dataset.glareInit = 'true';
    let glareFrame = 0;
    let pointerX = 0;
    let pointerY = 0;
    sidebar.addEventListener('pointermove', (event) => {
        if (!_finePointer.matches || prefersReducedMotion() || document.documentElement.classList.contains('theme-transition')) return;
        pointerX = event.clientX;
        pointerY = event.clientY;
        if (glareFrame) return;
        glareFrame = requestAnimationFrame(() => {
            if (document.documentElement.classList.contains('theme-transition')) {
                glareFrame = 0;
                return;
            }
            const rect = sidebar.getBoundingClientRect();
            sidebar.style.setProperty('--glare-x', `${pointerX - rect.left}px`);
            sidebar.style.setProperty('--glare-y', `${pointerY - rect.top + sidebar.scrollTop}px`);
            glareFrame = 0;
        });
    }, { passive: true });
}

function initTabsNavPills() {
    const sidebar = document.querySelector('.sidebar');
    if (!sidebar) return;
    sidebar.querySelectorAll('.tabs-nav').forEach((nav) => {
        const buttons = [...nav.querySelectorAll('.tab-btn')];
        if (!buttons.length) return;
        let visualTarget = null;
        function movePill(button, smooth = true) {
            visualTarget = button;
            nav.style.setProperty('--pill-duration', smooth ? '.5s' : '0s');
            if (!button) {
                nav.style.setProperty('--pill-opacity', '0');
                return;
            }
            nav.style.setProperty('--pill-x', `${button.offsetLeft}px`);
            nav.style.setProperty('--pill-y', `${button.offsetTop}px`);
            nav.style.setProperty('--pill-width', `${button.offsetWidth}px`);
            nav.style.setProperty('--pill-height', `${button.offsetHeight}px`);
            nav.style.setProperty('--pill-opacity', '1');
            nav.style.setProperty('--nav-active-background', 'transparent');
            nav.style.setProperty('--nav-active-shadow', 'none');
        }
        function restoreSelection() {
            movePill(nav.querySelector('.tab-btn:focus-visible') || nav.querySelector('.tab-btn.active'));
        }
        buttons.forEach((button) => {
            button.addEventListener('pointerenter', () => {
                if (_finePointer.matches) movePill(button);
            });
            button.addEventListener('focus', () => movePill(button));
        });
        nav.addEventListener('pointerleave', restoreSelection);
        nav.addEventListener('focusout', () => requestAnimationFrame(restoreSelection));
        const selectionObserver = new MutationObserver(restoreSelection);
        buttons.forEach((button) => selectionObserver.observe(button, { attributes: true, attributeFilter: ['class'] }));
        if (window.ResizeObserver) {
            const resizeObserver = new ResizeObserver(() => movePill(visualTarget || nav.querySelector('.tab-btn.active'), false));
            resizeObserver.observe(nav);
            buttons.forEach((button) => resizeObserver.observe(button));
        } else {
            window.addEventListener('resize', () => movePill(visualTarget, false), { passive: true });
        }
        movePill(nav.querySelector('.tab-btn.active'), false);
    });
}

// =============================================================================
// Navegación sin recarga completa (pjax), ver docs/architecture.md.
//
// El backend (dashboard/app.py:inject_partial_base(), + cada template
// de página con {% extends partial_base %}) responde a peticiones con
// el header X-Requested-With: fetch-nav con un fragmento HTML (NO un
// documento completo) que trae 3 cosas delimitadas por id: un <title>,
// #pjax-main (lo que va dentro de <main class="main-content">) y
// #pjax-sidebar (la zona dinámica de la barra lateral, ver
// #sidebar-dynamic en layout.html). navigateTo() pide ese fragmento,
// lo parsea con DOMParser, y reemplaza esos 2 contenedores + el título
// -- la barra lateral NUNCA se destruye entera, así que el tema
// claro/oscuro ya aplicado, el brillo líquido, y el interruptor mismo
// no se interrumpen visualmente.
// =============================================================================

window.navigateTo = function navigateTo(url, pushState = true) {
    // A propósito NO se cancela ningún sondeo de job en curso acá --
    // ver static/js/job-bell.js: el sondeo de vista previa/procesamiento
    // ahora vive a nivel global (campana de notificaciones), justamente
    // para SOBREVIVIR a la navegación en vez de tener que cortarse cada
    // vez que el usuario cambia de página (antes era necesario porque el
    // overlay de pantalla completa y su callback onDone() vivían atados
    // a la página del asistente de configuración).
    let finalUrl = url;
    return fetch(url, { headers: { "X-Requested-With": "fetch-nav" } })
        .then((resp) => {
            if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
            // fetch() sigue redirecciones del servidor por defecto (ej.
            // una cámara sin resultados que redirige de /store/results a
            // /setup) -- resp.url es la URL FINAL ya resuelta; usar el
            // "url" original para pushState dejaría la barra de
            // direcciones mostrando una URL que en realidad no es la que
            // se está viendo.
            finalUrl = resp.url || url;
            return resp.text();
        })
        .then((html) => {
            const doc = new DOMParser().parseFromString(html, "text/html");
            const newMain = doc.getElementById("pjax-main");
            const newSidebar = doc.getElementById("pjax-sidebar");
            const mainEl = document.querySelector(".main-content");
            const sidebarDynamicEl = document.getElementById("sidebar-dynamic");
            if (!newMain || !newSidebar || !mainEl || !sidebarDynamicEl) {
                // Respuesta inesperada (ej. una redirección a login que
                // no existe hoy, o un error de servidor devuelto como
                // HTML completo) -- no dejar la página a medio actualizar.
                throw new Error("Respuesta de navegación parcial incompleta");
            }

            document.title = doc.title;
            mainEl.innerHTML = newMain.innerHTML;
            sidebarDynamicEl.innerHTML = newSidebar.innerHTML;

            if (pushState) history.pushState({}, "", finalUrl);
            window.scrollTo(0, 0);

            reinitAfterNavigation();
        })
        .catch(() => {
            // Cualquier falla real (red caída, respuesta inesperada) --
            // navegación tradicional de respaldo en vez de dejar el
            // clic del usuario sin ningún efecto. finalUrl ya refleja
            // cualquier redirección que sí se haya resuelto.
            window.location.href = finalUrl;
        });
};

// Vuelve a correr, sobre el contenido NUEVO recién insertado, todo lo
// que antes solo corría una vez en DOMContentLoaded -- ver Parte 3 de
// la tarea de navegación sin recarga. Cada init de página se protege
// sola (ancla propia, ej. "if (!document.getElementById(...)) return;"
// -- confirmado leyendo cada script, no asumido), así que llamarlas
// todas sin importar qué página cargó es seguro: la que no aplica no
// hace nada. NO se re-ejecuta initThemeToggle() ni initSidebarGlare()
// acá -- ambas viven sobre elementos que NUNCA se reemplazan (el
// interruptor de tema y el propio <aside class="sidebar">), volver a
// llamarlas duplicaría sus listeners.
//
// initJobBell() SÍ hace falta re-correrlo acá: la campana vive dentro
// de .page-hero (ver job-bell.js), que a diferencia de la barra lateral
// se reemplaza por completo en cada navegación -- sin este re-init el
// botón quedaría sin sus listeners (campana "muerta") después de
// navegar una sola vez.
function reinitAfterNavigation() {
    window.refreshIcons();
    initKpiCountUp();
    initExpanders();
    initTabsNavPills();
    if (window.initJobBell) window.initJobBell();

    if (window.initResultsPage) window.initResultsPage();
    if (window.initSetupPage) window.initSetupPage();
    if (window.initCalibrationPage) window.initCalibrationPage();
    if (window.initDataManagementPage) window.initDataManagementPage();
    if (window.initTiendaCombinadaPage) window.initTiendaCombinadaPage();
    if (window.initSettingsPage) window.initSettingsPage();
}

// El selector de tienda navegaba con una recarga completa vía
// onchange="this.form.submit()" (inline en el HTML -- layout.html y
// layout_fragment.html, ver el comentario de duplicación deliberada
// ahí) -- inline a propósito, no re-enganchado con addEventListener,
// porque el propio <select> vive dentro de #sidebar-dynamic y se
// destruye/recrea en cada navegación.
window.handleTiendaSelectChange = function handleTiendaSelectChange(selectEl) {
    const url = `${selectEl.form.action}?${encodeURIComponent(selectEl.name)}=${encodeURIComponent(selectEl.value)}`;
    window.navigateTo(url);
};

// Solo intercepta <a href> reales dentro de la barra lateral (lista de
// cámaras, Vista combinada, Agregar cámara, sub-nav de la página), el
// breadcrumb del encabezado ("demo / cámara"), o la barra de pestañas
// horizontal de secciones (.section-tabs, ver results.html -- el único
// enlace real ahí es "Datos", el resto son botones data-tab sin href
// que ni siquiera llegan a este chequeo) -- exactamente lo que pide la
// tarea, no "cualquier link de la página" (ej. las tarjetas de tienda
// en welcome.html, o el link a Tendencias desde Datos, siguen
// navegando normal a propósito: no eran parte del pedido y ampliar el
// alcance sin que se pidiera es más riesgo que beneficio acá).
// Respeta target="_blank", descargas, y clic con modificador (nueva
// pestaña) -- en esos casos NO se llama preventDefault(), el navegador
// hace lo de siempre.
function isInternalNavigableLink(link) {
    if (!link || !link.getAttribute("href")) return false;
    if (link.target && link.target !== "_self") return false;
    if (link.hasAttribute("download")) return false;
    let url;
    try {
        url = new URL(link.href, window.location.href);
    } catch (e) {
        return false;
    }
    if (url.origin !== window.location.origin) return false;
    if (url.protocol !== "http:" && url.protocol !== "https:") return false;
    return true;
}

document.addEventListener("click", (event) => {
    if (event.defaultPrevented || event.button !== 0) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;

    const link = event.target.closest("a[href]");
    if (!link) return;
    if (!link.closest(".sidebar") && !link.closest(".page-hero") && !link.closest(".section-tabs")) return;
    if (!isInternalNavigableLink(link)) return;

    event.preventDefault();
    window.navigateTo(link.href);
});

// Atrás/adelante del navegador: no hay nada que "restaurar" desde
// history.state -- siempre se vuelve a pedir el fragmento fresco de la
// URL a la que el navegador ya saltó (location.href ya está actualizado
// para cuando este evento dispara), así que el contenido mostrado
// siempre coincide con la URL real, sin necesidad de cachear HTML viejo.
window.addEventListener("popstate", () => {
    window.navigateTo(location.href, false);
});
