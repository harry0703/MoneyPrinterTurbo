"""前置选题工坊：按「画面形态 + 内容体裁」产出可直接开拍的爆款选题方案。

本模块只负责三件事：
1. 维护画面形态与内容体裁两套预设（预设是领域数据，因此自带中英双语文案）；
2. 调用 LLM 生成结构化选题方案（JSON），并在模型不可用时降级为启发式方案；
3. 把选中的方案翻译成一份可以直接写回页面控件的生成参数。

真正的表单填充与任务提交仍由 WebUI 负责，服务层不依赖 Streamlit。
"""

import json
import re
from typing import Any, Dict, List, Optional

from loguru import logger

from app.models.schema import VideoAspect, VideoConcatMode, VideoFitMode
from app.services import llm

# 方案数量范围。上限刻意压到 6，避免一次请求产出过多方案导致模型输出被截断，
# 也避免用户在面对十几个选项时失去判断力。
MIN_CANDIDATE_COUNT = 1
MAX_CANDIDATE_COUNT = 6
DEFAULT_CANDIDATE_COUNT = 4

MAX_DIRECTION_LENGTH = 300
MAX_SUBJECT_LENGTH = 60
MAX_TITLE_LENGTH = 24
MAX_HOOK_LENGTH = 120
MAX_AUDIENCE_LENGTH = 60
MAX_REASON_LENGTH = 160
MAX_OUTLINE_ITEM_LENGTH = 80
MAX_OUTLINE_ITEMS = 6
MAX_KEYWORD_COUNT = 6
MAX_KEYWORD_LENGTH = 16

# 素材检索关键词需要落到具体的可视画面，抽象词会让素材库返回一堆无关片段。
_KEYWORD_BLACKLIST = {
    "视频",
    "素材",
    "画面",
    "背景",
    "场景",
    "镜头",
    "内容",
    "主题",
    "video",
    "footage",
    "background",
    "scene",
}

_EMOTION_OPTIONS = ("悬念", "治愈", "愤怒", "共鸣", "爽感", "惊奇", "温情")

_BGM_TYPE_OPTIONS = ("random", "")

# 降级占位方案的标记字段。只用于界面提示，不会随生成参数下传。
FALLBACK_FLAG = "is_fallback"


# ---------------------------------------------------------------------------
# 预设：画面形态
# ---------------------------------------------------------------------------
# requires_config_key 用于在 WebUI 里提前判断该形态能否一键开跑。素材库形态只需要
# 已经配置好的检索 Key；AI 生图形态需要图片模型；本地上传形态必须由用户选文件，
# 因此永远无法真正「一键」完成，界面会据此给出提示。
VISUAL_STYLES: List[Dict[str, Any]] = [
    {
        "id": "relax_video",
        "label": "解压氛围视频",
        "label_en": "Ambient Stock Video",
        "description": "从素材库取慢节奏实拍空镜，配合文案与配音，适合口播感弱的叙述型内容。",
        "description_en": "Slow stock footage from a video library, paired with narration for narrative content.",
        "video_source": "pexels",
        "requires_config_key": "pexels_api_keys",
        "video_aspect": VideoAspect.portrait.value,
        "video_concat_mode": VideoConcatMode.random.value,
        "video_fit_mode": VideoFitMode.cover.value,
        "clip_duration": 3,
        "keyword_style": "实拍空镜名词，优先夜晚街道、雨、窗边、公路、咖啡店这类有人味的具体场景",
    },
    {
        "id": "pure_image",
        "label": "纯图片轮播",
        "label_en": "Still Image Carousel",
        "description": "用 AI 生图产出一组统一风格的静态图，配文字与配音做轮播，画面一致性最好。",
        "description_en": "A consistent set of AI-generated stills with captions and voice-over.",
        "video_source": "openai_image",
        "requires_config_key": "openai_image_api_keys",
        "video_aspect": VideoAspect.portrait.value,
        "video_concat_mode": VideoConcatMode.random.value,
        "video_fit_mode": VideoFitMode.cover.value,
        "clip_duration": 4,
        "keyword_style": "静态画面描述名词，优先构图明确的特写与场景，如旧书桌、空荡教室、泛黄信纸",
    },
    {
        "id": "local_material",
        "label": "本地素材",
        "label_en": "Local Material",
        "description": "使用你自己上传的图片或视频。素材质量最高，但需要在生成前手动选择文件。",
        "description_en": "Use your own uploaded images or clips. Highest quality, but files must be selected manually.",
        "video_source": "local",
        "requires_config_key": None,
        "video_aspect": VideoAspect.portrait.value,
        "video_concat_mode": VideoConcatMode.random.value,
        "video_fit_mode": VideoFitMode.cover.value,
        "clip_duration": 3,
        "keyword_style": "用于给剪辑者看的画面提示，写成具体场景名词",
    },
]

