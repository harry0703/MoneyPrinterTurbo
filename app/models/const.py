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
TASK_STATE_COMPLETE = 1
TASK_STATE_PROCESSING = 4

CROSS_POST_STATE_PENDING = "pending"
CROSS_POST_STATE_PROCESSING = "processing"
CROSS_POST_STATE_COMPLETE = "complete"
CROSS_POST_STATE_FAILED = "failed"

# youtube_review_required: vídeo sobe como "private" e espera revisão manual
# do usuário (título/descrição/tags) antes de publicar ou agendar no YouTube.
YOUTUBE_REVIEW_STATE_PENDING = "pending"
YOUTUBE_REVIEW_STATE_FAILED = "failed"
YOUTUBE_REVIEW_STATE_PUBLISHED = "published"
YOUTUBE_REVIEW_STATE_SCHEDULED = "scheduled"

FILE_TYPE_VIDEOS = ["mp4", "mov", "mkv", "webm"]
FILE_TYPE_IMAGES = ["jpg", "jpeg", "png", "bmp"]
