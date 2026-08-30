"""TwelveLabs 可选集成：按语义重排素材关键词，并对成片做画面理解。

封装两个 TwelveLabs 模型，帮助更好利用已下载的库存/B-roll 素材：

  * Marengo（多模态向量，512 维）：按视频主题对 LLM 生成的搜索词做语义重排，
    时间轴不够时优先保留最贴题的片段，而不是 LLM 碰巧排在前面的词。
  * Pegasus（视频理解）：根据公开 URL 描述或质检片段，确认下载内容与文案相符。

未配置 ``twelvelabs_api_keys`` 时，本模块公开函数均为空操作，行为与未集成时一致。
SDK 延迟导入，只有真正启用该功能时才需要安装依赖。
"""

import math
from functools import lru_cache
from typing import List, Optional

from loguru import logger

from app.config import config
from app.services import material

DEFAULT_MARENGO_MODEL = "marengo3.0"
DEFAULT_PEGASUS_MODEL = "pegasus1.5"
# Pegasus 要求 max_tokens 在 [512, 98304]；一行质检用 512 足够。
_PEGASUS_MIN_MAX_TOKENS = 512


def is_enabled() -> bool:
    """至少配置了一个 TwelveLabs API Key 时返回 True。"""
    keys = config.app.get("twelvelabs_api_keys")
    return bool(keys)


def _client():
    # 延迟导入，并复用 material.py 的 Key 轮询，与其它供应商保持一致。
    from twelvelabs import TwelveLabs

    api_key = material.get_api_key("twelvelabs_api_keys")
    return TwelveLabs(api_key=api_key)


def _cosine(a: List[float], b: List[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def embed_text(text: str, model: Optional[str] = None) -> Optional[List[float]]:
    """
    Return a 512-dim Marengo text embedding, or None on failure / when disabled.

    Cached so repeated terms across a session don't re-hit the API.
    """
    if not is_enabled() or not text or not text.strip():
        return None
    model = model or config.app.get("twelvelabs_marengo_model", DEFAULT_MARENGO_MODEL)
    try:
        # lru_cache only memoizes successful returns; a raised exception is not
        # cached, so a transient API error never poisons the cache.
        return _embed_text_cached(text.strip(), model)
    except Exception as e:  # noqa: BLE001 - never break the pipeline on TL errors
        logger.warning(f"TwelveLabs embed_text failed, skipping rerank: {e}")
        return None


@lru_cache(maxsize=512)
def _embed_text_cached(text: str, model: str) -> List[float]:
    client = _client()
    resp = client.embed.create(model_name=model, text=text)
    # SDK aliases the raw JSON 'float' vector key to `float_`.
    return list(resp.text_embedding.segments[0].float_)


def rerank_terms_by_subject(
    video_subject: str,
    search_terms: List[str],
    model: Optional[str] = None,
) -> List[str]:
    """
    Reorder `search_terms` so the terms most semantically relevant to
    `video_subject` come first (Marengo cosine similarity).

    Opt-in: only runs when TwelveLabs is enabled AND
    `twelvelabs_rerank_terms` is truthy. Falls back to the original order on
    any failure, so it can never make the pipeline worse.
    """
    if not is_enabled() or not config.app.get("twelvelabs_rerank_terms"):
        return search_terms
    if not video_subject or len(search_terms) < 2:
        return search_terms

    subject_vec = embed_text(video_subject, model)
    if subject_vec is None:
        return search_terms

    scored = []
    for term in search_terms:
        vec = embed_text(term, model)
        if vec is None:
            # 任一关键词无法向量化时不冒险做部分重排，直接返回原文顺序。
            return search_terms
        scored.append((term, _cosine(subject_vec, vec)))

    ranked = [term for term, _ in sorted(scored, key=lambda x: x[1], reverse=True)]
    logger.info(
        f"TwelveLabs Marengo reranked {len(ranked)} search terms by relevance "
        f"to subject '{video_subject}': {ranked}"
    )
    return ranked


def analyze_clip(
    video_url: str,
    prompt: str = "Describe what happens in this video in one sentence.",
    model: Optional[str] = None,
    max_tokens: int = _PEGASUS_MIN_MAX_TOKENS,
) -> Optional[str]:
    """用 Pegasus 根据公开 URL 描述或质检片段，失败或未启用时返回 None。

    TwelveLabs 约束：Pegasus 需要可公网访问的 URL（或已上传资源），不能是
    本地路径；分析窗口至少 4 秒；该模型的 max_tokens 必须 >= 512。
    """
    if not is_enabled() or not video_url:
        return None
    model = model or config.app.get("twelvelabs_pegasus_model", DEFAULT_PEGASUS_MODEL)
    try:
        from twelvelabs.types import VideoContext_Url

        client = _client()
        resp = client.analyze(
            model_name=model,
            video=VideoContext_Url(url=video_url),
            prompt=prompt,
            max_tokens=max(max_tokens, _PEGASUS_MIN_MAX_TOKENS),
        )
        return resp.data
    except Exception as e:  # noqa: BLE001
        logger.warning(f"TwelveLabs analyze_clip failed: {e}")
        return None