# ---------------------------------------------------------------------------
# 预设：内容体裁
# ---------------------------------------------------------------------------
GENRES: List[Dict[str, Any]] = [
    {
        "id": "philosophy",
        "label": "哲理文案",
        "label_en": "Philosophy Copy",
        "description": "人生感悟、金句输出，靠共鸣转发。节奏短、句子狠、结尾留钩子。",
        "description_en": "Life insights and punchy aphorisms that ride on resonance and shares.",
        "paragraph_number": 3,
        "bgm_type": "random",
        "voice_rate": 1.0,
        "voice_hint": "沉稳男声，语速偏慢，句尾留白",
        "subtitle_position": "center",
        "font_size": 66,
        "topic_guide": "选题必须落在一个具体的生活困境上，不要空泛说教。爆点是「说出了我不敢说的话」。",
        "script_prompt": (
            "写作要求：\n"
            "1. 全篇围绕同一个具体生活困境展开，不要泛泛谈人生。\n"
            "2. 开头一句必须是反常识或扎心的判断句，不要铺垫。\n"
            "3. 中间用两到三个具体场景或细节支撑，不要抽象形容词堆砌。\n"
            "4. 结尾留一个开放式的反问或停顿，不要给标准答案。\n"
            "5. 每句不超过 20 字，长短句交错，适合配音朗读。"
        ),
    },
    {
        "id": "tianya",
        "label": "天涯神贴",
        "label_en": "Forum Legend Story",
        "description": "以第一人称讲述离奇经历或都市怪谈，靠真实感和细节抓人。",
        "description_en": "First-person recounting of uncanny experiences, carried by realism and detail.",
        "paragraph_number": 4,
        "bgm_type": "random",
        "voice_rate": 0.95,
        "voice_hint": "低沉男声，语速慢，气声偏重",
        "subtitle_position": "bottom",
        "font_size": 60,
        "topic_guide": "选题必须有「像是真事」的细节感，冲突来自信息不对称，结尾要留未解之谜。",
        "script_prompt": (
            "写作要求：\n"
            "1. 全程第一人称叙述，像在跟朋友讲一件亲身经历的事。\n"
            "2. 开头三句话内必须出现一个反常细节，把听众钉住。\n"
            "3. 中间至少给出三处具体到时间、地点、物件的细节，制造真实感。\n"
            "4. 不要解释、不要评论，只叙述发生过什么。\n"
            "5. 结尾不要揭开谜底，停在一个让人后背发凉的画面上。"
        ),
    },
    {
        "id": "drama_recap",
        "label": "短剧推文",
        "label_en": "Short Drama Recap",
        "description": "用强冲突剧情推进，三段一个小反转，目的是让人看完点进原片。",
        "description_en": "High-conflict plot with a twist every few lines, driving clicks to the full show.",
        "paragraph_number": 4,
        "bgm_type": "random",
        "voice_rate": 1.1,
        "voice_hint": "年轻女声或男声，语速偏快，情绪起伏明显",
        "subtitle_position": "bottom",
        "font_size": 62,
        "topic_guide": "选题必须一句话能说清核心冲突，主角要处在被压迫的弱势位置，观众要替他憋屈。",
        "script_prompt": (
            "写作要求：\n"
            "1. 开篇第一句直接抛出冲突，不要交代背景。\n"
            "2. 全篇围绕一个核心矛盾推进，不要分散支线。\n"
            "3. 每两到三句安排一个小反转，情绪要持续加码。\n"
            "4. 主角必须处在明显吃亏的位置，让听众替他憋屈。\n"
            "5. 结尾停在冲突最高点，不要给出结局。"
        ),
    },
    {
        "id": "novel_recap",
        "label": "小说推文",
        "label_en": "Novel Recap",
        "description": "小说情节解说，保留原文爽点，靠悬念驱动完播和追更。",
        "description_en": "Novel plot narration that keeps the payoff beats and drives completion.",
        "paragraph_number": 4,
        "bgm_type": "random",
        "voice_rate": 1.05,
        "voice_hint": "清晰中性声线，语速中偏快，重音落在转折处",
        "subtitle_position": "bottom",
        "font_size": 60,
        "topic_guide": "选题要挑小说里最爽或最虐的一个片段，能独立成立，不依赖前情。",
        "script_prompt": (
            "写作要求：\n"
            "1. 选一个能独立成立的桥段，不要从故事开头讲起。\n"
            "2. 用解说口吻转述，不要照抄原文长句。\n"
            "3. 保留原作的爽点或虐点，删掉与主线无关的铺垫。\n"
            "4. 每一段结尾都留一个悬念，勾住下一段。\n"
            "5. 最后一段停在情节最紧张处，明确引导听众去看原文。"
        ),
    },
    {
        "id": "folk_story",
        "label": "民间故事",
        "label_en": "Folk Tale",
        "description": "民间传说、历史秘闻、地方怪谈，靠奇观和道德落点吸引中老年受众。",
        "description_en": "Legends, historical oddities and local lore with a clear moral landing.",
        "paragraph_number": 4,
        "bgm_type": "random",
        "voice_rate": 0.95,
        "voice_hint": "说书感男声，语速慢，句间有停顿",
        "subtitle_position": "bottom",
        "font_size": 62,
        "topic_guide": "选题要有奇观感或因果报应结构，讲完要能落一句朴素的道理。",
        "script_prompt": (
            "写作要求：\n"
            "1. 用说书人的口吻讲一个有头有尾的故事。\n"
            "2. 故事里必须出现一个让人意外的奇观或转折。\n"
            "3. 人物动机要简单直白，善恶分明。\n"
            "4. 不要写景，只写事，句子短，适合念出来。\n"
            "5. 结尾落一句朴素但不说教的道理。"
        ),
    },
    {
        "id": "emotion",
        "label": "情感语录",
        "label_en": "Emotional Quotes",
        "description": "亲密关系里的共鸣片段，靠代入感和评论区互动拉数据。",
        "description_en": "Relationship resonance pieces that drive comments and shares.",
        "paragraph_number": 3,
        "bgm_type": "random",
        "voice_rate": 1.0,
        "voice_hint": "温柔女声，语速偏慢，情绪克制",
        "subtitle_position": "center",
        "font_size": 64,
        "topic_guide": "选题要写一个具体的相处瞬间，让听众自动代入自己的关系。",
        "script_prompt": (
            "写作要求：\n"
            "1. 围绕一个具体的相处瞬间展开，不要讲道理。\n"
            "2. 用第二人称或第一人称，制造贴身感。\n"
            "3. 细节要小到能被认出来，比如一句话、一个动作、一个时间点。\n"
            "4. 不要下结论，把判断留给听众。\n"
            "5. 结尾用一句短句收住，方便做评论区引导。"
        ),
    },
    {
        "id": "trivia",
        "label": "冷知识科普",
        "label_en": "Trivia Explainer",
        "description": "反常识知识点或悬案解析，靠「原来是这样」的惊奇感驱动完播。",
        "description_en": "Counter-intuitive facts or unsolved cases driven by surprise.",
        "paragraph_number": 3,
        "bgm_type": "random",
        "voice_rate": 1.05,
        "voice_hint": "中性偏亮的声线，语速中偏快，重音清晰",
        "subtitle_position": "bottom",
        "font_size": 60,
        "topic_guide": "选题必须是大多数人会猜错的问题，正确答案要让人有「居然是这样」的反应。",
        "script_prompt": (
            "写作要求：\n"
            "1. 开头先抛出一个大多数人会猜错的问题。\n"
            "2. 中间用两到三个可核实的事实推进，不要编造数据。\n"
            "3. 每一段都制造一次认知落差，先给直觉答案再推翻。\n"
            "4. 语言口语化，避免专业术语，必要时用比喻。\n"
            "5. 结尾给出结论并留一个延伸问题。"
        ),
    },
    {
        "id": "custom",
        "label": "自定义",
        "label_en": "Custom",
        "description": "不使用内置体裁规则，完全按你在下方补充的方向来生成。",
        "description_en": "No built-in genre rules; everything follows the direction you provide.",
        "paragraph_number": 3,
        "bgm_type": "random",
        "voice_rate": 1.0,
        "voice_hint": "按内容情绪自行选择",
        "subtitle_position": "bottom",
        "font_size": 60,
        "topic_guide": "按用户补充的方向自由发挥。",
        "script_prompt": "",
    },
]

