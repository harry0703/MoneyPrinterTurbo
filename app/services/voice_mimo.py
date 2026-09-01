"""Xiaomi MiMo TTS provider."""

import base64
import io
from typing import Union

from edge_tts import SubMaker
from loguru import logger
from openai import OpenAI

from app.config import config
from app.utils import utils
from app.services.voice_common import (
    _configure_pydub_ffmpeg,
    ensure_file_path_exists,
    ensure_legacy_submaker_fields,
    populate_legacy_submaker_with_full_text,
)

_MIMO_DEFAULT_BASE_URL = "https://api.xiaomimimo.com/v1"
_MIMO_DEFAULT_TTS_MODEL = "mimo-v2.5-tts"


def get_mimo_voices() -> list[str]:
    """
    获取 Xiaomi MiMo V2.5 TTS 的预置音色列表。

    当前只接入官方文档里的 `mimo-v2.5-tts` 预置音色模式。音色设计
    `mimo-v2.5-tts-voicedesign` 和音色复刻 `mimo-v2.5-tts-voiceclone`
    需要额外的输入表单和素材上传流程，先不混入普通 TTS 下拉框，避免
    用户误以为选择一个 voice id 就能完成所有高级能力。
    """
    voices_with_gender = [
        ("mimo_default", "Female"),
        ("冰糖", "Female"),
        ("茉莉", "Female"),
        ("苏打", "Male"),
        ("白桦", "Male"),
        ("Mia", "Female"),
        ("Chloe", "Female"),
        ("Milo", "Male"),
        ("Dean", "Male"),
    ]

    return [f"mimo:{voice}-{gender}" for voice, gender in voices_with_gender]


def is_mimo_voice(voice_name: str):
    """检查是否是 Xiaomi MiMo TTS 的声音"""
    return voice_name.startswith("mimo:")


def mimo_tts(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
) -> Union[SubMaker, None]:
    """
    使用 Xiaomi MiMo V2.5 TTS 生成语音。

    官方接口兼容 OpenAI Chat Completions，但 TTS 有两个关键差异：
    1. 待合成文本必须放在 `assistant` 消息里；
    2. 音频以 `message.audio.data` 的 base64 字符串返回。

    MiMo 当前没有返回逐词时间轴，因此这里复用项目已有的 legacy
    SubMaker 兜底方案：根据最终音频时长和脚本文本断句生成字幕时间轴。
    """
    from pydub import AudioSegment

    text = (text or "").strip()
    if not text:
        logger.error("MiMo TTS text is empty")
        return None

    api_key = config.app.get("mimo_api_key", "")
    if not api_key:
        logger.error("MiMo API key is not set")
        return None

    base_url = config.app.get("mimo_base_url", "") or _MIMO_DEFAULT_BASE_URL
    model_name = config.app.get("mimo_tts_model_name", "") or _MIMO_DEFAULT_TTS_MODEL
    style_prompt = config.app.get(
        "mimo_tts_style_prompt",
        "请用自然、清晰、适合短视频旁白的语气朗读。",
    )

    _configure_pydub_ffmpeg(AudioSegment)

    for i in range(3):
        try:
            logger.info(
                f"start mimo tts, model: {model_name}, voice: {voice_name}, try: {i + 1}"
            )
            ensure_file_path_exists(voice_file)

            client = OpenAI(api_key=api_key, base_url=base_url)
            completion = client.chat.completions.create(
                model=model_name,
                messages=[
                    {"role": "user", "content": style_prompt},
                    {"role": "assistant", "content": text},
                ],
                audio={
                    "format": "wav",
                    "voice": voice_name,
                },
            )

            if not completion or not getattr(completion, "choices", None):
                raise ValueError("MiMo TTS returned empty response")

            message = completion.choices[0].message
            audio = getattr(message, "audio", None)
            audio_data = None
            if isinstance(audio, dict):
                audio_data = audio.get("data")
            elif audio is not None:
                audio_data = getattr(audio, "data", None)

            if not audio_data:
                raise ValueError("MiMo TTS returned empty audio data")

            audio_bytes = base64.b64decode(audio_data)
            audio_segment = AudioSegment.from_file(io.BytesIO(audio_bytes), format="wav")

            output_format = utils.parse_extension(voice_file) or "mp3"
            if output_format == "wav":
                with open(voice_file, "wb") as f:
                    f.write(audio_bytes)
            else:
                audio_segment.export(voice_file, format=output_format)

            audio_duration = len(audio_segment) / 1000.0
            sub_maker = ensure_legacy_submaker_fields(SubMaker())
            logger.success(f"mimo tts succeeded: {voice_file}")
            logger.debug(
                "mimo subtitle timeline generated, "
                f"duration: {audio_duration:.3f}s, output_format: {output_format}"
            )
            return populate_legacy_submaker_with_full_text(
                sub_maker=sub_maker,
                text=text,
                audio_duration_seconds=audio_duration,
            )
        except Exception as e:
            logger.error(f"mimo tts failed: {str(e)}")

    return None
