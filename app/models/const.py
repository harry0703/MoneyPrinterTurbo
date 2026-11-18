PUNCTUATIONS = [
    "?",
    ",",
    ".",
    "、",
    ";",
    ":",
    "!",
    "…",
    "？",
    "，",
    "。",
    "、",
    "；",
    "：",
    "！",
    "...",
    # Common Arabic punctuation should also be natural sentence break points, so the script text and the subtitle pause boundaries
    # returned by edge-tts don't disagree and break later line-by-line matching.
    "،",
    "؛",
    "؟",
    # Full stops of scripts that do not use ".": Devanagari and Bengali danda,
    # Urdu, Burmese, Khmer and Ethiopic. Edge TTS word boundaries leave these
    # out or attach them to the last word, so they must end script lines too.
    "।",
    "॥",
    "۔",
    "။",
    "។",
    "።",
]

TASK_STATE_FAILED = -1
TASK_STATE_COMPLETE = 1
TASK_STATE_PROCESSING = 4

CROSS_POST_STATE_PENDING = "pending"
CROSS_POST_STATE_PROCESSING = "processing"
CROSS_POST_STATE_COMPLETE = "complete"
CROSS_POST_STATE_FAILED = "failed"

FILE_TYPE_VIDEOS = ["mp4", "mov", "mkv", "webm"]
FILE_TYPE_IMAGES = ["jpg", "jpeg", "png", "bmp"]