_VISUAL_STYLE_BY_ID = {item["id"]: item for item in VISUAL_STYLES}
_GENRE_BY_ID = {item["id"]: item for item in GENRES}

DEFAULT_VISUAL_STYLE_ID = VISUAL_STYLES[0]["id"]
DEFAULT_GENRE_ID = GENRES[0]["id"]


def list_visual_styles() -> List[Dict[str, Any]]:
    return VISUAL_STYLES


def list_genres() -> List[Dict[str, Any]]:
    return GENRES


def get_visual_style(style_id: Optional[str]) -> Dict[str, Any]:
    return _VISUAL_STYLE_BY_ID.get(str(style_id or ""), VISUAL_STYLES[0])


def get_genre(genre_id: Optional[str]) -> Dict[str, Any]:
    return _GENRE_BY_ID.get(str(genre_id or ""), GENRES[0])


def normalize_candidate_count(value) -> int:
    try:
        count = int(value)
    except (TypeError, ValueError):
        count = DEFAULT_CANDIDATE_COUNT
    return max(MIN_CANDIDATE_COUNT, min(count, MAX_CANDIDATE_COUNT))


def normalize_direction(value) -> str:
    return (value or "").strip()[:MAX_DIRECTION_LENGTH]


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------
def build_topic_candidates_prompt(
    visual_style_id: str,
    genre_id: str,
    count: int = DEFAULT_CANDIDATE_COUNT,
    direction: str = "",
) -> str:
    """构造选题方案的提示词。

    输出结构写死在提示词里并配一条完整示例，是为了让不同厂商的模型都能稳定返回
    同一个 JSON 结构；解析层仍然做完整校验和降级，不依赖模型守规矩。
    """
    style = get_visual_style(visual_style_id)
    genre = get_genre(genre_id)
    count = normalize_candidate_count(count)
    direction = normalize_direction(direction)

    direction_block = (
        f"\n## 用户补充方向\n{direction}\n" if direction else ""
    )

    example = {
        "subject": "凌晨三点还在回工作消息的人，后来都怎么样了",
        "title": "凌晨三点的消息",
        "hook": "你以为他在拼命，其实他只是不敢关手机。",
        "audience": "25-35 岁一线城市上班族",
        "why": "戳中「不敢拒绝」的普遍羞耻感，评论区会自动吵起来。",
        "outline": [
            "开头抛出凌晨回消息的具体场景",
            "中间给出两个代价：健康与关系",
            "结尾反问：你上一次关机是什么时候",
        ],
        "keywords": ["深夜办公室", "亮着的手机屏幕", "空荡的地铁站", "雨夜写字楼"],
        "emotion": "共鸣",
        "voice_hint": "沉稳男声，语速偏慢",
        "aspect": "9:16",
        "paragraph_number": 3,
        "clip_duration": 3,
        "bgm_type": "random",
    }

    prompt = f"""
# Role: 短视频爆款选题策划

## 目标
围绕指定的「画面形态」与「内容体裁」，产出 {count} 套可以直接开拍的短视频选题方案。

## 画面形态
{style["label"]}：{style["description"]}
素材关键词要求：{style["keyword_style"]}

## 内容体裁
{genre["label"]}：{genre["description"]}
选题要求：{genre["topic_guide"]}

## 硬性约束
1. 只输出一个合法的 JSON 数组，不要 markdown、不要代码块、不要任何解释文字。
2. 数组长度必须正好是 {count}。
3. 每个元素必须包含且只包含这些键：subject、title、hook、audience、why、outline、keywords、emotion、voice_hint、aspect、paragraph_number、clip_duration、bgm_type。
4. subject：一句话主题，不超过 {MAX_SUBJECT_LENGTH} 字，必须包含具体的人、事或冲突，不能是空泛口号。它会直接作为视频主题使用。
5. title：方案标题，不超过 {MAX_TITLE_LENGTH} 字，用于列表展示。
6. hook：前 3 秒钩子，一句话，制造悬念或反差。
7. audience：目标人群，不超过 {MAX_AUDIENCE_LENGTH} 字。
8. why：这套方案为什么可能爆，不超过 {MAX_REASON_LENGTH} 字，必须指出具体的情绪触发点或平台传播机制，不要写「容易火」这种废话。
9. outline：3 到 {MAX_OUTLINE_ITEMS} 条字符串，按时间顺序描述内容结构。
10. keywords：4 到 {MAX_KEYWORD_COUNT} 条素材检索关键词，每条不超过 {MAX_KEYWORD_LENGTH} 字，必须是具体的可视画面名词，不要抽象词，不要出现「视频」「素材」「画面」这类词。
11. emotion：从 {"/".join(_EMOTION_OPTIONS)} 中选一个。
12. voice_hint：音色与语速建议，一句话。
13. aspect：从 "9:16" 与 "16:9" 中选一个，默认 "9:16"。
14. paragraph_number：{llm.MIN_SCRIPT_PARAGRAPH_NUMBER} 到 {llm.MAX_SCRIPT_PARAGRAPH_NUMBER} 的整数，建议的文案段数。
15. clip_duration：2 到 10 的整数，建议的单段素材时长（秒）。
16. bgm_type：从 "random" 与 "" 中选一个。

## 输出示例
[{json.dumps(example, ensure_ascii=False)}]

## 质量要求
- {count} 套方案之间必须在选题角度上明显不同，不要只换措辞。
- 每套方案都要能被独立拍成一条完整短视频，不依赖上下文。
- 不要编造具体的人名、机构名或数据。
{direction_block}""".strip()

    return prompt


