import math
import os.path
import re
from os import path

from loguru import logger

from app.config import config
from app.models import const
from app.models.schema import (
    VideoConcatMode,
    VideoParams,
    VideoAspect,
    MaterialInfo,
    VideoSegment,
)
from app.services import llm, material, subtitle, voice, video
from app.services import video as video_utils
from app.services import state as sm
from app.utils import utils
import time

# ... 您已有的 start 函数 ...

# ===================================================================
# 新增的、实现音画同步的主任务函数
# ===================================================================
def start_storyboard_task(task_id, params: VideoParams):
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING)
    workdir = utils.task_dir(task_id)

    # 1. Generate Storyboard
    logger.info("--- Step 1: Generating Storyboard ---")
    video_script = params.video_script
    if not video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, status_message="Video script is empty.")
        return

    storyboard = llm.generate_storyboard(params.video_subject, video_script)
    if not storyboard:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, status_message="Failed to generate storyboard.")
        return

    # 2. Process each segment
    logger.info(f"--- Step 2: Processing {len(storyboard)} video segments ---")
    segment_video_paths = []
    segment_audio_paths = []
    segment_srt_paths = []
    total_duration = 0
    last_used_keywords = set()

    for i, segment in enumerate(storyboard):
        try:
            logger.info(f"--- Processing segment {i + 1} ---")
            segment_script = segment.get("script")
            if not segment_script:
                logger.warning(f"Segment {i + 1} has no script, skipping")
                continue

            search_terms_str = segment.get("search_terms", "")
            search_terms = [term.strip() for term in search_terms_str.split(',') if term.strip()]
            if not search_terms:
                logger.warning(f"Segment {i + 1} has no search terms, skipping")
                continue

            # Keyword Guard: Check for repetitive keywords
            current_keywords = set(search_terms)
            if i > 0 and current_keywords == last_used_keywords:
                logger.warning(f"Segment {i + 1} uses the same keywords as the previous one ({search_terms_str}). Reusing last video clip to avoid visual repetition.")
                if segment_video_paths:
                    segment_video_paths.append(segment_video_paths[-1]) # Reuse the last processed video clip
                    segment_audio_paths.append(segment_audio_paths[-1]) # Reuse the last audio clip
                    continue # Skip processing for this segment

            last_used_keywords = current_keywords

            # a. Generate audio and subtitles for the segment
            segment_audio_file = path.join(workdir, f"segment_{i + 1}.mp3")
            segment_srt_file = path.join(workdir, f"segment_{i + 1}.srt")
            sub_maker = voice.tts(
                text=segment_script,
                voice_name=voice.parse_voice_name(params.voice_name),
                voice_rate=params.voice_rate,
                voice_file=segment_audio_file,
            )
            if not sub_maker:
                raise Exception(f"Failed to generate audio for segment {i + 1}")

            # Trim silence from the generated audio
            trimmed_audio_file = path.join(workdir, f"segment_{i + 1}_trimmed.mp3")
            if voice.trim_audio_silence(segment_audio_file, trimmed_audio_file):
                logger.info(f"Silence trimmed for segment {i+1}, using trimmed audio.")
                audio_to_process = trimmed_audio_file
            else:
                logger.warning(f"Failed to trim silence for segment {i+1}, using original audio.")
                audio_to_process = segment_audio_file

            voice.create_subtitle(
                sub_maker=sub_maker, text=segment_script, subtitle_file=segment_srt_file
            )
            audio_duration = video.get_video_duration(audio_to_process)
            total_duration += audio_duration

            # b. Calculate the number of clips needed and download them
            num_clips = math.ceil(audio_duration / params.max_clip_duration) if params.max_clip_duration > 0 else 1
            logger.info(f"Segment {i+1} audio duration: {audio_duration:.2f}s, max_clip_duration: {params.max_clip_duration}s. Calculated number of clips: {num_clips}")

            video_materials = material.download_videos_for_clips(
                video_search_terms=search_terms,
                num_clips=num_clips,
                source=params.video_source
            )
            if not video_materials or len(video_materials) < num_clips:
                sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, status_message=f"Failed to download enough video materials for segment {i + 1}")
                return

            # c. Create video clip by combining materials with precise durations
            video_segments = []
            remaining_audio_duration = audio_duration
            for video_material in video_materials:
                if remaining_audio_duration <= 0:
                    break
                clip_duration = min(remaining_audio_duration, params.max_clip_duration)
                video_segments.append(VideoSegment(path=video_material.path, duration=clip_duration))
                remaining_audio_duration -= clip_duration

            # If the total duration of the clips is still less than the audio duration, adjust the last clip
            if remaining_audio_duration > 0.01 and video_segments:
                video_segments[-1].duration += remaining_audio_duration

            segment_video_path = os.path.join(workdir, f"segment_video_{i + 1}.mp4")
            video_created = video.create_video_clip_from_segments(
                segments=video_segments,
                video_aspect=params.video_aspect,
                output_path=segment_video_path
            )

            if not video_created:
                sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, status_message=f"Video clip creation failed for segment {i + 1}")
                return

            segment_video_paths.append(segment_video_path)
            segment_audio_paths.append(audio_to_process)
            segment_srt_paths.append(segment_srt_file)

        except Exception as e:
            logger.error(f"Error processing segment {i + 1}: {e}")
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, status_message=f"Error in segment {i + 1}: {e}")
            return

    # Check if any segments were processed
    if not segment_video_paths:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, status_message="Failed to process any segments.")
        logger.error("Failed to process any segments. Aborting video generation.")
        return

    # 3. Combine all segments
    logger.info("--- Step 3: Combining all video segments ---")
    # a. Combine audios
    combined_audio_path = path.join(workdir, "voice.mp3")
    if not voice.combine_audio_files(segment_audio_paths, combined_audio_path):
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, status_message="Failed to combine audio files.")
        return

    # b. Combine videos
    video_transition_mode = params.video_transition_mode
    concatenated_video_path = path.join(workdir, "concatenated_video.mp4")
    if not video.concatenate_videos(segment_video_paths, concatenated_video_path, transition_mode=video_transition_mode):
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, status_message="Failed to concatenate videos.")
        return

    # c. Combine subtitles
    combined_srt_path = path.join(workdir, "subtitles.srt")
    subtitle.combine_srt_files(segment_srt_paths, combined_srt_path)

    # 4. Final video assembly
    logger.info("--- Step 4: Final video assembly ---")
    # a. Add audio to concatenated video
    video_with_audio_path = path.join(workdir, "video_with_audio.mp4")
    if not video.add_audio_to_video(concatenated_video_path, combined_audio_path, video_with_audio_path):
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, status_message="Failed to add audio to video.")
        return

    # b. Add background music
    video_with_bgm_path = path.join(workdir, "video_with_bgm.mp4")
    bgm_file = video.get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
    if bgm_file:
        if not video.add_bgm_to_video(
            input_video_path=video_with_audio_path,
            bgm_path=bgm_file,
            bgm_volume=params.bgm_volume,
            output_video_path=video_with_bgm_path
        ):
            logger.warning("Failed to mix BGM. Proceeding without it.")
            video_with_bgm_path = video_with_audio_path # Fallback
    else:
        video_with_bgm_path = video_with_audio_path # No BGM requested

    # c. Add subtitles
    final_video_path = path.join(workdir, f"final_{task_id}.mp4")
    # video.add_subtitles_to_video(
    #     video_path=video_with_bgm_path,
    #     srt_path=combined_srt_path,
    #     font_name=params.font_name,
    #     font_size=params.font_size,
    #     text_fore_color=params.text_fore_color,
    #     stroke_color=params.stroke_color,
    #     stroke_width=params.stroke_width,
    #     subtitle_position=params.subtitle_position,
    #     custom_position=params.custom_position,
    #     output_path=final_video_path
    # )
    import shutil
    shutil.copy(video_with_bgm_path, final_video_path)

    # 5. Cleanup
    logger.info("--- Step 5: Cleaning up temporary files ---")
    cleanup_files = segment_video_paths + segment_audio_paths + segment_srt_paths + [combined_audio_path, concatenated_video_path, combined_srt_path, video_with_audio_path, video_with_bgm_path]
    for item in cleanup_files:
        if item and item != final_video_path and os.path.exists(item):
            os.remove(item)

    sm.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100, video_path=final_video_path)
    logger.success(f"Task {task_id} completed successfully. Final video: {final_video_path}")



    return {"videos": [final_video_path]}


