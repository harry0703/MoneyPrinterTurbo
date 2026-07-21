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

# Idempotency reservation outcomes returned by state.reserve_idempotent_task.
# - created:  this is the first valid request for the key; caller may enqueue.
# - duplicate: an identical prior submission exists; caller must NOT enqueue
#              and should return the existing task id (lost-response recovery).
# - conflict: the same key was used with different canonical parameters; caller
#              must reject with a stable 409 idempotency_conflict response.
IDEMPOTENCY_CREATED = "created"
IDEMPOTENCY_DUPLICATE = "duplicate"
IDEMPOTENCY_CONFLICT = "conflict"

FILE_TYPE_VIDEOS = ["mp4", "mov", "mkv", "webm"]
FILE_TYPE_IMAGES = ["jpg", "jpeg", "png", "bmp"]
