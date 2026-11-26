# BYNEX AI Personal Studio — manual de usuario y técnico

Módulo local de **voz clonada** y **avatares personalizados** integrado en el
panel existente de MoneyPrinterTurbo v1.3.10 junto a Cartoon Studio 2D.
Genera videos verticales, horizontales o cuadrados con la voz y la imagen del
titular autorizado, exige aprobación humana y **no publica en ninguna red**.

- Informe de auditoría previo: [`docs/bynnex-personal-studio-audit.md`](bynnex-personal-studio-audit.md)
- Código: `app/services/personal_studio/`, `webui/personal_studio.py`
- Pruebas: `test/services/test_personal_studio_*.py`

---

## 1. Qué está implementado

| Capacidad | Estado real |
|---|---|
| Perfil de voz con muestras WAV/MP3/FLAC/M4A/OGG/AAC | Sí |
| Grabación desde micrófono (`st.audio_input`) con consentimiento | Sí |
| Análisis de ruido, SNR, nivel, recorte, silencios y nota 0-100 | Sí |
| Limpieza: highpass, reducción de ruido, recorte de silencios, loudnorm | Sí |
| Clonación de timbre local (MeloTTS ES + OpenVoice V2) | **Sí, verificada en este equipo** |
| Vista previa antes de aprobar el perfil | Sí |
| Narración de guiones con números y términos técnicos expandidos | Sí |
| Pausas y estilos de locución (ritmo, no emoción) | Sí |
| Exportación de narración WAV y MP3 | Sí |
| Perfil de avatar desde foto con detección de rostro | Sí (OpenCV si existe; si no, heurística) |
| Biblioteca de avatares, miniaturas, borrado | Sí |
| Animación 2.5D: respiración, balanceo, parpadeo, boca por amplitud | Sí |
| Caricatura 2D con paleta derivada de la foto | Sí |
| Siete modos de producción | Sí |
| Subtítulos ASS quemados + SRT descargable | Sí |
| Música de fondo, logotipo, CTA final | Sí |
| Cola secuencial, cancelación, recuperación tras reinicio | Sí |
| Aprobación con huella de contenido y exportación bloqueada | Sí |
| Metadatos por plataforma y divulgación de contenido sintético | Sí |
| Panel integrado con 10 pestañas | Sí |

## 2. Requisitos y reutilización

No se instaló ninguna dependencia nueva. Se reutiliza:

- `.venv` de la aplicación (Python 3.11, Streamlit, Pillow, pydub, FFmpeg).
- `local-voice/.venv` (Python 3.11, **torch 2.15.0+cpu**, MeloTTS, OpenVoice V2).
- `local-voice/checkpoints_v2` con `es.pth` y el conversor de timbre.
- FFmpeg 9.0.2 y `ffprobe` del sistema.
- El motor `cartoon_animation` para la caricatura y su codificador de video.

**MeCab no es necesario**: el error aparece solo al importar la ruta japonesa de
MeloTTS. El trabajador fuerza `language="ES"` y valida los checkpoints antes de
cargar el modelo.

## 3. Arranque (PowerShell)

```powershell
cd "C:\Users\NELSON JULIO\crewai_ollama\MoneyPrinterTurbo"
.\.venv\Scripts\python.exe -m streamlit run webui\Main.py
```

En la barra de secciones elige **BYNEX Studio** (junto a "Generar video" y
"Cartoon Studio 2D"). Todo el almacenamiento queda en
`storage\personal_studio\`.

Pruebas del módulo:

```powershell
.\.venv\Scripts\python.exe -m pytest test\services\test_personal_studio_audio.py `
  test\services\test_personal_studio_script.py `
  test\services\test_personal_studio_security.py `
  test\services\test_personal_studio_voice_profiles.py `
  test\services\test_personal_studio_avatars.py `
  test\services\test_personal_studio_studio.py `
  test\services\test_personal_studio_visuals.py -q
