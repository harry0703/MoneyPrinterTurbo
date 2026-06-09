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
        tts_server: TTS server type (azure-tts-v1, azure-tts-v2, siliconflow, gemini-tts, coze-tts, qwen-tts)
        force_refresh: Force refresh voice cache (for Coze TTS)
    """
    try:
        if tts_server == "siliconflow":
            voices = voice.get_siliconflow_voices()
        elif tts_server == "gemini-tts":
            voices = voice.get_gemini_voices()
        elif tts_server == "coze-tts":
            voices = voice.get_coze_voices(force_refresh=force_refresh)
        elif tts_server == "qwen-tts":
            voices = voice.get_qwen_voices(force_refresh=force_refresh)
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
        tts_server = config.ui.get("tts_server", "azure-tts-v1")
        voice_name = config.ui.get("voice_name", "")

        cfg = {
            "ui": {
                **config.ui,
                "tts_server": tts_server,
                "voice_name": voice_name,
                "subtitle_enabled": config.ui.get("subtitle_enabled", True),
                "subtitle_position": config.ui.get("subtitle_position", "bottom"),
                "subtitle_custom_position": config.ui.get("subtitle_custom_position", 70.0),
                "subtitle_margin": config.ui.get("subtitle_margin", 0.1),
                "subtitle_auto_fit": config.ui.get("subtitle_auto_fit", False),
                "font_name": config.ui.get("font_name", "MicrosoftYaHeiBold.ttc"),
                "text_fore_color": config.ui.get("text_fore_color", "#FFFFFF"),
                "text_background_color": config.ui.get("text_background_color", True),
                "font_size": config.ui.get("font_size", 60),
                "stroke_color": config.ui.get("stroke_color", "#000000"),
                "stroke_width": config.ui.get("stroke_width", 1.5),
                "output_bg_color": config.ui.get("output_bg_color", "black"),
            },
            "app": {
                "llm_provider": config.app.get("llm_provider", "openai"),
                "video_source": config.app.get("video_source", "pexels"),
                "video_quality": config.app.get("video_quality", "ultra"),
                "video_bitrate": config.app.get("video_bitrate", "20M"),
                "video_brightness": config.app.get("video_brightness", 1.0),
                "video_contrast": config.app.get("video_contrast", 1.0),
                "video_concat_mode": config.app.get("video_concat_mode", "sequential"),
                "video_transition_mode": config.app.get("video_transition_mode", "none"),
                "video_aspect": config.app.get("video_aspect", "landscape"),
                "video_clip_duration": config.app.get("video_clip_duration", 3),
                "video_count": config.app.get("video_count", 1),
                "silence_duration": config.app.get("silence_duration", 0.3),
                "video_style": config.app.get("video_style", "none"),
                "intro_video_bg_type": config.app.get("intro_video_bg_type", "solid"),
                "intro_video_bg_blur": config.app.get("intro_video_bg_blur", 15),
                "intro_video_bg_color": config.app.get("intro_video_bg_color", "black"),
                "host_visible": config.app.get("host_visible", True),
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
            "qwen": {
                "api_key": config.qwen.get("api_key", ""),
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
        cfg: Configuration dictionary with keys: ui, app, azure, siliconflow, coze, whisper
    """
    try:
        if "ui" in cfg:
            for key, value in cfg["ui"].items():
                config.ui[key] = value

        if "app" in cfg:
            for key, value in cfg["app"].items():
                config.app[key] = value

        if "azure" in cfg:
            for key, value in cfg["azure"].items():
                config.azure[key] = value

        if "siliconflow" in cfg:
            for key, value in cfg["siliconflow"].items():
                config.siliconflow[key] = value

        if "coze" in cfg:
            for key, value in cfg["coze"].items():
                config.coze[key] = value

        if "qwen" in cfg:
            for key, value in cfg["qwen"].items():
                config.qwen[key] = value

        if "whisper" in cfg:
            for key, value in cfg["whisper"].items():
                config.whisper[key] = value

        config.save_config()
        logger.info(f"[Update Config] Config saved successfully. ui.subtitle_enabled={config.ui.get('subtitle_enabled')}")
        return utils.get_response(200, {"message": "Config saved successfully"})
    except Exception as e:
        logger.error(f"Failed to update config: {str(e)}")
        return utils.get_response(500, {"error": str(e)})


from app.config.cloned_voices import cloned_voices_config


