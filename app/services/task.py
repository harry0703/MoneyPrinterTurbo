import math
import os.path
import re
import unicodedata
from os import path

from loguru import logger
from moviepy import ColorClip

from app.config import config
from app.models import const
from app.models.schema import VideoAspect, VideoConcatMode, VideoParams
from app.integrations.provider_router import generate_with_fallback, generate_with_provider
from app.services import cover, llm, material, subtitle, video, voice, upload_post
from app.services.narration_source import NarrationSourceService
from app.services import state as sm
from app.utils import utils


narration_source = NarrationSourceService()


def _apply_avatar_bridge(params: VideoParams) -> None:
    avatar_file = str(getattr(params, "avatar_image_file", "") or "").strip()
    if not avatar_file:
        return

    avatar_abs = path.abspath(avatar_file)
    storage_abs = path.abspath(utils.storage_dir())
    tasks_abs = path.abspath(utils.storage_dir("tasks"))
    avatar_real = path.realpath(avatar_abs)
    storage_real = path.realpath(storage_abs)
    tasks_real = path.realpath(tasks_abs)

    if not path.isfile(avatar_real):
        logger.warning(f"avatar file not found or not a file: {avatar_file}")
        return

    def is_within(root: str, target: str) -> bool:
        return target.startswith(root + path.sep)

    if not (
        (is_within(storage_abs, avatar_abs) or is_within(tasks_abs, avatar_abs))
        and (is_within(storage_real, avatar_real) or is_within(tasks_real, avatar_real))
    ):
        logger.warning(f"avatar file outside allowed storage: {avatar_file}")
        return

    avatar_path = avatar_real

    # Reuse the existing character overlay + lipsync pipeline for advanced avatar uploads.
    params.character_overlay_enabled = True
    if not getattr(params, "character_image_file", None):
        params.character_image_file = avatar_path
    params.character_lipsync_enabled = True

    avatar_position = str(getattr(params, "avatar_position", "") or "").strip().lower()
    offset_x = int(getattr(params, "avatar_offset_x", 0) or 0)
    offset_y = int(getattr(params, "avatar_offset_y", 0) or 0)

    base_position_to_percent: dict[str, tuple[float, float]] = {
        "top_left": (0.0, 0.0),
        "top_right": (100.0, 0.0),
        "bottom_left": (0.0, 100.0),
        "bottom_right": (100.0, 100.0),
        "center": (50.0, 50.0),
    }
    if avatar_position == "custom":
        params.character_position = "custom"
        params.character_custom_x = min(100.0, max(0.0, 50.0 + float(offset_x)))
        params.character_custom_y = min(100.0, max(0.0, 50.0 + float(offset_y)))
        return

    if avatar_position in base_position_to_percent:
        base_x, base_y = base_position_to_percent[avatar_position]
        effective_x = min(100.0, max(0.0, base_x + float(offset_x)))
        effective_y = min(100.0, max(0.0, base_y + float(offset_y)))
        # Use custom mode so offset sliders visibly affect avatar placement.
        params.character_position = "custom"
        params.character_custom_x = effective_x
        params.character_custom_y = effective_y


def _sanitize_output_filename(text: str, max_length: int = 64) -> str:
    normalized = unicodedata.normalize("NFKD", (text or "")).encode("ascii", "ignore").decode("ascii")
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", normalized).strip("-").lower()
    if not normalized:
        return "video"
    return normalized[:max_length].rstrip("-") or "video"


def _build_final_video_filename(params: VideoParams, index: int) -> str:
    task_title = utils.build_task_title(
        video_subject=params.video_subject,
        video_script=params.video_script,
        fallback_title=os.path.splitext(os.path.basename(getattr(params, "pdf_file", "") or ""))[0],
    )
    safe_title = _sanitize_output_filename(task_title)
    if params.video_count > 1:
        return f"{safe_title}-{index}.mp4"
    return f"{safe_title}.mp4"