```

## 4. Flujo de usuario

### 4.1 Mi voz

1. **Crear perfil**: nombre, idioma (español), notas y autorización.
   Se exige nombre del titular, confirmación de autorización y de mayoría de
   edad; si es menor, nombre del tutor.
2. **Añadir muestras**: sube archivos o graba desde el micrófono. Cada muestra
   se analiza (original y limpia) y se muestran sus problemas.
3. **Procesar muestras**: elige hasta 4 muestras con mejor nota, con un máximo
   de 30 s, y crea `reference.wav`.
4. **Vista previa**: sintetiza un texto de prueba y lo reproduce. Puedes
   compararlo con tu grabación original.
5. **Aprobar perfil**: sin esta aprobación el estudio no narra.

Textos guía incluidos: pronunciación, números y precios, términos tecnológicos,
pausas y preguntas, en español colombiano.

### 4.2 Mis avatares

- Sube una foto de al menos 512 px por lado.
- Se calculan nitidez, brillo, contraste y una caja de rostro **solo para
  encuadrar**; no se identifica a la persona.
- Estilos: realista, semirrealista, corporativo, caricatura 2D, cómic,
  ilustrado y presentador tecnológico.
- La foto se recorta en cuadrado y se guarda con permisos restringidos.

### 4.3 Estudio personal

Campos reales del proyecto: nombre, descripción, tema, guion, palabras clave,
perfil de voz, perfil de avatar, estilo, tipo de video, escenario, resolución
(calculada), FPS, relación de aspecto, subtítulos, música, logotipo, posición del
logotipo, CTA y plataforma.

La **duración** no se escribe a mano: se conoce al narrar y se muestra en el
resultado. Así el panel no promete un dato que no existe todavía.

Modos:

| Modo | Qué produce |
|---|---|
| Tradicional | Diapositivas con zoom suave y voz personal |
| Avatar presentador | Tu avatar a cámara con animación 2.5D |
| Caricatura 2D | Personaje animado con tu paleta y tu voz |
| Híbrido | Diapositivas a la izquierda y avatar a la derecha |
| Podcast | MP3 + portada cuadrada + metadatos |
| Tutorial | Capturas o diapositivas con narración y subtítulos |
| Publicidad | Presentador + 2,2 s finales con tu llamada a la acción |

### 4.4 Aprobaciones y exportaciones

1. Genera el proyecto desde la cola.
2. Revisa el video en **Aprobaciones**.
3. Escribe tu nombre de revisor y aprueba, pide cambios o rechaza.
4. Solo con aprobación vigente se habilita **Exportar**.
5. La exportación copia `video.mp4`, `narration.mp3`, `subtitles.srt`,
   `cover.png`, `metadata.json` y `publication.json` a
   `storage/personal_studio/exports/<proyecto>_<plataforma>/`.
   `publication.json` declara `auto_publish: false` y `published: false`.

## 5. Arquitectura

```
webui/personal_studio.py          Panel Streamlit (10 pestañas)
        │
        ├── app/services/personal_studio/studio.py        proyectos, 7 modos, aprobación, export
        ├── …/voice_profiles.py    muestras, limpieza, reference.wav, borrado
        ├── …/engines.py           adaptadores y sondeo de motores
        │      └── voice_worker.py (subproceso en local-voice/.venv)
        ├── …/avatars.py           foto, calidad, rostro, paleta, biblioteca
        ├── …/visuals.py           fotogramas 2.5D, caricatura, diapositivas
        ├── …/compose.py           ASS/SRT, mux, música, logotipo
        ├── …/audio.py             análisis y filtros FFmpeg
        ├── …/script.py            números, glosario, pausas, segmentos
        ├── …/social.py            metadatos y divulgación por plataforma
        ├── …/jobs.py              cola secuencial persistida
        ├── …/resources.py         RAM/CPU/disco sin psutil
        ├── …/diagnostics.py       informe y prueba de humo
        ├── …/security.py          consentimiento firmado y rutas confinadas
        └── …/presets.py           catálogos visibles en el panel
