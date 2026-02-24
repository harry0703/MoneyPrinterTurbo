import asyncio
import math
import os.path
import random
import re
from dataclasses import dataclass
from os import path
from typing import Any

from edge_tts import SubMaker
from loguru import logger

from app.config import config
from app.models import const
from app.models.schema import VideoConcatMode, VideoParams
from app.services import llm, material, subtitle, video, voice
from app.services import state as sm
from app.utils import utils


@dataclass(slots=True)
class AudioGenerationResult:
    audio_file: str
    audio_duration: float
    sub_maker: SubMaker | None


@dataclass(slots=True)
class FinalVideoResult:
    videos: list[str]
    combined_videos: list[str]


def generate_script(task_id: str, params: VideoParams) -> str | None:
    logger.info("\n\n## generating video script")
    video_script = params.video_script.strip()
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


def generate_terms(
    task_id: str, params: VideoParams, video_script: str
) -> list[str] | None:
    logger.info("\n\n## generating video terms")
    video_terms = params.video_terms
    if not video_terms:
        generated_terms = llm.generate_terms(
            video_subject=params.video_subject, video_script=video_script, amount=5
        )
        if isinstance(generated_terms, list):
            video_terms = generated_terms
        else:
            logger.error(f"invalid video terms returned by llm: {generated_terms}")
            video_terms = None
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


def save_script_data(
    task_id: str, video_script: str, video_terms: list[str], params: VideoParams
) -> None:
    script_file = path.join(utils.task_dir(task_id), "script.json")
    script_data = {
        "script": video_script,
        "search_terms": video_terms,
        "params": params,
    }

    with open(script_file, "w", encoding="utf-8") as file_obj:
        file_obj.write(utils.to_json(script_data) or "{}")


def generate_audio(
    task_id: str, params: VideoParams, video_script: str
) -> AudioGenerationResult | None:
    """
    Generate audio for the video script.
    If a custom audio file is provided, it will be used directly.
    There will be no subtitle maker object returned in this case.
    Otherwise, TTS will be used to generate the audio.
    """
    logger.info("\n\n## generating audio")
    custom_audio_file = params.custom_audio_file
    if not custom_audio_file or not os.path.exists(custom_audio_file):
        if custom_audio_file:
            logger.warning(
                f"custom audio file not found: {custom_audio_file}, using TTS to generate audio."
            )
        else:
            logger.info("no custom audio file provided, using TTS to generate audio.")

        if not params.voice_name:
            logger.error("voice_name is empty, cannot generate audio.")
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            return None

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
            return None

        audio_duration = float(math.ceil(voice.get_audio_duration(sub_maker)))
        if audio_duration == 0:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error("failed to get audio duration.")
            return None

        return AudioGenerationResult(
            audio_file=audio_file,
            audio_duration=audio_duration,
            sub_maker=sub_maker,
        )

    logger.info(f"using custom audio file: {custom_audio_file}")
    audio_duration = voice.get_audio_duration(custom_audio_file)
    if audio_duration == 0:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("failed to get audio duration from custom audio file.")
        return None

    return AudioGenerationResult(
        audio_file=custom_audio_file,
        audio_duration=audio_duration,
        sub_maker=None,
    )


def generate_subtitle(
    task_id: str,
    params: VideoParams,
    video_script: str,
    sub_maker: SubMaker | None,
    audio_file: str,
) -> str:
    """
    Generate subtitle for the video script.
    If subtitle generation is disabled or no subtitle maker is provided, it will return an empty string.
    Otherwise, it will generate the subtitle using the specified provider.
    """
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

    subtitle_lines = subtitle.file_to_subtitles(subtitle_path)
    if not subtitle_lines:
        logger.warning(f"subtitle file is invalid: {subtitle_path}")
        return ""

    return subtitle_path


