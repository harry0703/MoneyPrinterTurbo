# BYNEX AI Personal Studio — Informe de auditoría inicial

Fecha: 2026-11-25 · Repositorio: MoneyPrinterTurbo v1.3.10 + Cartoon Studio 2D
(`feature/2d-cartoon-studio`) · Equipo auditado: AMD Ryzen 5 5500U, 12 GB RAM,
sin GPU dedicada, Windows 11.

Este documento es el **entregable del Sprint 1**. Todo lo marcado como *verificado*
se ejecutó en este equipo; lo no verificado se indica explícitamente.

---

## 1. Entorno real encontrado

| Elemento | Estado verificado | Evidencia |
|---|---|---|
| Python de la app | 3.13.1 (`python`), 3.11.0 en `.venv` | `python -c "import sys"` |
| Entorno de la app | `.venv` (3.11.0): streamlit 1.66.1, moviepy 2.2.1, numpy 2.4.4, Pillow 11.3, pydub, faster-whisper, ctranslate2 | `pip list` |
| FFmpeg | 9.0.2-full_build (gyan.dev) y `ffprobe` en PATH | `ffmpeg -version` |
| OpenVoice | **Vendido en `local-voice/OpenVoice`**, editable en `local-voice/.venv` | `import openvoice` → OK |
| MeloTTS | **Vendido en `local-voice/MeloTTS`**, editable en el mismo venv | `import melo` → OK |
| PyTorch | 2.15.0+cpu **solo** en `local-voice/.venv` | `torch.__version__` |
| Checkpoints OpenVoice V2 | `checkpoints_v2/converter` + `base_speakers/ses/es.pth` presentes | listado de directorios |
| OpenCV (`cv2`) | **Ausente** en la app y en el venv de voz | import falla |
| `psutil` | Ausente | import falla |
| `insightface`, `mediapipe`, `onnxruntime` | `onnxruntime` 1.24.4 presente en la app; InsightFace/MediaPipe ausentes | import |
| Grabaciones existentes | `local-voice/references/mi_voz.wav`, `mi_voz_pcm.wav`, `Voz segunda prueba.m4a` | atime + listado |

### Hallazgo clave de arquitectura

`OpenVoice` y `MeloTTS` **no son importables desde el entorno de la aplicación**:
dependen de PyTorch CPU, `librosa`, `soundfile` y versiones antiguas de numpy
(1.23.5), que chocan con el numpy 2.x del proyecto. Instalarlos en `.venv`
provocaría exactamente el conflicto de dependencias que el encargo pide evitar.

**Decisión:** el motor de voz se ejecuta como **proceso hijo** en
`local-voice/.venv`, invocado por `app/services/personal_studio/voice_worker.py`
y orquestado por `engines.py`. La app nunca importa torch: recibe WAV + JSON por
`stdout`. Esto aísla el conflicto y libera RAM al terminar cada generación.

## 2. Diagnóstico del error de MeCab

El error de MeCab aparece **solo en la ruta japonesa** de MeloTTS
(`melo/text/japanese.py` importa `mecab`). No afecta al español:

- `import melo` → OK
- `TTS(language="ES")` → OK
- Síntesis de prueba: *"Bienvenidos a BYNEX. Hoy hablamos de inteligencia
  artificial y soporte técnico."* → **6.41 s de audio en 6.2 s de síntesis**
  (carga del modelo: 12.5 s).

Por tanto **no se instala MeCab** ni diccionarios japoneses: no son necesarios
para español y añadirían ~200 MB. El código del trabajador fuerza `language="ES"`
y valida los checkpoints antes de cargar el modelo.

## 3. Prueba real de hardware (CPU)

Medición directa con `local-voice/.venv`:

| Medición | Resultado |
|---|---|
| Carga MeloTTS ES | 12.5 s (una vez por proceso) |
| Síntesis de 2 frases (6.4 s de audio) | 6.2 s |
| Relación tiempo real | ≈ 0.97× (no es tiempo real, pero es usable) |
| RAM durante la prueba | < 2 GB (torch CPU + modelo ES) |

Consecuencia de diseño: **una carga de modelos por narración**, no por frase.
El trabajador sintetiza todos los segmentos en un solo proceso y aplica
OpenVoice una sola vez sobre el audio completo; cargar el conversor por frase
multiplicaría el tiempo por el número de frases.

## 4. Funcionalidad existente que **no** se reconstruye

| Componente | Reutilización |
|---|---|
| `app/services/voice.py` | Motor TTS remoto (Edge/Azure/Gemini/etc.) como *fallback* sin clonación y para vista previa rápida |
| `app/services/video.py`, `video_project.py` | Codificación, mezcla de audio, quema de subtítulos ASS, ffmpeg con `cwd` seguro |
| `app/services/cartoon_animation/` | Personaje articulado `tiko`, `render_character`, `encode_frames`, `lip_sync.analyze_audio`, fondos (`garden`, `meadow`, `night`, `studio`) |
| `app/services/cartoon_studio.py` + `webui/cartoon_studio.py` | Sección "Cartoon Studio 2D" intacta en el panel |
| `webui/Main.py` | Navegación por secciones: se añade una tercera sección, no una app nueva |
| `app/services/bgm.py`, `resource/songs` | Música de fondo local |
| `app/services/subtitle.py` | No se usa para este módulo: los subtítulos se generan de los segmentos reales de la narración |

## 5. Matriz de motores de voz (verificada contra fuentes oficiales)

