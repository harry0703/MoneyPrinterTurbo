"""Google Gemini TTS provider."""

import base64
import io
from typing import Union

from edge_tts import SubMaker
from loguru import logger

from app.config import config
from app.services.voice_common import (
    _configure_pydub_ffmpeg,
    ensure_file_path_exists,
    ensure_legacy_submaker_fields,
    populate_legacy_submaker_with_full_text,
)

GEMINI_TTS_VOICES = (
    ("Zephyr", "Bright"),
    ("Puck", "Upbeat"),
    ("Charon", "Informative"),
    ("Kore", "Firm"),
    ("Fenrir", "Excitable"),
    ("Leda", "Youthful"),
    ("Orus", "Firm"),
    ("Aoede", "Breezy"),
    ("Callirrhoe", "Easy-going"),
    ("Autonoe", "Bright"),
    ("Enceladus", "Breathy"),
    ("Iapetus", "Clear"),
    ("Umbriel", "Easy-going"),
    ("Algieba", "Smooth"),
    ("Despina", "Smooth"),
    ("Erinome", "Clear"),
    ("Algenib", "Gravelly"),
    ("Rasalgethi", "Informative"),
    ("Laomedeia", "Upbeat"),
    ("Achernar", "Soft"),
    ("Alnilam", "Firm"),
    ("Schedar", "Even"),
    ("Gacrux", "Mature"),
    ("Pulcherrima", "Forward"),
    ("Achird", "Friendly"),
    ("Zubenelgenubi", "Casual"),
    ("Vindemiatrix", "Gentle"),
    ("Sadachbia", "Lively"),
    ("Sadaltager", "Knowledgeable"),
    ("Sulafat", "Warm"),
)


def get_gemini_voices() -> list[str]:
    """
    获取 Gemini TTS 官方预置音色列表。

    Google 没有为这些音色发布性别元数据，因此下拉框使用官方风格描述，
    避免把推测的性别写进持久化 voice id。音色目录来源：
    https://ai.google.dev/gemini-api/docs/speech-generation#voice-options

    Returns:
        声音列表，格式为 ["gemini:Zephyr-Bright", "gemini:Puck-Upbeat", ...]
    """
    return [f"gemini:{voice}-{style}" for voice, style in GEMINI_TTS_VOICES]


def is_gemini_voice(voice_name: str):
    """检查是否是Gemini TTS的声音"""
    return voice_name.startswith("gemini:")


def parse_gemini_voice_name(voice_name: str | None) -> str:
    """从新旧 Gemini 下拉框值中提取 Google API 使用的预置音色名称。"""
    if not is_gemini_voice(voice_name or ""):
        return ""
    return (voice_name or "").split(":", 1)[1].split("-", 1)[0].strip()


def gemini_tts(
    text: str,
    voice_name: str,
    voice_rate: float,
    voice_file: str,
    voice_volume: float = 1.0,
) -> Union[SubMaker, None]:
    """
    使用Google Gemini TTS生成语音

    Args:
        text: 要转换的文本
        voice_name: 语音名称，如 "Zephyr", "Puck" 等
        voice_rate: 语音速率（当前未使用）
        voice_file: 输出音频文件路径
        voice_volume: 音频音量（当前未使用）

    Returns:
        SubMaker对象或None
    """
    from pydub import AudioSegment
    from google import genai
    from google.genai import types
    _configure_pydub_ffmpeg(AudioSegment)

    try:
        api_key = config.app.get("gemini_api_key", "")
        if not api_key:
            logger.error("Gemini API key is not set")
            return None

        logger.info(f"start, voice name: {voice_name}, try: 1")

        generation_config = types.GenerateContentConfig(
            response_modalities=["AUDIO"],
            speech_config=types.SpeechConfig(
                voice_config=types.VoiceConfig(
                    prebuilt_voice_config=types.PrebuiltVoiceConfig(
                        voice_name=voice_name
                    )
                )
            ),
        )

        # google-genai 使用统一 Client 调用文本和 TTS 模型。上下文管理器确保
        # 请求结束后释放 HTTP 连接，同时保留原有 PCM 转码和字幕时间轴逻辑。
        with genai.Client(api_key=api_key) as client:
            response = client.models.generate_content(
                model="gemini-2.5-flash-preview-tts",
                contents=text,
                config=generation_config,
            )

        # 检查响应
        if not response.candidates or not response.candidates[0].content:
            logger.error("No audio content received from Gemini TTS")
            return None

        # 获取音频数据
        audio_data = None
        for part in response.candidates[0].content.parts:
            if hasattr(part, 'inline_data') and part.inline_data:
                audio_data = part.inline_data.data
                break

        if not audio_data:
            logger.error("No audio data found in response")
            return None

        # 音频数据已经是原始字节，不需要base64解码
        if isinstance(audio_data, str):
            # 如果是字符串，则需要base64解码
            audio_bytes = base64.b64decode(audio_data)
        else:
            # 如果已经是字节，直接使用
            audio_bytes = audio_data

        # 尝试不同的音频格式 - Gemini可能返回不同的格式
        audio_segment = None

        # Gemini返回Linear PCM格式，按照文档参数解析
        try:
            audio_segment = AudioSegment.from_file(
                io.BytesIO(audio_bytes),
                format="raw",
                frame_rate=24000,  # Gemini TTS默认采样率
                channels=1,        # 单声道
                sample_width=2     # 16-bit
            )
        except Exception as e:
            logger.error(f"Failed to load PCM audio: {e}")
            return None

        # API、CLI 或测试可以直接把尚不存在的嵌套目录作为输出位置。这里在
        # 真正写文件前统一创建父目录，避免一次成功的 Gemini 请求最后因为
        # 本地路径不存在而丢失结果，也让该 provider 与其他 TTS 实现行为一致。
        ensure_file_path_exists(voice_file)

        # pydub 会返回打开的输出文件对象。批量生成时若不主动关闭，文件描述符
        # 会持续累积，并在 Windows 上增加后续覆盖或删除音频文件失败的概率。
        exported_audio = audio_segment.export(voice_file, format="mp3")
        exported_audio.close()

        logger.info(f"completed, output file: {voice_file}")

        # Gemini 拿不到 edge_tts 那种逐词边界事件，因此这里退回到
        # 项目原有的 `subs/offset` 兼容结构，至少保证后续字幕与时长
        # 计算链路可继续工作。
        sub_maker = ensure_legacy_submaker_fields(SubMaker())
        audio_duration = len(audio_segment) / 1000.0  # 转换为秒
        return populate_legacy_submaker_with_full_text(
            sub_maker=sub_maker,
            text=text,
            audio_duration_seconds=audio_duration,
        )

    except ImportError as e:
        logger.error(f"Missing required package for Gemini TTS: {str(e)}. Please install: pip install pydub")
        return None
    except Exception as e:
        logger.error(f"Gemini TTS failed, error: {str(e)}")
        return None