@router.get("/cloned-voices", summary="Get cloned voices list")
def get_cloned_voices(request: Request):
    """Get the list of cloned voices from configuration."""
    try:
        cloned_voices = cloned_voices_config.get_voices()
        return utils.get_response(200, {"voices": cloned_voices})
    except Exception as e:
        logger.error(f"Failed to get cloned voices: {str(e)}")
        return utils.get_response(500, {"error": str(e)})


@router.get("/cloned-voices/providers", summary="Get cloned voice providers")
def get_cloned_voice_providers(request: Request):
    """Get list of available voice providers."""
    try:
        providers = cloned_voices_config.get_providers()
        return utils.get_response(200, {"providers": providers})
    except Exception as e:
        logger.error(f"Failed to get cloned voice providers: {str(e)}")
        return utils.get_response(500, {"error": str(e)})


@router.get("/cloned-voices/models/{provider}", summary="Get models for a provider")
def get_cloned_voice_models(request: Request, provider: str):
    """Get list of models for a specific provider."""
    try:
        models = cloned_voices_config.get_models(provider)
        return utils.get_response(200, {"models": models})
    except Exception as e:
        logger.error(f"Failed to get cloned voice models: {str(e)}")
        return utils.get_response(500, {"error": str(e)})


@router.post("/cloned-voices", summary="Add or update cloned voice")
def add_cloned_voice(request: Request, voice_data: dict):
    """
    Add or update a cloned voice.
    
    Args:
        voice_data: Dictionary containing:
            - voiceId: Unique voice identifier (required)
            - displayName: Display name for the voice (required)
            - gender: Voice gender (optional)
            - model: Target model for TTS synthesis (required)
            - brief: Description of the voice (optional)
            - provider: Voice provider (optional, default: "qwen")
            - region: Service region (optional)
    """
    try:
        required_fields = ["voiceId", "displayName", "model"]
        for field in required_fields:
            if field not in voice_data:
                return utils.get_response(400, {"error": f"Missing required field: {field}"})
        
        if "provider" not in voice_data:
            voice_data["provider"] = "qwen"
        
        cloned_voices_config.add_voice(voice_data)
        logger.info(f"Added/updated cloned voice: {voice_data['displayName']}")
        
        all_voices = cloned_voices_config.get_voices()
        return utils.get_response(200, {"message": "Voice saved successfully", "voices": all_voices})
    except Exception as e:
        logger.error(f"Failed to add cloned voice: {str(e)}")
        return utils.get_response(500, {"error": str(e)})


@router.delete("/cloned-voices/{voice_id}", summary="Delete cloned voice")
def delete_cloned_voice(request: Request, voice_id: str):
    """Delete a cloned voice by voiceId."""
    try:
        success = cloned_voices_config.delete_voice(voice_id)
        
        if success:
            logger.info(f"Deleted cloned voice: {voice_id}")
            all_voices = cloned_voices_config.get_voices()
            return utils.get_response(200, {"message": "Voice deleted successfully", "voices": all_voices})
        else:
            return utils.get_response(404, {"error": "Voice not found"})
    except Exception as e:
        logger.error(f"Failed to delete cloned voice: {str(e)}")
        return utils.get_response(500, {"error": str(e)})


@router.post("/cloned-voices/import", summary="Import cloned voices from JSON")
def import_cloned_voices(request: Request, data: dict):
    """
    Import cloned voices from JSON data.
    
    Args:
        data: Dictionary containing:
            - json_data: JSON string or list of voice objects
    """
    try:
        json_data = data.get("json_data", "")
        
        if not json_data:
            return utils.get_response(400, {"error": "JSON data is required"})
        
        # Parse JSON data
        if isinstance(json_data, str):
            import json
            try:
                voices = json.loads(json_data)
            except json.JSONDecodeError as e:
                return utils.get_response(400, {"error": f"Invalid JSON: {str(e)}"})
        elif isinstance(json_data, list):
            voices = json_data
        else:
            return utils.get_response(400, {"error": "JSON data must be a list of voice objects"})
        
        if not isinstance(voices, list):
            voices = [voices]
        
        # Set default provider if not specified
        for voice_data in voices:
            if "provider" not in voice_data:
                voice_data["provider"] = "qwen"
        
        cloned_voices_config.import_voices(voices)
        logger.info(f"Imported {len(voices)} cloned voices")
        
        all_voices = cloned_voices_config.get_voices()
        return utils.get_response(200, {"message": f"Imported {len(voices)} voices successfully", "voices": all_voices})
    except Exception as e:
        logger.error(f"Failed to import cloned voices: {str(e)}")
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