```

### 5.1 Por qué la voz corre en otro proceso

El entorno de la app usa numpy 2.x y no tiene torch. `local-voice/.venv` usa
numpy 1.23.5 y torch 2.15 CPU. Importar OpenVoice en la app rompería el entorno.
Por eso `engines.py` escribe un trabajo JSON por `stdin` y lanza
`voice_worker.py`; el resultado llega en un archivo `report` y en un WAV.
Al terminar, la memoria de los modelos se libera con el proceso.

Protocolo resumido:

```json
{
  "segments": [{"text": "Bienvenidos a BYNEX.", "pause_after": 0.25}],
  "output": "…/narration.wav",
  "reference": "…/voices/v_xxx/reference.wav",
  "checkpoints": "…/local-voice/checkpoints_v2",
  "language": "ES",
  "speed": 1.0,
  "cache_dir": "…/voices/.se_cache/v_xxx",
  "digest": "<sha256 de reference.wav>",
  "watermark": "@BYNEX",
  "sample_rate": 24000,
  "ffmpeg": "…/ffmpeg.exe",
  "report": "…/.voice-report.json"
}
```

El trabajador sintetiza todos los segmentos con una sola carga de MeloTTS,
concatena con las pausas y aplica OpenVoice **una vez** sobre el audio completo.
La caché de timbre evita recalcular la extracción en cada narración.

### 5.2 Almacenamiento

```
storage/personal_studio/
├── voices/<v_id>/
│   ├── profile.json          consentimiento firmado, métricas, estado
│   ├── samples/              originales + .clean.wav
│   ├── reference.wav         timbre para OpenVoice
│   └── preview.wav
├── voices/.se_cache/<v_id>/  speaker embedding cacheado
├── avatars/<a_id>/
│   ├── avatar.json           calidad, rostro, paleta, consentimiento
│   ├── source.png, portrait.png, thumb.png
├── projects/<p_id>/
│   ├── project.json
│   ├── assets/               imágenes, logotipo, música
│   ├── outputs/              video.mp4, narration.*, subtitles.srt, cover.png, metadata.json
│   └── approvals.json        historial de revisiones
├── exports/<proyecto>_<plataforma>/
└── jobs.json
```

### 5.3 Aprobación con huella

`studio.fingerprint()` combina guion, modo, estilo, escenario, plataforma,
calidad, aspecto, FPS, subtítulos, voz, avatar, CTA, logotipo, música,
imágenes y los SHA-256 de narración y video. Si cambia cualquier elemento,
`approval_state()` marca la aprobación como caducada y `export()` se niega.

### 5.4 Cola y cancelación

- Un trabajador pesado a la vez (`ThreadPoolExecutor(max_workers=1)`).
- Estado persistido en `jobs.json`; tras un reinicio lo que estaba en curso se
  marca como interrumpido, nunca como completado.
- Cancelar activa un `Event`; el bucle de fotogramas y el proceso de voz lo
  consultan. FFmpeg se termina y no queda archivo temporal.

## 6. Uso programático

```python
from app.services.personal_studio.voice_profiles import VoiceStore
from app.services.personal_studio.avatars import AvatarStore
from app.services.personal_studio.studio import ProjectStore, build_project, approve, export

voices = VoiceStore()
profile = voices.create(name="Mi voz", consent={
    "subject_name": "Nelson Julio",
    "granted": True,
    "age_confirmed": True,
    "scope": ["voz"],
})
voices.add_sample(profile["id"], "muestra.wav", open("muestra.wav", "rb").read())
voices.process(profile["id"])
voices.approve(profile["id"])