def generate_script(task_id, params):
    logger.info("\n\n## generating video script")
    content_source = str(getattr(params, "content_source", "text") or "text").strip().lower()

    if content_source == "pdf":
        try:
            video_script = narration_source.resolve_text(
                prompt=params.video_script,
                content_source=content_source,
                pdf_path=getattr(params, "pdf_file", None),
            )
        except Exception as exc:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(f"failed to resolve narration text from pdf: {str(exc)}")
            return None
        logger.debug("video script resolved from uploaded pdf")
        return video_script

    video_script = narration_source.normalize_text(params.video_script)
    if not video_script:
        video_script = llm.generate_script(
            video_subject=params.video_subject,
            language=params.video_language,
            paragraph_number=params.paragraph_number,
        )
    else:
        logger.debug(f"video script: \n{video_script}")

    if not video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("failed to generate video script.")
        return None

    return video_script


def generate_terms(task_id, params, video_script):
    logger.info("\n\n## generating video terms")
    video_terms = params.video_terms
    if not video_terms:
        video_terms = llm.generate_terms(
            video_subject=params.video_subject, video_script=video_script, amount=5
        )
    else:
        if isinstance(video_terms, str):
            video_terms = [term.strip() for term in re.split(r"[,，]", video_terms)]
        elif isinstance(video_terms, list):
            video_terms = [term.strip() for term in video_terms]
        else:
            raise ValueError("video_terms must be a string or a list of strings.")

        logger.debug(f"video terms: {utils.to_json(video_terms)}")

    if not video_terms:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("failed to generate video terms.")
        return None

    return video_terms


def save_script_data(task_id, video_script, video_terms, params):
    script_file = path.join(utils.task_dir(task_id), "script.json")
    script_data = {
        "script": video_script,
        "search_terms": video_terms,
        "params": params,
    }

    with open(script_file, "w", encoding="utf-8") as f:
        f.write(utils.to_json(script_data))


def resolve_effective_clip_duration(params, video_script, audio_duration):
    duration_mode = str(getattr(params, "duration_mode", "manual") or "manual").strip().lower()
    raw_clip_duration = params.video_clip_duration
    clip_duration = int(raw_clip_duration) if raw_clip_duration is not None else 5
    if duration_mode != "auto_text" and clip_duration > 0:
        return clip_duration

    sentences = utils.split_string_by_punctuations(video_script or "")
    if not sentences:
        return 5

    average_sentence_duration = audio_duration / max(len(sentences), 1)
    return max(4, min(12, math.ceil(average_sentence_duration)))


def generate_audio(task_id, params, video_script):
    '''
    Generate audio for the video script.
    If a custom audio file is provided, it will be used directly.
    There will be no subtitle maker object returned in this case.
    Otherwise, TTS will be used to generate the audio.
    Returns:
        - audio_file: path to the generated or provided audio file
        - audio_duration: duration of the audio in seconds
        - sub_maker: subtitle maker object if TTS is used, None otherwise
    '''
    logger.info("\n\n## generating audio")
    # /audio 和 /subtitle 请求模型不包含 custom_audio_file，
    # 这里统一做兼容读取，避免直调接口时抛属性错误。
    custom_audio_file = getattr(params, "custom_audio_file", None)
    if not custom_audio_file or not os.path.exists(custom_audio_file):
        if custom_audio_file:
            logger.warning(
                f"custom audio file not found: {custom_audio_file}, using TTS to generate audio."
            )
        else:
            logger.info("no custom audio file provided, using TTS to generate audio.")
        audio_file = path.join(utils.task_dir(task_id), "audio.mp3")
        sub_maker = voice.tts(
            text=video_script,
            voice_name=voice.parse_voice_name(params.voice_name),
            voice_rate=params.voice_rate,
            voice_file=audio_file,
        )
        if sub_maker is None:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                """failed to generate audio:
1. check if the language of the voice matches the language of the video script.
2. check if the network is available. If you are in China, it is recommended to use a VPN and enable the global traffic mode.
            """.strip()
            )
            return None, None, None
        audio_duration = math.ceil(voice.get_audio_duration(sub_maker))
        if audio_duration == 0:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error("failed to get audio duration.")
            return None, None, None
        return audio_file, audio_duration, sub_maker
    else:
        logger.info(f"using custom audio file: {custom_audio_file}")
        audio_duration = voice.get_audio_duration(custom_audio_file)
        if audio_duration == 0:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error("failed to get audio duration from custom audio file.")
            return None, None, None
        return custom_audio_file, audio_duration, None

