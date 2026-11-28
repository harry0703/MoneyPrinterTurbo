"""Catálogos estáticos de BYNEX AI Personal Studio.

Todo lo que el panel muestra como opción vive aquí para que la UI, la capa de
servicio y las pruebas usen la misma fuente. Solo se declaran capacidades que
el motor real soporta; por ejemplo, ningún estilo promete control emocional
porque MeloTTS no expone embeddings de emoción.
"""

from __future__ import annotations

# Perfiles de procesamiento. `verified` indica si la resolución se ha medido en
# este equipo; el panel lo muestra y la cola avisa antes de usar uno no medido.
QUALITY_PROFILES: dict[str, dict] = {
    "economico": {
        "label": "Económico",
        "max_height": 480,
        "fps": 20,
        "crf": 26,
        "preset": "veryfast",
        "work_width": 480,
        "verified": True,
        "note": "Vista previa rápida y consumo bajo de RAM.",
    },
    "equilibrado": {
        "label": "Equilibrado",
        "max_height": 720,
        "fps": 24,
        "crf": 22,
        "preset": "veryfast",
        "work_width": 640,
        "verified": True,
        "note": "Calidad para redes sociales con recursos controlados.",
    },
    "alta": {
        "label": "Alta calidad",
        "max_height": 1080,
        "fps": 24,
        "crf": 20,
        "preset": "medium",
        "work_width": 720,
        "verified": False,
        "note": "Procesamiento por segmentos; más lento. Sin medir en este equipo.",
    },
}

# Plataformas y formatos. Los límites son conservadores y locales: no se
# consultan APIs de cada red. `aspect` se usa para derivar ancho/alto.
PLATFORMS: dict[str, dict] = {
    "whatsapp": {
        "label": "WhatsApp",
        "aspect": "1:1",
        "max_seconds": 90,
        "title_limit": 100,
        "hashtags": 3,
        "note": "Estado de WhatsApp: cuadrado y breve.",
    },
    "facebook": {
        "label": "Facebook",
        "aspect": "16:9",
        "max_seconds": 600,
        "title_limit": 120,
        "hashtags": 5,
    },
    "facebook_reels": {
        "label": "Facebook Reels",
        "aspect": "9:16",
        "max_seconds": 90,
        "title_limit": 100,
        "hashtags": 5,
    },
    "instagram_reels": {
        "label": "Instagram Reels",
        "aspect": "9:16",
        "max_seconds": 90,
        "title_limit": 100,
        "hashtags": 5,
    },
    "instagram_stories": {
        "label": "Instagram Stories",
        "aspect": "9:16",
        "max_seconds": 60,
        "title_limit": 90,
        "hashtags": 3,
    },
    "tiktok": {
        "label": "TikTok",
        "aspect": "9:16",
        "max_seconds": 180,
        "title_limit": 100,
        "hashtags": 5,
    },
    "youtube": {
        "label": "YouTube",
        "aspect": "16:9",
        "max_seconds": 3600,
        "title_limit": 100,
        "hashtags": 5,
    },
    "youtube_shorts": {
        "label": "YouTube Shorts",
        "aspect": "9:16",
        "max_seconds": 60,
        "title_limit": 100,
        "hashtags": 5,
    },
}

ASPECT_SIZES: dict[str, tuple[int, int]] = {
    "9:16": (1080, 1920),
    "16:9": (1920, 1080),
    "1:1": (1080, 1080),
}

# Los estilos se implementan con ritmo, pausas y segmentación del guion. No son
# emociones del modelo: el campo `pacing` lo dice explícitamente en la UI.
NARRATION_STYLES: dict[str, dict] = {
    "profesional": {
        "label": "Profesional",
        "rate": 0.98,
        "pause": 0.32,
        "max_chars": 190,
        "pacing": "Frases medidas y pausas cortas.",
    },
    "educativo": {
        "label": "Educativo",
        "rate": 0.94,
        "pause": 0.45,
        "max_chars": 170,
        "pacing": "Ritmo pausado para explicar.",
    },
    "conversacional": {
        "label": "Conversacional",
        "rate": 1.02,
        "pause": 0.25,
        "max_chars": 160,
        "pacing": "Frases cortas, cercanas.",
    },
    "publicitario": {
        "label": "Publicitario",
        "rate": 1.08,
        "pause": 0.18,
        "max_chars": 140,
        "pacing": "Ritmo ágil con énfasis por frase.",
    },
    "entusiasta": {
        "label": "Entusiasta",
        "rate": 1.08,
        "pause": 0.2,
        "max_chars": 150,
        "pacing": "Energía alta mediante frases breves.",
    },
    "corporativo": {
        "label": "Corporativo",
        "rate": 0.96,
        "pause": 0.38,
        "max_chars": 200,
        "pacing": "Tono sobrio y pausado.",
    },
    "humoristico": {
        "label": "Humorístico",
        "rate": 1.04,
        "pause": 0.3,
        "max_chars": 140,
        "pacing": "Pausas cómicas antes del remate.",
    },
    "narrativo": {
        "label": "Narrativo",
        "rate": 0.96,
        "pause": 0.42,
        "max_chars": 180,
        "pacing": "Pausas largas entre ideas.",
    },
    "tranquilo": {
        "label": "Tranquilo",
        "rate": 0.9,
        "pause": 0.5,
        "max_chars": 165,
        "pacing": "Ritmo lento y pausas amplias.",
    },
    "motivacional": {
        "label": "Motivacional",
        "rate": 1.02,
        "pause": 0.3,
        "max_chars": 150,
        "pacing": "Cierre de frase con pausa enfática.",
    },
}