| Motor | Clonación | Español | CPU viable aquí | Licencia comercial | Decisión |
|---|---|---|---|---|---|
| **MeloTTS (base) + OpenVoice V2 (timbre)** | Sí | Sí (`es.pth`) | **Sí, medido** | **MIT** (código y checkpoints V2) | **Motor principal** |
| MeloTTS sola | No | Sí | Sí | MIT | Voz base del pipeline |
| Edge TTS (existente) | No | Sí (`es-CO-*`) | Sí (requiere red) | Servicio de Microsoft | **Respaldo naturalista** |
| Piper | No (zero-shot limitado) | Sí (voces `es_*`) | Sí | Motor **GPL-3.0**, licencia por voz | Adapter presente, solo si el usuario instala binario+voz |
| Coqui XTTS v2 | Sí | Sí | Difícil (lento en CPU) | **Coqui Public Model License: solo no comercial** | **Descartado** por licencia |
| F5-TTS | Sí | No oficial | No práctico | Código MIT, **pesos CC-BY-NC-4.0** | Descartado |
| Chatterbox | Sí | Multilingüe | 0.5B, lento en CPU | MIT, pero **archivado por Resemble (ago-2026)** | Descartado por mantenimiento |

Fuentes: licencia MIT en `local-voice/OpenVoice/LICENSE`, `local-voice/MeloTTS/LICENSE`
y model card de `checkpoints_v2`; `huggingface.co/coqui/XTTS-v2/LICENSE.txt`
(CPML 1.0.0, solo no comercial); repo de F5-TTS (MIT código / CC-BY-NC pesos);
`github.com/resemble-ai/chatterbox` (MIT, retirado); Piper (motor GPL-3.0,
licencia por voz).

**Conclusión:** OpenVoice V2 + MeloTTS es el único par con clonación real,
español y licencia comercial permisiva que además está **ya instalado y medido**
en este equipo. No se instala ningún otro motor.

## 6. Matriz de motores de animación

| Tecnología | Requisito real | Veredicto aquí |
|---|---|---|
| SadTalker | PyTorch + modelos 3DMM (~2 GB), minutos por minuto en CPU | No viable |
| LivePortrait | GPU + InsightFace (licencia de modelos no comercial) | No viable |
| MuseTalk | GPU, requisitos de licencia restrictivos | No viable |
| Wav2Lip | Pesos de investigación no comercial | Descartado |
| Rhubarb Lip Sync | Excelente fonemas, pero no anima imágenes; requiere binario+`es` | No instalado; sustituido por envolvente de amplitud |
| OpenCV | Detección de rostro Haar | **No instalado** → heurística de piel propia + aviso |
| MediaPipe | FaceMesh, wheels CPU | No instalado (no se descarga sin autorización) |
| Pillow + FFmpeg | Ya presentes | **Base de la animación 2.5D** |
| Motor 2D propio (`cartoon_animation`) | Ya presente | **Modo caricatura** |

**Decisión:** animación 2.5D determinista con Pillow (respiración, balanceo,
parpadeo y boca por envolvente de audio) + caricatura 2D con el motor existente.
No se promete fotorrealismo ni sincronización fonética: la sincronización es de
**amplitud**, documentada como tal.

## 7. Licencias y contenido sintético

- OpenVoice y MeloTTS: **MIT**, uso comercial permitido.
- OpenVoice inserta una marca de agua (`message="@BYNEX"`) en el audio convertido.
- YouTube exige declarar contenido sintético que haga parecer que una persona
  real dice algo que no dijo; Meta exige etiqueta "AI info" para vídeo
  fotorrealista o audio realista alterado; TikTok exige etiquetar AIGC realista.
  El módulo genera el texto de divulgación y **bloquea la exportación** si no se
  aprobó el contenido.
- No se usa ni se enviará ninguna foto/voz a servicios externos: el motor de
  clonación es local. Edge TTS (respaldo) sí envía el texto a Microsoft; el panel
  lo advierte antes de usarlo.

## 8. Riesgos y limitaciones conocidas

1. **Sin segmentación de personas**: no se puede recortar el fondo de una foto
   sin `rembg`/`cv2`. Se ofrece fondo desenfocado/degradado, no recorte.
2. **Detección de rostro heurística** si no hay OpenCV: puede encuadrar mal
   fotos con fondos de tono piel. El panel muestra el encuadre y permite ajustar.
3. **Sin control emocional real** en MeloTTS: los "estilos" son ritmo, pausas y
   segmentación de texto, no embeddings. Se declara en la UI.
4. **1080p**: se permite, pero en este equipo un minuto a 1080p tarda varios
   minutos. El perfil se marca como "no verificado en tiempo" hasta medirlo.
5. **Acento colombiano**: lo aporta la muestra del usuario; la voz base es
   española neutra. Si la muestra es corta o ruidosa, el acento se degrada.
6. El audio de Edge TTS requiere conexión; OpenVoice/MeloTTS funcionan offline.

## 9. Plan incremental (Sprints 2–10) y estado

| Sprint | Alcance | Estado en esta entrega |
|---|---|---|
| 1 | Auditoría, arquitectura, prueba de hardware | **Completado** (este documento) |
| 2 | Perfil de voz: muestras, procesado, motor, narración | Implementado |
| 3 | Naturalidad: números, términos técnicos, pausas, estilos | Implementado (ritmo/pausas, no emoción) |
| 4 | Avatares: foto, calidad, encuadre, fondos, biblioteca | Implementado (sin recorte de fondo) |
| 5 | Animación y sincronización labial | Implementado (amplitud + 2D caricatura) |
| 6 | Integración audiovisual: 7 modos, FFmpeg, Cartoon Studio | Implementado |
| 7 | Panel web | Implementado |
| 8 | Redes sociales, metadatos, aprobación única | Implementado |
| 9 | Optimización/seguridad: cola, RAM, borrado, consentimiento | Implementado |
| 10 | Pruebas y documentación | Pruebas automatizadas + manuales |

Los criterios de aceptación y las evidencias ejecutadas se detallan en
`docs/bynnex-personal-studio.md`.
