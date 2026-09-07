# Base de Conocimiento Técnica

## Objetivo

Este documento resume cómo está construido `MoneyPrinterTurbo`, qué partes ya aportan valor, dónde están las limitaciones actuales y qué cambios conviene priorizar para volver el proyecto más potente, mantenible y operable.

## Resumen Ejecutivo

`MoneyPrinterTurbo` ya tiene una base funcional sólida:

- Genera video desde tema, guion o PDF.
- Soporta varios proveedores LLM y TTS.
- Expone API con FastAPI y una UI con Streamlit.
- Tiene capa de servicios separada y algunos tests de regresión.

El principal problema no es de idea ni de producto, sino de forma:

- demasiada lógica está concentrada en pocos archivos grandes;
- hay estado global mutable repartido por todo el sistema;
- la operación depende mucho del entorno local;
- la validación automática todavía no es reproducible;
- faltan límites claros entre dominio, infraestructura y presentación.

Conclusión: el proyecto es aprovechable y ampliable, pero antes de añadir más features conviene endurecer arquitectura, empaquetado, tests y observabilidad.

## Qué Hace Hoy el Sistema

### Interfaces

- `FastAPI` sirve la API y los archivos de tareas generadas.
- `Streamlit` actúa como interfaz principal de configuración y ejecución.

### Flujo principal

1. El usuario envía tema, guion, PDF o materiales.
2. Se genera o normaliza el guion.
3. Se generan términos de búsqueda.
4. Se produce audio TTS o se usa audio propio.
5. Se generan subtítulos.
6. Se descargan o preparan materiales visuales.
7. Se compone el video final.
8. Se guarda en `storage/tasks`.

### Módulos principales

- `app/controllers/`: endpoints HTTP y subida/descarga de archivos.
- `app/services/`: lógica de negocio y orquestación.
- `app/models/`: schemas y enums.
- `app/config/`: carga de configuración global.
- `webui/`: interfaz Streamlit.
- `test/services/`: pruebas unitarias y de regresión.

## Mapa de Arquitectura Actual

### Backend

- Entrada ASGI: `app/asgi.py`
- Router raíz: `app/router.py`
- Endpoints de video/audio/subtítulos: `app/controllers/v1/video.py`
- Estado de tareas: `app/services/state.py`
- Orquestación principal: `app/services/task.py`
- Composición de video: `app/services/video.py`
- Materiales remotos/locales: `app/services/material.py`
- LLM: `app/services/llm.py`
- Voz/TTS: `app/services/voice.py`

### UI

- `webui/Main.py` contiene gran parte de la UI, configuración dinámica y flujo de generación.

### Infraestructura

- `Dockerfile`
- `docker-compose.yml`
- `config.example.toml`

## Fortalezas Reales del Proyecto

- El producto ya resuelve un caso de uso claro y demostrable.
- La separación por servicios existe y permite refactorizar sin reescribir todo.
- Se han introducido mejoras recientes de seguridad en uploads y paths.
- El soporte multi-provider de LLM/TTS abre margen comercial y técnico.
- La base de tests ya cubre algunos regresiones valiosas.
- El proyecto conserva modo local, Docker y API, lo que facilita distintos modelos de uso.

## Hallazgos Técnicos Clave

### 1. Configuración global mutable

La configuración se carga al importar y luego se muta en caliente desde varios puntos.

Referencias:

- `app/config/config.py:44-81`
- `webui/Main.py:65-79`
- `webui/Main.py:105-108`
- `webui/Main.py:223-243`

Impacto:

- dificulta tests aislados;
- mezcla configuración persistente con estado de sesión;
- complica correr múltiples workers o procesos con comportamiento consistente.

### 2. Módulos demasiado grandes y con demasiadas responsabilidades

Archivos especialmente cargados:

- `webui/Main.py` ~1284 líneas
- `app/services/voice.py` ~2188 líneas
- `app/services/video.py` ~706 líneas
- `app/services/llm.py` ~587 líneas
- `app/services/task.py` ~521 líneas

Impacto:

- alto costo de cambio;
- mayor probabilidad de regresiones;
- onboarding más lento;
- baja reutilización interna.

### 3. Orquestación del pipeline muy acoplada

`app/services/task.py` mezcla:

- normalización de entrada;
- resolución de PDF;
- generación LLM;
- TTS;
- subtítulos;
- descarga de materiales;
- fallback visual;
- persistencia de artefactos.