def generate_script(task_id, params):
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


def generate_terms(task_id, params, video_script):
    logger.info("\n\n## generating video terms")
    video_terms = params.video_terms
    if not video_terms:
        video_terms = llm.generate_terms(
            video_subject=params.video_subject, video_script=video_script
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


def generate_audio(task_id, params, video_script):
    logger.info("\n\n## generating audio")
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
    return audio_file, audio_duration, sub_maker


def generate_subtitle(task_id, params, video_script, sub_maker, audio_file):
    if not params.subtitle_enabled:
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


def get_video_materials(task_id, params, video_terms, audio_duration):
    if params.video_source == "local":
        logger.info("\n\n## preprocess local materials")
        materials = video.preprocess_video(
            materials=params.video_materials, clip_duration=params.max_clip_duration
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
            video_subject=params.video_subject,
            search_terms=video_terms,
            source=params.video_source,
            video_aspect=params.video_aspect,
            video_contact_mode=params.video_concat_mode,
            audio_duration=audio_duration * params.video_count,
            max_clip_duration=params.max_clip_duration,
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
        video_utils.combine_videos_ffmpeg(
            combined_video_path=combined_video_path,
            video_paths=downloaded_videos,
            audio_file=audio_file,
            video_aspect=params.video_aspect,
            video_concat_mode=video_concat_mode,
            video_transition_mode=video_transition_mode,
            max_clip_duration=params.max_clip_duration,
            threads=params.n_threads,
        )

        _progress += 50 / params.video_count / 2
        sm.state.update_task(task_id, progress=_progress)

        final_video_path = path.join(utils.task_dir(task_id), f"final-{index}.mp4")

        logger.info(f"\n\n## generating video: {index} => {final_video_path}")
        video_utils.generate_video(
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


def start(task_id, params: VideoParams, stop_at: str = "video"):
    logger.info(f"start task: {task_id}, stop_at: {stop_at}")
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=5)

    if type(params.video_concat_mode) is str:
        params.video_concat_mode = VideoConcatMode(params.video_concat_mode)

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

    kwargs = {
        "videos": final_video_paths,
        "combined_videos": combined_video_paths,
        "script": video_script,
        "terms": video_terms,
        "audio_file": audio_file,
        "audio_duration": audio_duration,
        "subtitle_path": subtitle_path,
        "materials": downloaded_videos,
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