PRODUCTION_MODES: dict[str, dict] = {
    "tradicional": {
        "label": "Video tradicional con voz personal",
        "kind": "video",
        "needs_avatar": False,
        "needs_images": True,
        "description": "Imágenes narradas con tu voz autorizada.",
    },
    "presentador": {
        "label": "Avatar presentador",
        "kind": "video",
        "needs_avatar": True,
        "needs_images": False,
        "description": "Tu avatar presenta el contenido a cámara.",
    },
    "caricatura": {
        "label": "Caricatura 2D personalizada",
        "kind": "video",
        "needs_avatar": True,
        "needs_images": False,
        "description": "Personaje 2D animado con tu paleta y tu voz.",
    },
    "hibrido": {
        "label": "Video híbrido",
        "kind": "video",
        "needs_avatar": True,
        "needs_images": True,
        "description": "Avatar a un lado y material visual al otro.",
    },
    "podcast": {
        "label": "Podcast personalizado",
        "kind": "audio",
        "needs_avatar": False,
        "needs_images": False,
        "description": "Audio narrado con portada para podcast.",
    },
    "tutorial": {
        "label": "Tutorial tecnológico",
        "kind": "video",
        "needs_avatar": False,
        "needs_images": True,
        "description": "Capturas o diapositivas con narración y subtítulos.",
    },
    "publicidad": {
        "label": "Publicidad automatizada",
        "kind": "video",
        "needs_avatar": True,
        "needs_images": False,
        "description": "Promoción de un servicio BYNEX con cierre y llamada a la acción.",
    },
}

AVATAR_STYLES: dict[str, dict] = {
    "realista": {"label": "Realista", "engine": "photo", "note": "Foto con animación 2.5D."},
    "semirrealista": {"label": "Semirrealista", "engine": "photo"},
    "corporativo": {"label": "Corporativo", "engine": "photo"},
    "caricatura": {"label": "Caricatura 2D", "engine": "cartoon"},
    "comic": {"label": "Estilo cómic", "engine": "cartoon"},
    "ilustrado": {"label": "Ilustrado", "engine": "cartoon"},
    "presentador": {"label": "Presentador tecnológico", "engine": "photo"},
}

SCENES: dict[str, dict] = {
    "estudio": {"label": "Estudio", "kind": "gradient"},
    "oficina": {"label": "Oficina", "kind": "gradient"},
    "tecnologico": {"label": "Tecnológico", "kind": "gradient"},
    "jardin": {"label": "Jardín", "kind": "cartoon", "asset": "garden"},
    "pradera": {"label": "Pradera", "kind": "cartoon", "asset": "meadow"},
    "noche": {"label": "Noche", "kind": "cartoon", "asset": "night"},
    "estudio_cartoon": {"label": "Estudio cartoon", "kind": "cartoon", "asset": "studio"},
}

# Textos originales en español colombiano para evaluar la voz.
VOICE_SAMPLE_SCRIPTS: dict[str, str] = {
    "pronunciacion": (
        "Buenos días, soy la voz de BYNEX. En Cartagena de Indias trabajamos con "
        "tecnología clara, cercana y bien explicada. ¿Me escuchas con naturalidad?"
    ),
    "numeros": (
        "El plan económico cuesta 49.900 pesos al mes; el equilibrado, 89.900; y "
        "el anual tiene un descuento del 15 por ciento. Llámanos al 300 123 4567."
    ),
    "tecnologia": (
        "Configuramos Wi-Fi, correo corporativo, copias de seguridad y Python. "
        "También revisamos la API, el servidor y la base de datos en la nube."
    ),
    "pausas": (
        "Primero revisamos tu equipo. Después explicamos el diagnóstico. "
        "Finalmente entregamos una solución y te acompañamos en la posventa."
    ),
    "preguntas": (
        "¿Tu computador está lento? ¿Necesitas una página web? ¿Quieres automatizar "
        "tareas repetitivas? En BYNEX encontramos la respuesta correcta."
    ),
}

# Términos que el español neutro suele pronunciar mal. La sustitución es
# conservadora y se puede desactivar; no traduce el significado.
TECH_TERMS: dict[str, str] = {
    "Wi-Fi": "wifi",
    "WiFi": "wifi",
    "online": "en línea",
    "email": "correo electrónico",
    "software": "programas",
    "hardware": "equipos",
    "backup": "copia de seguridad",
    "link": "enlace",
}

AI_DISCLOSURE = (
    "Este contenido fue generado con inteligencia artificial a partir de la voz "
    "y la imagen autorizadas de su titular. Puede incluir audio sintético."
)

DEFAULT_HASHTAGS = ("#BYNEX", "#Tecnología", "#Colombia", "#SoporteTécnico")
