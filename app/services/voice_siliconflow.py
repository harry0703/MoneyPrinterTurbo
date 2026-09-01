"""SiliconFlow TTS provider."""

from typing import Union

import requests
from edge_tts import SubMaker
from loguru import logger
from moviepy.audio.io.AudioFileClip import AudioFileClip

from app.config import config
from app.services.voice_common import (
    ensure_legacy_submaker_fields,
    populate_legacy_submaker_with_full_text,
)


def get_siliconflow_voices() -> list[str]:
    """
    获取硅基流动的声音列表

    Returns:
        声音列表，格式为 ["siliconflow:FunAudioLLM/CosyVoice2-0.5B:alex", ...]
    """
    # 硅基流动的声音列表和对应的性别（用于显示）
    voices_with_gender = [
        ("FunAudioLLM/CosyVoice2-0.5B", "alex", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "anna", "Female"),
        ("FunAudioLLM/CosyVoice2-0.5B", "bella", "Female"),
        ("FunAudioLLM/CosyVoice2-0.5B", "benjamin", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "charles", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "claire", "Female"),
        ("FunAudioLLM/CosyVoice2-0.5B", "david", "Male"),
        ("FunAudioLLM/CosyVoice2-0.5B", "diana", "Female"),
    ]

    # 添加siliconflow:前缀，并格式化为显示名称
    return [
        f"siliconflow:{model}:{voice}-{gender}"
        for model, voice, gender in voices_with_gender
    ]


def is_siliconflow_voice(voice_name: str):
    """检查是否是硅基流动的声音"""
    return voice_name.startswith("siliconflow:")


def siliconflow_tts(
    text: str,
    model: str,
    voice: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
) -> Union[SubMaker, None]:
    """
    使用硅基流动的API生成语音

    Args:
        text: 要转换为语音的文本
        model: 模型名称，如 "FunAudioLLM/CosyVoice2-0.5B"
        voice: 声音名称，如 "FunAudioLLM/CosyVoice2-0.5B:alex"
        voice_rate: 语音速度，范围[0.25, 4.0]
        voice_file: 输出的音频文件路径
        voice_volume: 语音音量，范围[0.6, 5.0]，需要转换为硅基流动的增益范围[-10, 10]

    Returns:
        SubMaker对象或None
    """
    text = text.strip()
    api_key = config.siliconflow.get("api_key", "")

    if not api_key:
        logger.error("SiliconFlow API key is not set")
        return None

    # 将voice_volume转换为硅基流动的增益范围
    # 默认voice_volume为1.0，对应gain为0
    gain = voice_volume - 1.0
    # 确保gain在[-10, 10]范围内
    gain = max(-10, min(10, gain))

    url = "https://api.siliconflow.cn/v1/audio/speech"

    payload = {
        "model": model,
        "input": text,
        "voice": voice,
        "response_format": "mp3",
        "sample_rate": 32000,
        "stream": False,
        "speed": voice_rate,
        "gain": gain,
    }

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}

    for i in range(3):  # 尝试3次
        try:
            logger.info(
                f"start siliconflow tts, model: {model}, voice: {voice}, try: {i + 1}"
            )

            response = requests.post(url, json=payload, headers=headers)

            if response.status_code == 200:
                # 保存音频文件
                with open(voice_file, "wb") as f:
                    f.write(response.content)

                sub_maker = ensure_legacy_submaker_fields(SubMaker())

                try:
                    audio_clip = AudioFileClip(voice_file)
                    try:
                        audio_duration = audio_clip.duration
                    finally:
                        audio_clip.close()
                except Exception as e:
                    logger.warning(f"Failed to read audio duration: {str(e)}")
                    audio_duration = 10.0

                logger.success(f"siliconflow tts succeeded: {voice_file}")
                return populate_legacy_submaker_with_full_text(
                    sub_maker=sub_maker,
                    text=text,
                    audio_duration_seconds=audio_duration,
                )
            else:
                logger.error(
                    f"siliconflow tts failed with status code {response.status_code}: {response.text}"
                )
        except Exception as e:
            logger.error(f"siliconflow tts failed: {str(e)}")

    return None
