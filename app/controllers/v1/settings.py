import os
from uuid import uuid4
from fastapi import Request
from fastapi.responses import FileResponse
from loguru import logger

from app.config import config
from app.controllers.v1.base import new_router
from app.models.exception import HttpException
from app.services import voice
from app.utils import utils

router = new_router()


@router.get("/voices", summary="Get voice list based on TTS server")
def get_voices(request: Request, tts_server: str = "azure-tts-v1", force_refresh: bool = False):
    """
    Get voice list based on TTS server selection.

    Args:
        tts_server: TTS server type (azure-tts-v1, azure-tts-v2, siliconflow, gemini-tts, coze-tts)
        force_refresh: Force refresh voice cache (for Coze TTS)
    """
    try:
        if tts_server == "siliconflow":
            voices = voice.get_siliconflow_voices()
        elif tts_server == "gemini-tts":
            voices = voice.get_gemini_voices()
        elif tts_server == "coze-tts":
            voices = voice.get_coze_voices(force_refresh=force_refresh)
        else:
            all_voices = voice.get_all_azure_voices(filter_locals=None)
            if tts_server == "azure-tts-v2":
                voices = [v for v in all_voices if "V2" in v]
            else:
                voices = [v for v in all_voices if "V2" not in v]

        return utils.get_response(200, {"voices": voices})
    except Exception as e:
        logger.error(f"Failed to get voices: {str(e)}")
        return utils.get_response(500, {"error": str(e)})


@router.get("/config", summary="Get configuration")
def get_config(request: Request):
    """Get current configuration for UI settings."""
    try:
        cfg = {
            "ui": config.ui,
            "app": {
                "llm_provider": config.app.get("llm_provider", "openai"),
                "video_source": config.app.get("video_source", "pexels"),
                "hide_config": config.app.get("hide_config", False),
                "use_gpu": config.app.get("use_gpu", False),
                "pexels_api_keys": config.app.get("pexels_api_keys", []),
                "pixabay_api_keys": config.app.get("pixabay_api_keys", []),
                "openai_api_key": config.app.get("openai_api_key", ""),
                "openai_base_url": config.app.get("openai_base_url", ""),
                "openai_model_name": config.app.get("openai_model_name", "gpt-3.5-turbo"),
                "moonshot_api_key": config.app.get("moonshot_api_key", ""),
                "moonshot_base_url": config.app.get("moonshot_base_url", ""),
                "moonshot_model_name": config.app.get("moonshot_model_name", ""),
                "deepseek_api_key": config.app.get("deepseek_api_key", ""),
                "deepseek_base_url": config.app.get("deepseek_base_url", ""),
                "deepseek_model_name": config.app.get("deepseek_model_name", ""),
            },
            "azure": {
                "speech_region": config.azure.get("speech_region", ""),
                "speech_key": config.azure.get("speech_key", ""),
            },
            "siliconflow": {
                "api_key": config.siliconflow.get("api_key", ""),
            },
            "coze": {
                "api_key": config.coze.get("api_key", ""),
            },
            "whisper": {
                "device": config.whisper.get("device", "CPU"),
            }
        }
        return utils.get_response(200, cfg)
    except Exception as e:
        logger.error(f"Failed to get config: {str(e)}")
        return utils.get_response(500, {"error": str(e)})


@router.put("/config", summary="Update configuration")
def update_config(request: Request, cfg: dict):
    """
    Update configuration.

    Args:
        cfg: Configuration dictionary with keys: ui, azure, siliconflow, coze
    """
    try:
        if "ui" in cfg:
            for key, value in cfg["ui"].items():
                config.ui[key] = value

        if "azure" in cfg:
            for key, value in cfg["azure"].items():
                config.azure[key] = value

        if "siliconflow" in cfg:
            for key, value in cfg["siliconflow"].items():
                config.siliconflow[key] = value

        if "coze" in cfg:
            for key, value in cfg["coze"].items():
                config.coze[key] = value

        config.save_config()
        return utils.get_response(200, {"message": "Config saved successfully"})
    except Exception as e:
        logger.error(f"Failed to update config: {str(e)}")
        return utils.get_response(500, {"error": str(e)})


@router.post("/audio/preview", summary="Preview audio (play voice)")
def preview_audio(request: Request, params: dict):
    """
    Generate and return audio preview.

    Args:
        params: Dictionary containing:
            - text: Text to synthesize
            - voice_name: Voice identifier
            - voice_rate: Voice speed (0.5-2.0)
            - voice_volume: Voice volume (0.1-2.0)
            - voice_emotion: Voice emotion (for Coze TTS)
    """
    try:
        text = params.get("text", "")
        voice_name = params.get("voice_name", "")
        voice_rate = float(params.get("voice_rate", 1.0))
        voice_volume = float(params.get("voice_volume", 1.0))
        voice_emotion = params.get("voice_emotion", "")

        if not text or not voice_name:
            return utils.get_response(400, {"error": "Text and voice_name are required"})

        temp_dir = utils.storage_dir("temp", create=True)
        audio_file = os.path.join(temp_dir, f"tmp-voice-{str(uuid4())}.mp3")

        sub_maker = voice.tts(
            text=text,
            voice_name=voice_name,
            voice_rate=voice_rate,
            voice_file=audio_file,
            voice_volume=voice_volume,
            emotion=voice_emotion,
            is_preview=True,
        )

        if not sub_maker and not os.path.exists(audio_file):
            text = "This is an example voice. If you hear this, the voice synthesis failed with the original content."
            sub_maker = voice.tts(
                text=text,
                voice_name=voice_name,
                voice_rate=voice_rate,
                voice_file=audio_file,
                voice_volume=voice_volume,
                emotion=voice_emotion,
                is_preview=True,
            )

        if os.path.exists(audio_file):
            return FileResponse(audio_file, media_type="audio/mp3", filename="preview.mp3")
        else:
            return utils.get_response(500, {"error": "Failed to generate audio"})
    except Exception as e:
        logger.error(f"Failed to preview audio: {str(e)}")
        return utils.get_response(500, {"error": str(e)})