def build_genre_script_prompt(
    genre_id: str, visual_style_id: str = "", direction: str = ""
) -> str:
    """把体裁预设翻译成 video_script_prompt。

    这段文本会随任务一起提交，由任务流水线在生成文案时使用，因此必须自洽：
    只描述写作规则，不引用界面状态。
    """
    genre = get_genre(genre_id)
    parts = []
    if genre["script_prompt"]:
        parts.append(genre["script_prompt"])
    if direction:
        parts.append(f"补充方向：{direction}")
    return "\n".join(parts).strip()[: llm.MAX_SCRIPT_PROMPT_LENGTH]


# ---------------------------------------------------------------------------
# 解析与降级
# ---------------------------------------------------------------------------
def _clamp_text(value, max_length: int) -> str:
    text = str(value if value is not None else "").strip()
    text = re.sub(r"\s+", " ", text)
    return text[:max_length]


def _normalize_outline(value) -> List[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\n;；]|^\s*\d+[.、)]", value)
    elif isinstance(value, (list, tuple)):
        raw_items = list(value)
    else:
        raw_items = []

    items: List[str] = []
    for raw in raw_items:
        item = _clamp_text(raw, MAX_OUTLINE_ITEM_LENGTH)
        if item:
            items.append(item)
        if len(items) >= MAX_OUTLINE_ITEMS:
            break
    return items


