import math
import os.path
import re
from os import path

from loguru import logger

from app.config import config
from app.models import const
from app.models.schema import VideoConcatMode, VideoParams
from app.services import llm, material, subtitle, video, voice, upload_post
from app.services import state as sm
from app.utils import utils


def generate_script(task_id, params):
    logger.info("\n\n## generating video script")
    video_script = params.video_script.strip()
    if not video_script:
        if getattr(params, "content_mode", "standard") == "csr_training":
            video_script = llm.generate_csr_training_script(
                training_topic=params.video_subject,
                language=params.video_language,
                scenario_type=getattr(params, "csr_scenario_type", "de-escalation"),
                customer_persona=getattr(
                    params, "csr_customer_persona", "frustrated customer"
                ),
                policy_context=getattr(params, "csr_policy_context", ""),
                duration_seconds=getattr(params, "csr_duration_seconds", 60),
            )
        else:
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


def generate_audio(task_id, params, video_script, file_prefix=""):
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
        audio_file = path.join(utils.task_dir(task_id), f"{file_prefix}audio.mp3")
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

def generate_subtitle(task_id, params, video_script, sub_maker, audio_file, file_prefix=""):
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

    subtitle_path = path.join(utils.task_dir(task_id), f"{file_prefix}subtitle.srt")
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


def get_video_materials(task_id, params, video_terms, audio_duration):
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
    else:
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
    task_id, params, downloaded_videos, audio_file, subtitle_path
):
    final_video_paths = []
    combined_video_paths = []
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
            max_clip_duration=params.video_clip_duration,
            threads=params.n_threads,
        )

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

        final_video_path = path.join(utils.task_dir(task_id), f"final-{index}.mp4")

        logger.info(f"\n\n## generating video: {index} => {final_video_path}")
        video.generate_video(
            video_path=combined_video_path,
            audio_path=audio_file,
            subtitle_path=subtitle_path,
            output_file=final_video_path,
            params=params,
        )

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

        final_video_paths.append(final_video_path)
        combined_video_paths.append(combined_video_path)

    return final_video_paths, combined_video_paths


def _get_long_form_section_duration(params, section, fallback_seconds):
    duration_minutes = section.get("duration_minutes")
    try:
        return max(60, int(float(duration_minutes) * 60))
    except Exception:
        return fallback_seconds