def generate_subtitle(task_id, params, video_script, sub_maker, audio_file):
    '''
    Generate subtitle for the video script.
    If subtitle generation is disabled or no subtitle maker is provided, it will return an empty string.
    Otherwise, it will generate the subtitle using the specified provider.
    Returns:
        - subtitle_path: path to the generated subtitle file
    '''
    logger.info("\n\n## generating subtitle")
    if not params.subtitle_enabled or sub_maker is None:
        return ""

    subtitle_path = path.join(utils.task_dir(task_id), "subtitle.srt")
    subtitle_provider = config.app.get("subtitle_provider", "edge").strip().lower()
    logger.info(f"\n\n## generating subtitle, provider: {subtitle_provider}")

    subtitle_fallback = False
    if subtitle_provider == "edge":
        voice.create_subtitle(
            text=video_script, sub_maker=sub_maker, subtitle_file=subtitle_path
        )
        if not os.path.exists(subtitle_path):
            subtitle_fallback = True
            logger.warning("subtitle file not found, fallback to whisper")

    if subtitle_provider == "whisper" or subtitle_fallback:
        subtitle.create(audio_file=audio_file, subtitle_file=subtitle_path)
        logger.info("\n\n## correcting subtitle")
        subtitle.correct(subtitle_file=subtitle_path, video_script=video_script)

    if audio_file and os.path.exists(audio_file):
        voice.align_subtitle_file_duration(
            subtitle_file=subtitle_path,
            audio_duration_seconds=voice.get_audio_duration(audio_file),
        )

    subtitle_lines = subtitle.file_to_subtitles(subtitle_path)
    if not subtitle_lines:
        logger.warning(f"subtitle file is invalid: {subtitle_path}")
        return ""

    return subtitle_path