def _normalize_keywords(value) -> List[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[,，、;；\s]+", value)
    elif isinstance(value, (list, tuple)):
        raw_items = list(value)
    else:
        raw_items = []

    keywords: List[str] = []
    seen = set()
    for raw in raw_items:
        keyword = _clamp_text(raw, MAX_KEYWORD_LENGTH)
        if not keyword:
            continue
        # 抽象词会让素材库返回无关片段，直接丢掉比留给下游过滤更省成本。
        if keyword.lower() in _KEYWORD_BLACKLIST:
            continue
        if keyword in seen:
            continue
        seen.add(keyword)
        keywords.append(keyword)
        if len(keywords) >= MAX_KEYWORD_COUNT:
            break
    return keywords


def _normalize_aspect(value, fallback: str) -> str:
    candidate = _clamp_text(value, 8)
    valid = {item.value for item in VideoAspect}
    return candidate if candidate in valid else fallback


def _normalize_int(value, minimum: int, maximum: int, fallback: int) -> int:
    try:
        number = int(float(value))
    except (TypeError, ValueError):
        return fallback
    return max(minimum, min(number, maximum))


def _normalize_bgm_type(value, fallback: str) -> str:
    candidate = str(value if value is not None else "").strip().lower()
    if candidate in ("none", "no", "off", "false"):
        return ""
    if candidate in _BGM_TYPE_OPTIONS:
        return candidate
    return fallback


def _normalize_candidate(raw, style: Dict[str, Any], genre: Dict[str, Any]) -> Dict[str, Any]:
    """把模型返回的单个方案规范化成固定结构。

    所有字段都会被限长、限范围，并补齐缺失项；下游可以假设结构完整，
    不需要再做防御性判断。
    """
    if not isinstance(raw, dict):
        raise ValueError("topic candidate is not a JSON object")

    subject = _clamp_text(raw.get("subject"), MAX_SUBJECT_LENGTH)
    title = _clamp_text(raw.get("title"), MAX_TITLE_LENGTH)
    if not subject and not title:
        raise ValueError("topic candidate is missing both subject and title")
    if not subject:
        subject = title
    if not title:
        title = subject[:MAX_TITLE_LENGTH]

    keywords = _normalize_keywords(raw.get("keywords"))

    return {
        "subject": subject,
        "title": title,
        "hook": _clamp_text(raw.get("hook"), MAX_HOOK_LENGTH),
        "audience": _clamp_text(raw.get("audience"), MAX_AUDIENCE_LENGTH),
        "why": _clamp_text(raw.get("why"), MAX_REASON_LENGTH),
        "outline": _normalize_outline(raw.get("outline")),
        "keywords": keywords,
        "emotion": _clamp_text(raw.get("emotion"), 12) or "共鸣",
        "voice_hint": _clamp_text(raw.get("voice_hint"), 40) or genre["voice_hint"],
        "aspect": _normalize_aspect(raw.get("aspect"), style["video_aspect"]),
        "paragraph_number": _normalize_int(
            raw.get("paragraph_number"),
            llm.MIN_SCRIPT_PARAGRAPH_NUMBER,
            llm.MAX_SCRIPT_PARAGRAPH_NUMBER,
            genre["paragraph_number"],
        ),
        "clip_duration": _normalize_int(raw.get("clip_duration"), 2, 10, style["clip_duration"]),
        "bgm_type": _normalize_bgm_type(raw.get("bgm_type"), genre["bgm_type"]),
    }


def parse_topic_candidates(
    response: str, visual_style_id: str, genre_id: str
) -> List[Dict[str, Any]]:
    """解析模型返回的方案数组。

    模型可能返回裸数组、包在对象里的数组，或者带 markdown fence 的文本，
    这里统一兼容；单个方案解析失败会被跳过而不是整体失败。
    """
    style = get_visual_style(visual_style_id)
    genre = get_genre(genre_id)

    text = llm._strip_code_fence(response)

    data = None
    try:
        data = json.loads(text)
    except Exception:
        # 部分模型会在 JSON 外层补一段说明文字，退化为提取第一个完整数组。
        for opening in ("[", "{"):
            try:
                data = llm._extract_embedded_json(text, opening)
                break
            except Exception:
                continue

    if isinstance(data, dict):
        # 兼容 {"candidates": [...]} / {"topics": [...]} 这类包装结构。
        for key in ("candidates", "topics", "plans", "data", "items", "list"):
            if isinstance(data.get(key), list):
                data = data[key]
                break

    if not isinstance(data, list):
        raise ValueError("topic candidates response is not a JSON array")

    candidates: List[Dict[str, Any]] = []
    for raw in data:
        try:
            candidates.append(_normalize_candidate(raw, style, genre))
        except Exception as exc:
            logger.warning(f"skip invalid topic candidate: {exc}")

    if not candidates:
        raise ValueError("topic candidates response contains no usable entry")

    return candidates


def _fallback_topic_candidates(
    visual_style_id: str,
    genre_id: str,
    count: int,
    direction: str,
) -> List[Dict[str, Any]]:
    """模型不可用时的兜底方案。

    返回的每一项都会带上 FALLBACK_FLAG，界面据此提示用户这是占位内容。
    只给结构完整的骨架而不假装是模型产出，是为了避免用户直接开跑一条
    没有任何选题依据的视频。
    """
    style = get_visual_style(visual_style_id)
    genre = get_genre(genre_id)
    count = normalize_candidate_count(count)
    direction = normalize_direction(direction)

    templates = [
        ("一个被忽视的日常细节，其实决定了结果", "反常识切入，靠认知落差留住人"),
        ("当事人的一次关键选择，改变了他后面很多年", "靠因果张力驱动完播"),
        ("所有人都在做的事，可能从一开始就是错的", "挑战共识，容易引发评论争论"),
        ("一个具体的瞬间，让两个人再也回不到从前", "情绪浓度高，适合做共鸣传播"),
        ("一件小事被反复放大之后，变成了不可收拾的局面", "冲突逐步升级，节奏好控制"),
        ("被忽略的第三个人，才是整件事的关键", "视角反转，制造二次观看动机"),
    ]

    candidates: List[Dict[str, Any]] = []
    for index in range(count):
        template, reason = templates[index % len(templates)]
        subject = f"{template}" if not direction else f"{direction}：{template}"
        entry = _normalize_candidate(
            {
                "subject": subject,
                "title": template[:MAX_TITLE_LENGTH],
                "hook": "先说结论：你可能一直都理解错了。",
                "audience": "泛内容受众",
                "why": f"{reason}（模型不可用，此为占位方案，请手动改写后再生成）",
                "outline": ["抛出反常识结论", "给出两到三个具体细节", "结尾留悬念"],
                "keywords": ["夜晚街道", "窗边剪影", "旧书桌", "雨滴特写"],
                "emotion": "悬念",
                "voice_hint": genre["voice_hint"],
                "aspect": style["video_aspect"],
                "paragraph_number": genre["paragraph_number"],
                "clip_duration": style["clip_duration"],
                "bgm_type": genre["bgm_type"],
            },
            style,
            genre,
        )
        entry[FALLBACK_FLAG] = True
        candidates.append(entry)
    return candidates


def is_fallback_candidate(candidate: Dict[str, Any]) -> bool:
    """判断某套方案是否来自降级占位，供界面给出明确提示。"""
    return bool(candidate.get(FALLBACK_FLAG))


def generate_topic_candidates(
    visual_style_id: str,
    genre_id: str,
    count: int = DEFAULT_CANDIDATE_COUNT,
    direction: str = "",
    app_config=None,
) -> List[Dict[str, Any]]:
    """生成选题方案。模型失败或输出不可解析时返回占位方案而不是抛异常。"""
    style = get_visual_style(visual_style_id)
    genre = get_genre(genre_id)
    count = normalize_candidate_count(count)
    direction = normalize_direction(direction)

    prompt = build_topic_candidates_prompt(
        visual_style_id=style["id"],
        genre_id=genre["id"],
        count=count,
        direction=direction,
    )
    logger.info(
        "generating topic candidates: "
        f"visual_style={style['id']}, genre={genre['id']}, count={count}, "
        f"has_direction={bool(direction)}"
    )

    for attempt in range(2):
        try:
            if app_config is None:
                response = llm._generate_response(prompt=prompt)
            else:
                response = llm._generate_response(prompt=prompt, app_config=app_config)
            if isinstance(response, str) and response.startswith("Error: "):
                logger.error(f"failed to generate topic candidates: {response}")
                break
            candidates = parse_topic_candidates(response, style["id"], genre["id"])
            logger.success(f"completed: {len(candidates)} topic candidates")
            return candidates[:count]
        except Exception as exc:
            logger.warning(f"failed to parse topic candidates: {exc}")
        if attempt == 0:
            logger.warning("failed to generate topic candidates, trying again...")

    logger.warning("falling back to placeholder topic candidates")
    return _fallback_topic_candidates(style["id"], genre["id"], count, direction)


# ---------------------------------------------------------------------------
# 方案 -> 生成参数
# ---------------------------------------------------------------------------
def build_form_params(
    candidate: Dict[str, Any],
    visual_style_id: str,
    genre_id: str,
    direction: str = "",
    voice_name: str = "",
) -> Dict[str, Any]:
    """把选中的方案翻译成可直接写回页面控件的生成参数。

    返回结构刻意与历史任务恢复使用的参数模型保持一致，这样 WebUI 可以直接复用
    同一个填充实现，不需要为选题工坊维护第二套控件映射。

    voice_name 必须由调用方传入当前音色：填充实现会在缺少该字段时退回「无配音」，
    而选题工坊的目标恰恰是「画面 + 文字 + 配音」，不能把用户配好的音色关掉。
    """
    style = get_visual_style(visual_style_id)
    genre = get_genre(genre_id)
    direction = normalize_direction(direction)

    keywords = candidate.get("keywords") or []
    if isinstance(keywords, str):
        keywords = _normalize_keywords(keywords)

    return {
        "video_subject": candidate.get("subject", ""),
        # 文案留空，让任务流水线按下面的写作要求现生成，避免把方案标题当成正文。
        "video_script": "",
        "video_terms": ", ".join(keywords),
        "video_language": "zh-CN",
        "paragraph_number": candidate.get("paragraph_number", genre["paragraph_number"]),
        "video_script_prompt": build_genre_script_prompt(
            genre["id"], style["id"], direction
        ),
        "video_source": style["video_source"],
        "video_aspect": candidate.get("aspect", style["video_aspect"]),
        "video_concat_mode": style["video_concat_mode"],
        "video_fit_mode": style["video_fit_mode"],
        "video_clip_duration": candidate.get("clip_duration", style["clip_duration"]),
        "video_count": 1,
        "match_materials_to_script": False,
        "voice_name": voice_name,
        "voice_rate": genre["voice_rate"],
        "bgm_type": candidate.get("bgm_type", genre["bgm_type"]),
        "bgm_volume": 0.2,
        "subtitle_enabled": True,
        "subtitle_position": genre["subtitle_position"],
        "font_size": genre["font_size"],
    }


if __name__ == "__main__":
    result = generate_topic_candidates(
        visual_style_id=DEFAULT_VISUAL_STYLE_ID,
        genre_id="philosophy",
        count=2,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