def get_video_materials(
    task_id: str,
    params: VideoParams,
    video_terms: list[str],
    audio_duration: float,
) -> list[str] | None:
    if params.video_source == "local":
        logger.info("\n\n## preprocess local materials")
        materials = video.preprocess_video(
            materials=params.video_materials, clip_duration=params.video_clip_duration
        )
        if not materials:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                "no valid materials found, please check the materials and try again."
            )
            return None
        return [material_info.url for material_info in materials]

    if params.video_source == "jimeng":
        logger.info("\n\n## generating video using JiMeng API")
        from app.services.jimeng_video import jimeng_video_service

        try:
            base_prompt = (params.video_script or params.video_subject or "").strip()
            if not base_prompt:
                sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
                logger.error("no prompt provided for JiMeng video generation")
                return None

            video_aspect = (
                params.video_aspect.value
                if hasattr(params.video_aspect, "value")
                else "16:9"
            )

            try:
                estimated_clip_duration = float(
                    config.jimeng.get("clip_duration_seconds", 5)
                )
            except (TypeError, ValueError):
                estimated_clip_duration = 5
            if estimated_clip_duration <= 0:
                estimated_clip_duration = 5

            total_target_duration = audio_duration * max(params.video_count or 1, 1)
            target_clip_count = max(
                1, math.ceil(total_target_duration / estimated_clip_duration)
            )
            max_clips_cfg = config.jimeng.get("max_clips", 12)
            try:
                max_clips = int(max_clips_cfg) if max_clips_cfg is not None else 12
            except (TypeError, ValueError):
                max_clips = 12
            if max_clips > 0 and target_clip_count > max_clips:
                logger.warning(
                    f"target JiMeng clip count {target_clip_count} exceeds max_clips={max_clips}, capped"
                )
                target_clip_count = max_clips

            clean_terms = [term.strip() for term in video_terms if term and term.strip()]
            try:
                poll_interval = max(
                    1, int(config.jimeng.get("poll_interval", 10) or 10)
                )
            except (TypeError, ValueError):
                poll_interval = 10
            try:
                timeout = max(60, int(config.jimeng.get("timeout", 600) or 600))
            except (TypeError, ValueError):
                timeout = 600
            material_directory = config.app.get("material_directory", "").strip()
            if material_directory == "task":
                material_directory = utils.task_dir(task_id)
            elif material_directory and not os.path.isdir(material_directory):
                material_directory = ""
            logger.info(
                f"JiMeng target clips: {target_clip_count}, audio_duration: {audio_duration:.2f}s, estimated_clip_duration: {estimated_clip_duration:.2f}s"
            )

            generated_video_paths: list[str] = []
            for i in range(target_clip_count):
                term = clean_terms[i % len(clean_terms)] if clean_terms else ""
                scene_prompt = base_prompt
                if term:
                    scene_prompt = (
                        f"{scene_prompt}\n\nScene keyword: {term}\nScene index: {i + 1}/{target_clip_count}"
                    )
                else:
                    scene_prompt = f"{scene_prompt}\n\nScene index: {i + 1}/{target_clip_count}"

                seed = random.randint(1, 2_147_483_647)
                logger.info(
                    f"Generating JiMeng clip {i + 1}/{target_clip_count}, seed={seed}"
                )
                video_url = asyncio.run(
                    jimeng_video_service.generate_video(
                        prompt=scene_prompt,
                        seed=seed,
                        aspect_ratio=video_aspect,
                        poll_interval=poll_interval,
                        timeout=timeout,
                    )
                )
                if video_url:
                    saved_video_path = material.save_video(
                        video_url=video_url, save_dir=material_directory
                    )
                    if saved_video_path:
                        generated_video_paths.append(saved_video_path)
                        logger.info(
                            f"JiMeng clip generated and saved ({i + 1}/{target_clip_count}): {saved_video_path}"
                        )
                    else:
                        logger.warning(
                            f"JiMeng clip generated but failed to save locally ({i + 1}/{target_clip_count})"
                        )
                else:
                    logger.warning(
                        f"JiMeng clip generation returned empty url ({i + 1}/{target_clip_count})"
                    )

            if generated_video_paths:
                logger.info(
                    f"JiMeng video generation finished, saved {len(generated_video_paths)}/{target_clip_count} clips locally"
                )
                return generated_video_paths

            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error("failed to generate video using JiMeng API")
            return None

        except Exception as e:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(f"error generating video with JiMeng API: {e}")
            return None

    logger.info(f"\n\n## downloading videos from {params.video_source}")
    downloaded_videos = material.download_videos(
        task_id=task_id,
        search_terms=video_terms,
        source=params.video_source,
        video_aspect=params.video_aspect,
        video_contact_mode=params.video_concat_mode,
        audio_duration=audio_duration * params.video_count,
        max_clip_duration=params.video_clip_duration,
    )
    if not downloaded_videos:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error(
            "failed to download videos, maybe the network is not available. if you are in China, please use a VPN."
        )
        return None

    return downloaded_videos