Referencias:

- `app/services/task.py:21-54`
- `app/services/task.py:57-79`
- `app/services/task.py:109-197`
- `app/services/task.py:200-255`

Impacto:

- no hay pasos claramente desacoplados;
- es difícil reintentar solo una fase;
- casi no hay contratos de pipeline explícitos.

### 4. Estado de tareas débil para cargas reales

El estado se guarda en memoria o en Redis, pero sin modelo de eventos, TTL, locking robusto ni recuperación clara.

Referencias:

- `app/services/state.py:24-58`
- `app/services/state.py:61-158`
- `app/controllers/v1/video.py:39-53`

Impacto:

- comportamiento frágil en reinicios;
- escalado horizontal limitado;
- poca trazabilidad para tareas largas o fallidas.

### 5. Lógica de proveedores LLM concentrada en un bloque condicional grande

`app/services/llm.py` usa un árbol `if/elif` muy largo para todos los proveedores.

Referencias:

- `app/services/llm.py:55-257`

Impacto:

- añadir nuevos proveedores cuesta demasiado;
- cada cambio puede romper proveedores no relacionados;
- difícil testear por adaptador.

### 6. UI de Streamlit demasiado acoplada al dominio

`webui/Main.py` no solo renderiza UI, también:

- manipula config global;
- valida contenido;
- administra sesión;
- llama servicios de negocio directamente.

Referencias:

- `webui/Main.py:57-79`
- `webui/Main.py:123-220`
- `webui/Main.py:223+`

Impacto:

- la UI es difícil de dividir o modernizar;
- la lógica no se puede reutilizar fácilmente desde API o CLI;
- limita migraciones futuras a frontend web más serio.

### 7. Operación y empaquetado inconsistentes

Hallazgos:

- `docker-compose.yml` usa `python3 main.py`, pero el README también habla de `python`.
- en este entorno `python` no existe, sí `python3`.
- el `Dockerfile` instala desde `requirements.txt`, mientras la fuente principal declarada es `pyproject.toml`.
- no hay workflows CI en `.github/workflows`.

Referencias:

- `docker-compose.yml`
- `Dockerfile`
- `pyproject.toml`
- `requirements.txt`
- `.github/` sin pipelines

Impacto:

- difícil reproducir builds;
- riesgo de deriva entre entornos;
- tests no se ejecutan automáticamente en PRs.

### 8. Validación automática no lista para confiarse

Resultado de ejecución local:

- `python3 -m unittest discover -s test` falla.
- Las fallas principales son dependencias ausentes del entorno: `toml`, `moviepy`, `edge_tts`, `pypdf`.

Conclusión:

- los tests existen, pero el flujo de verificación no está empaquetado ni blindado;
- la suite no es plug-and-play para colaboradores o CI.

### 9. Seguridad mejoró, pero sigue incompleta

Aspectos positivos:

- sanitización de nombres de archivo.
- protección contra path traversal al resolver archivos.
- TLS activado por defecto para descargas de materiales.
- `g4f` ahora exige activación explícita.

Referencias:

- `app/controllers/v1/video.py:56-98`
- `app/services/material.py:22-36`
- `app/services/llm.py:60-81`

Huecos pendientes:

- sin auth real en API por defecto;
- sin rate limiting;
- sin cuotas por usuario;
- sin separación formal entre rutas públicas y administrativas;
- sin política clara de retención/limpieza de artefactos.

### 10. Observabilidad básica, no operativa

Hay logging, pero falta observabilidad real:

- no hay métricas;
- no hay tracing por tarea de punta a punta;
- no hay clasificación de errores por etapa;
- no hay panel de salud ni tiempos por pipeline.

## Riesgos Prioritarios

### Riesgo Alto

- roturas por cambios laterales en archivos gigantes;
- generación inconsistente según entorno local;
- imposibilidad de escalar tareas de forma segura;
- bugs difíciles de reproducir por configuración global mutable.

### Riesgo Medio

- alto costo al añadir nuevos proveedores;
- crecimiento desordenado del WebUI;
- acumulación de basura en `storage/`.

### Riesgo Bajo pero importante

- deuda documental;
- naming mixto y comentarios bilingües sin convención;
- ausencia de métricas de calidad visual o performance.

## Cómo Hacerlo Más Potente

### Fase 1. Endurecimiento base

