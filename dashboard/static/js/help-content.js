// Contenido del widget de ayuda flotante (botón "?" en la esquina).
// 100% estático -- sin llamadas al servidor ni a ningún modelo de
// lenguaje. Para agregar o editar una pregunta frecuente, solo hace
// falta tocar este archivo: static/js/help-widget.js no sabe nada del
// contenido en sí, solo sabe cómo dibujar la lista y las respuestas.
//
// Formato de cada pregunta:
//   id: identificador único (string)
//   question: texto del botón en la lista de preguntas
//   blocks: arreglo de bloques de la respuesta, en orden. Cada bloque es
//     { type: "p", text: "..." }              -- un párrafo
//     { type: "ol", items: ["...", "..."] }    -- lista de pasos numerados
//     { type: "ul", items: ["...", "..."] }    -- lista sin numerar
window.HELP_CONTENT = {
    greeting: "Hola. Esta es la ayuda de la interfaz -- elige una pregunta para ver los pasos.",
    questions: [
        {
            id: "subir-video",
            question: "¿Cómo subo un video nuevo?",
            blocks: [
                { type: "p", text: "Se hace desde el asistente de configuración de la cámara correspondiente." },
                {
                    type: "ol", items: [
                        "Ve a la tienda y a la cámara donde quieres subir el video (elígela en el menú lateral).",
                        "Abre “Agregar nueva grabación / recalibrar”, arriba de la página de resultados, para entrar al asistente.",
                        "En el paso “1. Sube tu video”, elige el archivo (.mp4, .avi o .mov) y presiona “Subir video”.",
                        "Espera a que termine de cargar -- el video se va a reproducir en la página cuando esté listo."
                    ]
                },
                { type: "p", text: "Desde ahí puedes seguir con el recorte opcional, la calibración de góndolas y el procesamiento." }
            ]
        },
        {
            id: "calibracion",
            question: "¿Cómo marco mis góndolas (calibración)?",
            blocks: [
                { type: "p", text: "La calibración define las zonas que el sistema va a medir, dibujando un polígono sobre la imagen del video." },
                {
                    type: "ol", items: [
                        "En el paso “3. Marca tus góndolas”, haz clic sobre la imagen para ir marcando las esquinas de la zona (mínimo 3 puntos).",
                        "Cubre tanto el piso donde se para el cliente como el estante de productos: así el sistema puede medir la permanencia (cuánto tiempo se queda alguien ahí) y la interacción (cuándo toca el producto) en la misma zona.",
                        "Si generaste la vista previa de calor, úsala como guía antes de dibujar -- muestra dónde se mueve y se detiene la gente realmente.",
                        "Cuando termines esa zona, presiona “Cerrar zona actual” y ponle un nombre. Repite para cada góndola.",
                        "Cuando termines todas las zonas, guárdalas."
                    ]
                }
            ]
        },
        {
            id: "nueva-camara",
            question: "¿Cómo agrego una cámara nueva a mi tienda?",
            blocks: [
                {
                    type: "ol", items: [
                        "Desde la vista de la tienda, presiona “+ Agregar cámara” en el menú lateral.",
                        "Ponle un identificador a la cámara (sin espacios) y presiona “Continuar al asistente”.",
                        "Sigue el mismo asistente de siempre: subir video, calibrar y procesar. Al terminar, la cámara queda registrada bajo tu tienda automáticamente."
                    ]
                },
                { type: "p", text: "También puedes vincular una cámara que ya tiene datos en el sistema pero todavía no pertenece a ninguna tienda, desde esa misma pantalla." }
            ]
        },
        {
            id: "colores-zonas",
            question: "¿Qué significan los colores de las zonas (semáforo)?",
            blocks: [
                { type: "p", text: "El resumen por zona clasifica cada una en una de estas cuatro categorías, según su tráfico y si la gente se detiene:" },
                {
                    type: "ul", items: [
                        "Zona Caliente (alto tráfico + se detienen)",
                        "Zona de Paso (alto tráfico, no se detienen)",
                        "Interés de Nicho (poco tráfico, sí se detienen)",
                        "Zona Fría (poco tráfico)"
                    ]
                }
            ]
        },
        {
            id: "comparar-fechas",
            question: "¿Cómo comparo resultados de distintas fechas?",
            blocks: [
                {
                    type: "ol", items: [
                        "Al procesar un video, deja marcada la opción “Guardar este resultado en el historial de tendencias” (ya viene activada por defecto).",
                        "Ve a la pestaña “Tendencias” de la cámara.",
                        "Elige dos fechas para ver una comparación detallada, o agrupa la evolución en el tiempo por día, semana o mes."
                    ]
                },
                { type: "p", text: "Se necesitan al menos 2 fechas guardadas en el historial para poder comparar." }
            ]
        },
        {
            id: "simulador",
            question: "¿Cómo uso el Simulador?",
            blocks: [
                { type: "p", text: "El Simulador estima qué pasaría con la interacción de un producto si lo movieras de una zona a otra, basándose en el tráfico ya observado de ambas." },
                {
                    type: "ol", items: [
                        "Necesitas al menos 2 zonas calibradas -- pueden estar en la misma cámara o en cámaras distintas de la misma tienda.",
                        "En la pestaña “Simulador”, elige la zona de origen (donde está el producto ahora) y la zona destino (a donde lo moverías).",
                        "Presiona “Simular” y revisa el resultado."
                    ]
                },
                { type: "p", text: "Es una extrapolación sobre datos reales, no una predicción garantizada." }
            ]
        },
        {
            id: "borrar-datos",
            question: "¿Cómo borro un video o resultados que ya no necesito?",
            blocks: [
                {
                    type: "ol", items: [
                        "Ve a la pestaña “Datos” de la cámara correspondiente (ícono de base de datos en el menú lateral).",
                        "Elige qué quieres eliminar: el video crudo, los resultados actuales, una fecha archivada puntual, o la cámara completa.",
                        "Confirma la acción cuando el sistema te lo pida."
                    ]
                },
                { type: "p", text: "Importante: ninguna de estas acciones se puede deshacer." }
            ]
        },
        {
            id: "privacidad",
            question: "¿El sistema identifica a mis clientes?",
            blocks: [
                { type: "p", text: "No. El sistema está diseñado, a propósito, para no identificar personas:" },
                {
                    type: "ul", items: [
                        "No usa reconocimiento facial.",
                        "No guarda imágenes de las personas que aparecen en el video.",
                        "Ni siquiera distingue de forma confiable a un cliente específico de otro cuando hay varias personas en la misma escena."
                    ]
                },
                { type: "p", text: "Por eso las métricas se muestran siempre agregadas (por zona, por fecha), nunca por “cliente individual”." }
            ]
        }
    ]
};