def get_video_materials(task_id, params, video_terms, audio_duration):
    effective_clip_duration = resolve_effective_clip_duration(
        params, params.video_script, audio_duration
    )

    def _convert_external_material(local_path: str, provider_name: str) -> list[str]:
        local_extension = utils.parse_extension(local_path)
        if local_extension in const.FILE_TYPE_IMAGES:
            logger.info("external provider returned image, converting it to animated clip")
            external_materials = [
                type("ExternalMaterial", (), {"provider": provider_name, "url": local_path, "duration": 0})()
            ]
            preprocessed = video.preprocess_video(
                materials=external_materials,
                clip_duration=effective_clip_duration,
            )
            return [item.url for item in preprocessed] if preprocessed else []
        return [local_path]

    def _generate_external_fallback(prompt: str, metadata: dict) -> list[str]:
        payload = {
            "prompt": prompt,
            "aspectRatio": str(params.video_aspect or "9:16"),
            "duration": int(effective_clip_duration or 5),
            "outputType": (getattr(params, "external_output_type", "video") or "video"),
            "metadata": dict(metadata or {}),
        }
        output_dir = path.join(utils.storage_dir(), "generated")
        preferred_provider = (getattr(params, "external_provider", "") or "").strip().lower()
        result = generate_with_fallback(
            payload,
            output_dir=output_dir,
            preferred_provider=preferred_provider,
        )
        if not result.get("success"):
            logger.warning(
                f"external fallback failed error={result.get('error', 'unknown')}"
            )
            return []

        local_path = result.get("localPath") or ""
        if not local_path or not os.path.exists(local_path):
            logger.warning("external fallback completed without local file")
            return []

        return _convert_external_material(local_path, result.get("provider") or preferred_provider or "external")
    if params.video_source == "external":
        provider_name = (getattr(params, "external_provider", "") or "").strip().lower()
        if not provider_name:
            logger.warning("video_source=external but external_provider is empty, trying external fallback")
            external_prompt = params.video_subject or " ".join(video_terms or []) or params.video_script
            return _generate_external_fallback(external_prompt, {})

        external_prompt = params.video_subject or " ".join(video_terms or []) or params.video_script
        external_payload = {
            "prompt": external_prompt,
            "aspectRatio": str(params.video_aspect or "9:16"),
            "duration": int(effective_clip_duration or 5),
            "outputType": (getattr(params, "external_output_type", "video") or "video"),
            "metadata": dict(getattr(params, "external_metadata", None) or {}),
        }
        output_dir = path.join(utils.storage_dir(), "generated")
        result = generate_with_provider(provider_name, external_payload, output_dir=output_dir)
        if not result.get("success"):
            logger.warning(
                f"external generation failed provider={provider_name} error={result.get('error', 'unknown')}"
            )
            external_prompt = external_payload["prompt"]
            metadata = dict(external_payload.get("metadata", {}))
            return _generate_external_fallback(external_prompt, metadata)

        local_path = result.get("localPath") or ""
        if not local_path or not os.path.exists(local_path):
            logger.warning(
                f"external provider returned success without local file provider={provider_name}, trying fallback"
            )
            external_prompt = external_payload["prompt"]
            metadata = dict(external_payload.get("metadata", {}))
            return _generate_external_fallback(external_prompt, metadata)

        converted = _convert_external_material(local_path, provider_name)
        return converted

    if params.video_source == "local":
        logger.info("\n\n## preprocess local materials")
        materials = video.preprocess_video(
            materials=params.video_materials, clip_duration=effective_clip_duration
        )
        if not materials:
            logger.warning("no valid local materials found, trying external fallback")
            external_prompt = params.video_subject or " ".join(video_terms or []) or params.video_script
            return _generate_external_fallback(external_prompt, {})
        return [material_info.url for material_info in materials]
    else:
        logger.info(f"\n\n## downloading videos from {params.video_source}")
        downloaded_videos = material.download_videos(
            task_id=task_id,
            search_terms=video_terms,
            source=params.video_source,
            video_aspect=params.video_aspect,
            video_contact_mode=params.video_concat_mode,
            audio_duration=audio_duration * params.video_count,
            max_clip_duration=effective_clip_duration,
        )
        if not downloaded_videos:
            logger.warning("failed to download videos, trying external fallback")
            external_prompt = params.video_subject or " ".join(video_terms or []) or params.video_script
            return _generate_external_fallback(external_prompt, {})
        return downloaded_videos


def build_fallback_materials(task_id, params, video_terms, audio_duration):
    logger.info("\n\n## generating fallback visual materials")
    fallback_dir = path.join(utils.task_dir(task_id), "fallback_materials")
    os.makedirs(fallback_dir, exist_ok=True)
    video_width, video_height = VideoAspect(params.video_aspect).to_resolution()
    clip_duration = resolve_effective_clip_duration(params, params.video_script, audio_duration)
    palette = _fallback_palette(video_terms)
    material_paths = []

    # Crear varios clips para que combine_videos pueda concatenarlos y extenderlos
    # hasta cubrir toda la duración del audio.
    for index, color in enumerate(palette[:3], start=1):
        clip_path = path.join(fallback_dir, f"fallback-{index}.mp4")
        if os.path.exists(clip_path) and os.path.getsize(clip_path) > 0:
            material_paths.append(clip_path)
            continue
        clip = ColorClip(size=(video_width, video_height), color=color).with_duration(clip_duration)
        clip.write_videofile(clip_path, fps=30, codec="libx264", audio=False, logger=None)
        clip.close()
        material_paths.append(clip_path)

    return material_paths


def _fallback_palette(video_terms):
    seed_text = " ".join(video_terms or []) if isinstance(video_terms, list) else str(video_terms or "fallback")
    seed = sum(ord(char) for char in seed_text)
    colors = [
        ((seed * 3) % 120 + 60, (seed * 5) % 120 + 60, (seed * 7) % 120 + 60),
        ((seed * 11) % 120 + 60, (seed * 13) % 120 + 60, (seed * 17) % 120 + 60),
        ((seed * 19) % 120 + 60, (seed * 23) % 120 + 60, (seed * 29) % 120 + 60),
    ]
    return colors