Prioridad máxima.

1. Unificar instalación y ejecución.
2. Declarar un único flujo oficial: `uv sync --frozen` y un runner documentado.
3. Añadir CI mínima:
   - instalación;
   - lint;
   - tests unitarios;
   - smoke test de importación.
4. Extraer configuración a un objeto tipado y evitar mutaciones globales directas.
5. Separar dependencias opcionales por extras:
   - `tts`
   - `video`
   - `llm`
   - `dev`

### Fase 2. Refactor por arquitectura

1. Dividir `task.py` en pipeline explícito:
   - `script_stage`
   - `terms_stage`
   - `audio_stage`
   - `subtitle_stage`
   - `materials_stage`
   - `render_stage`
2. Convertir `llm.py` en adapters por proveedor:
   - `providers/openai.py`
   - `providers/gemini.py`
   - `providers/litellm.py`
3. Dividir `voice.py` por backends TTS.
4. Convertir `webui/Main.py` en módulos:
   - layout
   - forms
   - session state
   - actions

### Fase 3. Potencia de producto

1. Cola de trabajos robusta:
   - Redis Queue, Celery, Dramatiq o Arq.
2. Reintentos por etapa con estados explícitos.
3. Cache inteligente de:
   - términos;
   - guiones;
   - materiales;
   - audio;
   - subtítulos.
4. Plantillas de estilo de video:
   - shorts motivacionales;
   - noticias;
   - storytelling;
   - faceless educational;
   - audiolibro visual.
5. Presets exportables/importables por usuario.

### Fase 4. Escalabilidad y comercialización

1. Autenticación y multiusuario.
2. Persistencia de tareas en DB.
3. Dashboard operativo con métricas.
4. API versionada y estable.
5. Workers separados para:
   - LLM;
   - TTS;
   - render;
   - post-procesado.

## Propuesta de Arquitectura Objetivo

### Capas

- `presentation`
  - FastAPI
  - Streamlit o futuro frontend web
- `application`
  - casos de uso
  - orquestación de pipeline
- `domain`
  - entidades de tarea, asset, voice profile, render job
- `infrastructure`
  - OpenAI/Gemini/LiteLLM
  - TTS providers
  - Pexels/Pixabay
  - ffmpeg/moviepy
  - Redis/DB/storage

### Beneficio

Este cambio permitiría:

- sustituir proveedores sin tocar el pipeline;
- probar lógica sin requerir red ni ffmpeg real;
- exponer CLI/API/Web sin duplicar reglas de negocio.

## Backlog Recomendado

### Quick wins

- añadir `Makefile` o scripts `uv run` para comandos estándar;
- crear `requirements-dev` o extras `dev`;
- agregar `pytest` o mantener `unittest` pero con setup reproducible;
- crear workflow CI básico;
- documentar dependencias del sistema: ffmpeg, imagemagick, fonts.

### Mejoras de alto retorno

- factorizar proveedores LLM;
- factorizar TTS;
- crear `TaskPipelineResult` tipado;
- persistir metadatos de cada tarea en JSON estructurado o DB;
- introducir limpieza automática de temporales.

### Mejoras de producto

- preview de estilos visuales;
- ranking automático de clips;
- biblioteca de presets;
- soporte de batch jobs con colas y prioridades;
- exportación de proyecto editable.

## Métricas que Conviene Empezar a Medir

- tiempo por etapa;
- tasa de fallo por proveedor;
- duración media de render;
- reutilización de caché;
- porcentaje de tareas completadas;
- coste estimado por video;
- tamaño medio de artefactos generados.

## Orden Recomendado de Ejecución

1. CI + instalación reproducible.
2. Configuración tipada y no global.
3. Refactor `llm.py` y `voice.py` por adaptadores.
4. Refactor pipeline de `task.py`.
5. Separación progresiva de `webui/Main.py`.
6. Cola de tareas robusta.
7. Persistencia y observabilidad.

## Decisión Estratégica

Si el objetivo es solo “seguir agregando opciones”, el proyecto crecerá más rápido pero se volverá más frágil.

Si el objetivo es “hacerlo más potente”, la secuencia correcta es:

- primero estabilidad operativa;
- luego arquitectura extensible;
- después nuevas capacidades de producto.

Esa secuencia reduce regresiones y hace viable escalar el sistema sin que cada mejora rompa otra parte.
