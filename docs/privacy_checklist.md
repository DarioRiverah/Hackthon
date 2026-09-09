# Checklist de privacidad por diseño

Este documento formaliza cómo el proyecto cumple con el principio de
"privacidad por diseño" exigido por el reto, y su relación con la Ley
1581 de 2012 (Colombia) sobre protección de datos personales.

## Principio central

> El dato biométrico queda excluido por diseño, no por política.

Es decir: la arquitectura del sistema hace que sea *técnicamente
imposible* generar o almacenar datos biométricos, en vez de depender de
una regla que alguien podría desactivar u olvidar.

## Checklist

- [x] **No se extraen embeddings faciales ni landmarks faciales.**
      Solo se usan bounding boxes de cuerpo completo (para tracking) y
      posición de muñeca (para interacción) — ninguno de los dos
      permite identificar a una persona específica.

- [x] **No se realiza reconocimiento facial en ningún punto del
      pipeline.** Los modelos usados (YOLO26, YOLOv8-pose) detectan
      "persona" y "keypoints de pose" genéricos, no identidad.

- [x] **No se infieren emociones ni estado de ánimo.** El sistema mide
      comportamiento espacial observable (tráfico, permanencia,
      interacción física), nunca estado emocional.

- [x] **Los identificadores de persona son efímeros.** El `track_id` y
      el `id_persona` que genera el sistema solo existen durante el
      procesamiento de un video específico. No hay ningún mecanismo de
      re-identificación entre videos distintos, ni entre sesiones.

- [x] **No se almacena ningún frame ni recorte de imagen de una
      persona.** Los únicos archivos que persisten después de procesar
      un video son: coordenadas numéricas agregadas (CSV), y un mapa de
      calor generado a partir de esas coordenadas (una imagen del
      *espacio físico*, no de personas). El video original permanece
      en `data/raw/` únicamente como conveniencia local del usuario —
      el pipeline no depende de conservarlo, y puede borrarse después
      de procesar sin afectar ningún resultado ya generado.

- [x] **Procesamiento 100% local (edge).** El video nunca se transmite
      a ningún servidor externo ni servicio en la nube. Todo el
      cómputo ocurre en la máquina del usuario.

- [x] **Configuración por tienda, sin datos cruzados entre tiendas.**
      Cada tienda tiene su propio archivo de configuración y sus
      propios resultados, identificados por nombre de tienda — no hay
      ninguna base de datos compartida ni comparación automática entre
      clientes de distintas tiendas.

## Sobre el uso de video con personas reales (ej. grabaciones de un
comercio con consentimiento)

- Se recomienda que el establecimiento cuente con aviso visible de
  videovigilancia (circuito cerrado de televisión), como ya es práctica
  común en la mayoría de comercios.
- El consentimiento del dueño del establecimiento para el
  procesamiento con este sistema debe obtenerse por separado del aviso
  de videovigilancia general, dado que se trata de un tratamiento
  adicional (análisis automatizado) sobre la grabación.
- Se recomienda procesar el video y descartarlo lo antes posible una
  vez extraídas las métricas agregadas, minimizando el tiempo que el
  video crudo permanece almacenado.

## Alcance honesto: lo que este documento NO garantiza

Este documento describe el diseño técnico del sistema tal como fue
construido para este MVP. No constituye asesoría legal. Cualquier
despliegue en un comercio real debería validarse con asesoría legal
específica sobre protección de datos aplicable a la jurisdicción
correspondiente.