def generate_final_videos(
    task_id,
    params,
    downloaded_videos,
    audio_file,
    subtitle_path,
    cover_image_path: str = "",
):
    final_video_paths = []
    combined_video_paths = []
    effective_clip_duration = resolve_effective_clip_duration(
        params, params.video_script, voice.get_audio_duration(audio_file)
    )
    video_concat_mode = (
        params.video_concat_mode if params.video_count == 1 else VideoConcatMode.random
    )
    video_transition_mode = params.video_transition_mode

    _progress = 50
    for i in range(params.video_count):
        index = i + 1
        combined_video_path = path.join(
            utils.task_dir(task_id), f"combined-{index}.mp4"
        )
        logger.info(f"\n\n## combining video: {index} => {combined_video_path}")
        video.combine_videos(
            combined_video_path=combined_video_path,
            video_paths=downloaded_videos,
            audio_file=audio_file,
            video_aspect=params.video_aspect,
            video_concat_mode=video_concat_mode,
            video_transition_mode=video_transition_mode,
            max_clip_duration=effective_clip_duration,
            threads=params.n_threads,
        )

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

        final_video_path = path.join(
            utils.task_dir(task_id), _build_final_video_filename(params, index)
        )

        logger.info(f"\n\n## generating video: {index} => {final_video_path}")
        video.generate_video(
            video_path=combined_video_path,
            audio_path=audio_file,
            subtitle_path=subtitle_path,
            output_file=final_video_path,
            params=params,
            cover_image_path=cover_image_path,
        )

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

        final_video_paths.append(final_video_path)
        combined_video_paths.append(combined_video_path)

    return final_video_paths, combined_video_paths