projects = ProjectStore()
project = projects.create({
    "name": "Consejo BYNEX",
    "script": "Bienvenidos a BYNEX. Hoy hablamos de copias de seguridad.",
    "voice_id": profile["id"],
    "mode": "presentador",
    "platform": "instagram_reels",
    "quality": "economico",
})
build_project(project["id"])
approve(project["id"], reviewer="Nelson", decision="approve")
print(export(project["id"])["path"])
```

## 7. Privacidad, consentimiento y seguridad

- **Consentimiento firmado** por perfil con SHA-256 del contenido canónico.
  Alterar el nombre, el alcance o el estado de edad invalida la firma.
- **Alcance separado**: un perfil de voz autoriza `voz`; uno de imagen autoriza
  `imagen`. No se puede usar un consentimiento para el otro fin.
- **Menores**: se exige tutor; el contenido queda marcado y el panel avisa que
  no se automatiza ninguna publicación.
- **Rutas confinadas**: todo identificador se valida y cada ruta se resuelve
  contra su directorio base (`confined_path`).
- **Permisos**: se aplica `chmod` al propietario cuando el sistema lo permite.
  En Windows NTFS los permisos POSIX son limitados: **el módulo no cifra el
  disco**. Para datos sensibles, usa BitLocker o una carpeta cifrada.
- **Borrado**: elimina el perfil desde el panel; se borran muestras, referencia,
  vista previa y miniaturas. La caché de timbre queda bajo `voices/.se_cache` y
  también se puede borrar.
- **Sin envío externo**: OpenVoice y MeloTTS son locales. Solo **Edge TTS**, si
  se elige como respaldo, envía el texto a Microsoft; el resultado lo advierte.
- **Marca de agua**: OpenVoice inserta `@BYNEX` en el audio convertido.
- **Prohibiciones** (en el texto del consentimiento y en la UI): suplantación,
  engaño, evasión de autenticación biométrica y uso de terceros sin permiso.

## 8. Divulgación de contenido sintético

Verificado en fuentes oficiales (noviembre de 2026):

- **YouTube**: hay que declarar contenido sintético que haga parecer que una
  persona real dice o hace algo que no hizo, altere un evento real o genere una
  escena realista; las animaciones no realistas no lo requieren.
- **Meta (Facebook, Instagram, Threads)**: se exige etiqueta "AI info" para
  video fotorrealista o audio realista creado o alterado con IA.
- **TikTok**: exige etiquetar AIGC que muestre escenas o personas realistas;
  también prohíbe suplantar a figuras privadas sin permiso.

El módulo escribe `ai_disclosure` en `metadata.json` y `publication.json`
siempre que la narración sea sintética (incluido el respaldo Edge TTS). Las
animaciones 2D no realistas se marcan igualmente por prudencia.

## 9. Pruebas y evidencias ejecutadas

Comandos ejecutados en este equipo (Windows 11, Ryzen 5 5500U, 12 GB, CPU):

| Prueba | Resultado |
|---|---|
| Importación del entorno de voz | `torch 2.15.0+cpu`, `melo`, `openvoice` OK |
| MeloTTS ES, 2 frases | 6.41 s de audio en 6.2 s (carga 12.5 s) |
| OpenVoice E2E (`clonar_voz.py`) | 18.9 s para 6.4 s de narración, WAV generado |
| Clonación vía API del módulo | 5.87 s de audio en 31.6 s (incluye 2 cargas de modelo) |
| Proyecto presentador 480p 9:16 | `rendered`, MP4 76 KB, 5.68 s |
| Aprobación y exportación | Aprobación vigente + paquete con 4 archivos |
| Los 7 modos | 6 modos adicionales generan video/audio correctamente |
| Panel Streamlit (`AppTest`) | 10 pestañas, 0 excepciones |
| Pruebas automatizadas nuevas | **58 pasaron** |
| Pruebas WebUI existentes | 32 pasaron |
| Ruff en archivos nuevos y `Main.py` | sin hallazgos |

Las pruebas automatizadas cubren análisis de audio, limpieza, perfiles,
consentimiento, rutas, avatares, guion, proyectos, huella de aprobación, cola,
metadatos, subtítulos y un render pequeño real con FFmpeg. La síntesis con
OpenVoice **no** está en la suite automática porque tarda ~30 s y requiere los
checkpoints; se verificó manualmente con la evidencia de arriba.

## 10. Limitaciones declaradas

1. **No hay fotorrealismo tipo SadTalker/LivePortrait.** La animación es 2.5D
   determinista; la boca sigue la **amplitud** del audio, no fonemas.
2. **No se recorta el fondo** de la foto: falta segmentación (`rembg`/`cv2`).
   Se usa fondo desenfocado de la propia foto o un escenario cartoon.
3. **Detección de rostro heurística** si no hay OpenCV; puede fallar con fondos
   de tono piel. El panel muestra el resultado y el encuadre es automático.
4. **Sin control emocional** del modelo. Los estilos cambian ritmo y pausas.
5. **Acento colombiano** depende de la muestra del usuario; la voz base es
   española neutra. Muestras cortas o ruidosas degradan el resultado.
6. **1080p no está medido** en este equipo; el perfil "Alta calidad" se marca
   como no verificado y puede tardar varios minutos por minuto de video.
7. **Piper** solo funciona si el usuario instala el binario y una voz
   (el motor es GPL-3.0 y cada voz tiene su licencia). No se descargó nada.
8. **XTTS v2 y F5-TTS se descartaron** por licencia no comercial de sus pesos.
9. **Publicación**: no existe integración de subida. El paquete exportado es
   local y requiere acción manual.
10. **Windows**: `chmod` es limitado; el cifrado del disco es responsabilidad
    del usuario.

## 11. Próximos pasos sugeridos

- Medir 1080p y ajustar `QUALITY_PROFILES["alta"]["verified"]` con evidencia.
- Instalar `opencv-python` (wheel CPU) para detección Haar más fiable sin GPU.
- Evaluar `rembg` para recorte de fondo si se autoriza la descarga del modelo.
- Añadir un corrector de pronunciación por palabra cuando se detecten errores
  concretos en la voz clonada.
- Integrar la subida opcional con `upload_post` (ya presente en el proyecto)
  manteniendo la aprobación manual obligatoria.