def start_long_csr_training(task_id, params: VideoParams):
    logger.info(f"start long-form csr training task: {task_id}")
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=5)

    target_minutes = int(getattr(params, "csr_target_duration_minutes", 15) or 15)
    section_count = int(getattr(params, "csr_section_count", 8) or 8)
    target_minutes = max(5, min(target_minutes, 60))
    section_count = max(2, min(section_count, 20))
    fallback_section_seconds = max(60, int(target_minutes * 60 / section_count))

    outline = llm.generate_csr_training_outline(
        training_topic=params.video_subject,
        language=params.video_language,
        scenario_type=getattr(params, "csr_scenario_type", "de-escalation"),
        customer_persona=getattr(params, "csr_customer_persona", "frustrated customer"),
        policy_context=getattr(params, "csr_policy_context", ""),
        target_duration_minutes=target_minutes,
        section_count=section_count,
    )
    if not outline or isinstance(outline, str):
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error(f"failed to generate long-form outline: {outline}")
        return

    sm.state.update_task(
        task_id,
        state=const.TASK_STATE_PROCESSING,
        progress=10,
        outline=outline,
    )

    section_results = []
    section_final_videos = []
    section_combined_videos = []
    section_scripts = []
    section_terms = []
    section_progress_span = 80 / len(outline)

    for index, section in enumerate(outline):
        section_number = index + 1
        progress_base = 10 + index * section_progress_span
        section_title = section.get("title") or f"Section {section_number}"
        section_objective = section.get("objective") or section_title
        section_duration_seconds = _get_long_form_section_duration(
            params, section, fallback_section_seconds
        )

        logger.info(
            f"\n\n## long-form section {section_number}/{len(outline)}: {section_title}"
        )
        section_script = llm.generate_csr_training_section_script(
            training_topic=params.video_subject,
            section_title=section_title,
            section_objective=section_objective,
            language=params.video_language,
            scenario_type=getattr(params, "csr_scenario_type", "de-escalation"),
            customer_persona=getattr(
                params, "csr_customer_persona", "frustrated customer"
            ),
            policy_context=getattr(params, "csr_policy_context", ""),
            duration_seconds=section_duration_seconds,
        )
        if not section_script or "Error: " in section_script:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(f"failed to generate section script: {section_title}")
            return
        section_scripts.append({"title": section_title, "script": section_script})
        sm.state.update_task(task_id, progress=progress_base + section_progress_span * 0.1)

        section_params = params.model_copy(deep=True)
        section_params.content_mode = "csr_training"
        section_params.video_subject = f"{params.video_subject}: {section_title}"
        section_params.video_script = section_script
        section_params.video_count = 1
        section_params.csr_duration_seconds = section_duration_seconds
        section_params.custom_audio_file = None
        if type(section_params.video_concat_mode) is str:
            section_params.video_concat_mode = VideoConcatMode(
                section_params.video_concat_mode
            )

        video_terms = ""
        if section_params.video_source != "local":
            video_terms = llm.generate_terms(
                video_subject=section_params.video_subject,
                video_script=section_script,
                amount=5,
            )
            if not video_terms or isinstance(video_terms, str):
                video_terms = [
                    "customer service",
                    "call center",
                    "support agent",
                    "office training",
                    "help desk",
                ]
        section_terms.append({"title": section_title, "terms": video_terms})

        prefix = f"section-{section_number:02d}-"
        audio_file, audio_duration, sub_maker = generate_audio(
            task_id, section_params, section_script, file_prefix=prefix
        )
        if not audio_file:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            return
        sm.state.update_task(task_id, progress=progress_base + section_progress_span * 0.25)

        subtitle_path = generate_subtitle(
            task_id,
            section_params,
            section_script,
            sub_maker,
            audio_file,
            file_prefix=prefix,
        )
        sm.state.update_task(task_id, progress=progress_base + section_progress_span * 0.35)

        downloaded_videos = get_video_materials(
            task_id, section_params, video_terms, audio_duration
        )
        if not downloaded_videos:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            return
        sm.state.update_task(task_id, progress=progress_base + section_progress_span * 0.5)

        combined_video_path = path.join(
            utils.task_dir(task_id), f"section-{section_number:02d}-combined.mp4"
        )
        final_video_path = path.join(
            utils.task_dir(task_id), f"section-{section_number:02d}-final.mp4"
        )

        video.combine_videos(
            combined_video_path=combined_video_path,
            video_paths=downloaded_videos,
            audio_file=audio_file,
            video_aspect=section_params.video_aspect,
            video_concat_mode=section_params.video_concat_mode,
            video_transition_mode=section_params.video_transition_mode,
            max_clip_duration=section_params.video_clip_duration,
            threads=section_params.n_threads,
        )
        section_combined_videos.append(combined_video_path)
        sm.state.update_task(task_id, progress=progress_base + section_progress_span * 0.7)

        video.generate_video(
            video_path=combined_video_path,
            audio_path=audio_file,
            subtitle_path=subtitle_path,
            output_file=final_video_path,
            params=section_params,
        )
        section_final_videos.append(final_video_path)
        section_results.append(
            {
                "title": section_title,
                "script": section_script,
                "terms": video_terms,
                "audio_file": audio_file,
                "audio_duration": audio_duration,
                "subtitle_path": subtitle_path,
                "combined_video": combined_video_path,
                "video": final_video_path,
            }
        )
        sm.state.update_task(task_id, progress=progress_base + section_progress_span * 0.95)

    final_course_path = path.join(utils.task_dir(task_id), "final-long-training.mp4")
    logger.info(f"\n\n## concatenating long-form course => {final_course_path}")
    video.concat_videos_with_audio(
        video_files=section_final_videos,
        output_file=final_course_path,
        threads=params.n_threads,
    )

    script_file = path.join(utils.task_dir(task_id), "long-form-script.json")
    with open(script_file, "w", encoding="utf-8") as f:
        f.write(
            utils.to_json(
                {
                    "outline": outline,
                    "sections": section_scripts,
                    "terms": section_terms,
                    "params": params,
                }
            )
        )

    kwargs = {
        "videos": [final_course_path],
        "combined_videos": section_combined_videos,
        "section_videos": section_final_videos,
        "outline": outline,
        "sections": section_results,
        "script": "\n\n".join(item["script"] for item in section_scripts),
        "terms": section_terms,
        "script_file": script_file,
    }
    sm.state.update_task(
        task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs
    )
    logger.success(
        f"long-form csr training task {task_id} finished, generated {final_course_path}"
    )
    return kwargs


def start(task_id, params: VideoParams, stop_at: str = "video"):
    logger.info(f"start task: {task_id}, stop_at: {stop_at}")
    if getattr(params, "content_mode", "standard") == "csr_long_training":
        if stop_at != "video":
            raise ValueError("csr_long_training mode only supports full video generation")
        return start_long_csr_training(task_id, params)

    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=5)

    # 1. Generate script
    video_script = generate_script(task_id, params)
    if not video_script or "Error: " in video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return

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

    # 6. Generate final videos
    final_video_paths, combined_video_paths = generate_final_videos(
        task_id, params, downloaded_videos, audio_file, subtitle_path
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
        "cross_post_results": cross_post_results if cross_post_results else None,
    }
    sm.state.update_task(
        task_id, state=const.TASK_STATE_COMPLETE, progress=100, **kwargs
    )
    return kwargs


if __name__ == "__main__":
    task_id = "task_id"
    params = VideoParams(
        video_subject="金钱的作用",
        voice_name="zh-CN-XiaoyiNeural-Female",
        voice_rate=1.0,
    )
    start(task_id, params, stop_at="video")
