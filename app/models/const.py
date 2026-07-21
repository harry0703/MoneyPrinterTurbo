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
    # 阿拉伯语常用标点也应作为自然断句点，避免脚本文本和 edge-tts
    # 返回的字幕停顿边界不一致，导致后续逐行匹配失败。
    "،",
    "؛",
    "؟",
]

TASK_STATE_FAILED = -1
TASK_STATE_QUEUED = 0
TASK_STATE_COMPLETE = 1
TASK_STATE_PROCESSING = 4

# Idempotency claim and atomic-acceptance outcomes.
IDEMPOTENCY_CREATED = "created"
IDEMPOTENCY_DUPLICATE = "duplicate"
IDEMPOTENCY_CONFLICT = "conflict"
IDEMPOTENCY_PENDING = "pending"
IDEMPOTENCY_ACCEPTED = "accepted"
IDEMPOTENCY_STALE = "stale"
IDEMPOTENCY_QUEUE_FULL = "queue_full"

IDEMPOTENCY_PHASE_PENDING = "pending"
IDEMPOTENCY_PHASE_ACCEPTED = "accepted"
IDEMPOTENCY_ACCEPTED_TTL_SECONDS = 86400
TASK_TERMINAL_MARKER_PREFIX = "task_terminal:"

FILE_TYPE_VIDEOS = ["mp4", "mov", "mkv", "webm"]
FILE_TYPE_IMAGES = ["jpg", "jpeg", "png", "bmp"]