def start(task_id, params: VideoParams, stop_at: str = "video"):
    logger.info(f"start task: {task_id}, stop_at: {stop_at}")
    _apply_avatar_bridge(params)
    original_task_dir = utils.ensure_task_dir(
        task_id,
        utils.build_task_title(
            video_subject=params.video_subject,
            video_script=params.video_script,
        ),
    )
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=5)

    # 1. Generate script
    video_script = generate_script(task_id, params)
    if not video_script or "Error: " in video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return
    params.video_script = video_script
    renamed_task_dir = utils.rename_task_dir(
        task_id,
        utils.build_task_title(
            video_subject=params.video_subject,
            video_script=video_script,
            fallback_title=os.path.splitext(os.path.basename(params.pdf_file))[0]
            if getattr(params, "pdf_file", None)
            else "",
        ),
    )

    def _rebase_task_path(path_value: str | None) -> str | None:
        if not path_value:
            return path_value
        old_root = os.path.realpath(original_task_dir)
        new_root = os.path.realpath(renamed_task_dir)
        resolved = os.path.realpath(path_value)
        if resolved == old_root:
            return new_root
        if resolved.startswith(old_root + os.sep):
            suffix = resolved[len(old_root):].lstrip(os.sep)
            return os.path.join(new_root, suffix)
        return path_value

    params.pdf_file = _rebase_task_path(getattr(params, "pdf_file", None))
    params.custom_cover_file = _rebase_task_path(getattr(params, "custom_cover_file", None))
    params.custom_audio_file = _rebase_task_path(getattr(params, "custom_audio_file", None))
    params.character_image_file = _rebase_task_path(getattr(params, "character_image_file", None))
    params.avatar_image_file = _rebase_task_path(getattr(params, "avatar_image_file", None))
    params.bgm_file = _rebase_task_path(getattr(params, "bgm_file", None))

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=10)

    if stop_at == "script":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, script=video_script
        )
        return {"script": video_script}

    # 2. Generate terms
    video_terms = ""
    if params.video_source != "local":
        video_terms = generate_terms(task_id, params, video_script)
        if not video_terms:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            return

    save_script_data(task_id, video_script, video_terms, params)

    if stop_at == "terms":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, terms=video_terms
        )
        return {"script": video_script, "terms": video_terms}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)

    # 3. Generate audio
    audio_file, audio_duration, sub_maker = generate_audio(
        task_id, params, video_script
    )
    if not audio_file:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=30)

    if stop_at == "audio":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            audio_file=audio_file,
        )
        return {"audio_file": audio_file, "audio_duration": audio_duration}

    # 4. Generate subtitle
    subtitle_path = generate_subtitle(
        task_id, params, video_script, sub_maker, audio_file
    )

    if stop_at == "subtitle":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            subtitle_path=subtitle_path,
        )
        return {"subtitle_path": subtitle_path}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=40)

    # 5. Get video materials
    downloaded_videos = get_video_materials(
        task_id, params, video_terms, audio_duration
    )
    if not downloaded_videos:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    if stop_at == "materials":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            materials=downloaded_videos,
        )
        return {"materials": downloaded_videos}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=50)

    # 仅完整视频生成流程才需要处理视频拼接模式；
    # 这样可以避免 /subtitle 和 /audio 这类请求访问不存在的字段。
    if type(params.video_concat_mode) is str:
        params.video_concat_mode = VideoConcatMode(params.video_concat_mode)

    # Build cover before final rendering so it can be used as video intro.
    cover_image_path = resolve_cover_image_path(
        task_id=task_id,
        params=params,
        video_script=video_script,
        video_terms=video_terms,
        material_paths=downloaded_videos,
    )

    # 6. Generate final videos
    final_video_paths, combined_video_paths = generate_final_videos(
        task_id,
        params,
        downloaded_videos,
        audio_file,
        subtitle_path,
        cover_image_path,
    )

    if not final_video_paths:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

    logger.success(
        f"task {task_id} finished, generated {len(final_video_paths)} videos."
    )

    # 7. Cross-post to TikTok/Instagram (if enabled)
    cross_post_results = []
    if upload_post.upload_post_service.is_configured() and upload_post.upload_post_service.auto_upload:
        logger.info("\n\n## cross-posting videos to TikTok/Instagram")
        for video_path in final_video_paths:
            result = upload_post.cross_post_video(
                video_path=video_path,
                title=params.video_subject or "Check out this video! #shorts #viral"
            )
            cross_post_results.append(result)
            if result.get('success'):
                logger.info(f"✅ Cross-posted: {video_path}")
            else:
                logger.warning(f"⚠️ Failed to cross-post: {video_path} - {result.get('error', 'Unknown error')}")

    kwargs = {
        "videos": final_video_paths,
        "combined_videos": combined_video_paths,
        "script": video_script,
        "terms": video_terms,
        "audio_file": audio_file,
        "audio_duration": audio_duration,
        "subtitle_path": subtitle_path,
        "materials": downloaded_videos,
        "cover_image": cover_image_path,
        "cross_post_results": cross_post_results if cross_post_results else None,
    }
    sm.state.update_task(
        task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs
    )
    return kwargs


def resolve_cover_image_path(task_id, params, video_script, video_terms, material_paths):
    custom_cover_file = getattr(params, "custom_cover_file", None)
    if custom_cover_file and os.path.exists(custom_cover_file):
        logger.info(f"using custom cover image: {custom_cover_file}")
        return custom_cover_file

    if not params.generate_cover:
        return ""

    try:
        cover_image_path = cover.generate_cover_image(
            task_id=task_id,
            params=params,
            video_script=video_script,
            video_terms=video_terms,
            material_paths=material_paths,
        )
        logger.info(f"cover image generated: {cover_image_path}")
        return cover_image_path
    except Exception as exc:
        logger.warning(f"failed to generate cover image: {str(exc)}")
        return ""


if __name__ == "__main__":
    task_id = "task_id"
    params = VideoParams(
        video_subject="金钱的作用",
        voice_name="zh-CN-XiaoyiNeural-Female",
        voice_rate=1.0,
    )
    start(task_id, params, stop_at="video")