def generate_final_videos(
    task_id: str,
    params: VideoParams,
    downloaded_videos: list[str],
    audio_file: str,
    subtitle_path: str,
) -> FinalVideoResult:
    final_video_paths: list[str] = []
    combined_video_paths: list[str] = []
    video_concat_mode = (
        params.video_concat_mode if params.video_count == 1 else VideoConcatMode.random
    )
    video_transition_mode = params.video_transition_mode

    progress = 50.0
    for i in range(params.video_count):
        index = i + 1
        combined_video_path = path.join(utils.task_dir(task_id), f"combined-{index}.mp4")
        logger.info(f"\n\n## combining video: {index} => {combined_video_path}")
        video.combine_videos(
            combined_video_path=combined_video_path,
            video_paths=downloaded_videos,
            audio_file=audio_file,
            video_aspect=params.video_aspect,
            video_concat_mode=video_concat_mode,
            video_transition_mode=video_transition_mode,
            max_clip_duration=params.video_clip_duration,
            threads=params.n_threads,
        )

        progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=progress)

        final_video_path = path.join(utils.task_dir(task_id), f"final-{index}.mp4")

        logger.info(f"\n\n## generating video: {index} => {final_video_path}")
        video.generate_video(
            video_path=combined_video_path,
            audio_path=audio_file,
            subtitle_path=subtitle_path,
            output_file=final_video_path,
            params=params,
        )

        progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=progress)

        final_video_paths.append(final_video_path)
        combined_video_paths.append(combined_video_path)

    return FinalVideoResult(videos=final_video_paths, combined_videos=combined_video_paths)


def start(
    task_id: str, params: VideoParams, stop_at: str = "video"
) -> dict[str, Any] | None:
    logger.info(f"start task: {task_id}, stop_at: {stop_at}")
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=5)

    if isinstance(params.video_concat_mode, str):
        params.video_concat_mode = VideoConcatMode(params.video_concat_mode)

    video_script = generate_script(task_id, params)
    if not video_script or "Error: " in video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return None

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=10)

    if stop_at == "script":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, script=video_script
        )
        return {"script": video_script}

    video_terms: list[str] = []
    if params.video_source != "local":
        video_terms = generate_terms(task_id, params, video_script) or []
        if not video_terms:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            return None

    save_script_data(task_id, video_script, video_terms, params)

    if stop_at == "terms":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, terms=video_terms
        )
        return {"script": video_script, "terms": video_terms}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)

    audio_result = generate_audio(task_id, params, video_script)
    if audio_result is None:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return None

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=30)

    if stop_at == "audio":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            audio_file=audio_result.audio_file,
        )
        return {
            "audio_file": audio_result.audio_file,
            "audio_duration": audio_result.audio_duration,
        }

    subtitle_path = generate_subtitle(
        task_id,
        params,
        video_script,
        audio_result.sub_maker,
        audio_result.audio_file,
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

    downloaded_videos = get_video_materials(
        task_id, params, video_terms, audio_result.audio_duration
    )
    if not downloaded_videos:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return None

    if stop_at == "materials":
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            materials=downloaded_videos,
        )
        return {"materials": downloaded_videos}

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=50)

    try:
        final_videos = generate_final_videos(
            task_id,
            params,
            downloaded_videos,
            audio_result.audio_file,
            subtitle_path,
        )
    except Exception as e:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.exception(f"failed to generate final videos: {e}")
        return None

    if not final_videos.videos:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return None

    logger.success(f"task {task_id} finished, generated {len(final_videos.videos)} videos.")

    kwargs = {
        "videos": final_videos.videos,
        "combined_videos": final_videos.combined_videos,
        "script": video_script,
        "terms": video_terms,
        "audio_file": audio_result.audio_file,
        "audio_duration": audio_result.audio_duration,
        "subtitle_path": subtitle_path,
        "materials": downloaded_videos,
    }
    sm.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs)
    return kwargs


if __name__ == "__main__":
    task_id = "task_id"
    params = VideoParams(
        video_subject="test",
        voice_name="zh-CN-XiaoyiNeural-Female",
        voice_rate=1.0,
    )
    start(task_id, params, stop_at="video")
