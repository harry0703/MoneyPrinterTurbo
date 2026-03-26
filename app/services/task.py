import math
import os.path
import re
from os import path

from loguru import logger

from app.config import config
from app.config.config import load_config
from app.models import const
from app.models.schema import Scene, VideoConcatMode, VideoParams
from app.services import llm, material, subtitle, video, voice
from app.services import state as sm
from app.utils import utils

# Helper functions for subtitle time conversion
def _srt_time_to_seconds(time_str):
    """Convert SRT time format to seconds"""
    try:
        # Format: 00:00:00,000
        parts = time_str.split(':')
        if len(parts) == 3:
            hours = int(parts[0])
            minutes = int(parts[1])
            seconds_ms = parts[2].split(',')
            seconds = int(seconds_ms[0])
            milliseconds = int(seconds_ms[1]) if len(seconds_ms) == 2 else 0
            return hours * 3600 + minutes * 60 + seconds + milliseconds / 1000
    except Exception as e:
        logger.error(f"failed to convert SRT time to seconds: {e}")
    return 0

def _seconds_to_srt_time(seconds):
    """Convert seconds to SRT time format"""
    try:
        hours = int(seconds // 3600)
        minutes = int((seconds % 3600) // 60)
        secs = int(seconds % 60)
        milliseconds = int((seconds % 1) * 1000)
        return f"{hours:02d}:{minutes:02d}:{secs:02d},{milliseconds:03d}"
    except Exception as e:
        logger.error(f"failed to convert seconds to SRT time: {e}")
    return "00:00:00,000"


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


def generate_multi_scene_script(task_id, params):
    """
    Generate multi-scene script for video.
    If multi-scene mode is enabled and user provides a subject, generate multi-scene script.
    If user provides a script, convert it to multi-scene format.
    
    Returns:
        Tuple of (script_text, scenes_list)
    """
    logger.info("\n\n## generating multi-scene script")
    
    video_script = params.video_script.strip()
    
    if not video_script:
        # User provided subject only, generate multi-scene script from scratch
        logger.info("generating multi-scene script from subject")
        video_script = llm.generate_multi_scene_script(
            video_subject=params.video_subject,
            language=params.video_language,
            max_scenes=5
        )
    else:
        # User provided script, convert to multi-scene format
        logger.info("converting provided script to multi-scene format")
        video_script = llm.convert_to_multi_scene(
            video_script=video_script,
            video_subject=params.video_subject
        )
    
    if not video_script or "Error: " in video_script:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("failed to generate multi-scene script.")
        return None, None
    
    # Parse the multi-scene script into structured data
    scenes_data = llm.parse_multi_scene_script(video_script)
    
    if not scenes_data:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("failed to parse multi-scene script.")
        return None, None
    
    logger.success(f"generated {len(scenes_data)} scenes")
    return video_script, scenes_data


def generate_scene_terms(task_id, params, scenes):
    """
    Generate search terms for each scene.
    
    Args:
        task_id: Task ID
        params: Video parameters
        scenes: List of scene dictionaries
    
    Returns:
        List of terms for each scene
    """
    logger.info("\n\n## generating terms for each scene")
    
    scene_terms_list = []
    for i, scene in enumerate(scenes):
        logger.info(f"generating terms for scene {i+1}/{len(scenes)}: {scene.get('title', '')}")
        
        terms = llm.generate_scene_terms(
            video_subject=params.video_subject,
            scene_script=scene.get('script', ''),
            scene_camera=scene.get('camera', ''),
            amount=5
        )
        
        if terms and not (isinstance(terms, str) and "Error: " in terms):
            # Ensure video subject is included in keywords
            subject_lower = params.video_subject.lower()
            terms_lower = [term.lower() for term in terms]
            if subject_lower not in terms_lower:
                # Add video subject to terms if not already present
                terms.insert(0, params.video_subject)
                # Limit to amount terms
                terms = terms[:5]
            scene_terms_list.append(terms)
            scene['keywords'] = terms
            logger.success(f"scene {i+1} terms: {terms}")
        else:
            logger.warning(f"failed to generate terms for scene {i+1}, using default terms")
            default_terms = [params.video_subject, "video", "content"]
            scene_terms_list.append(default_terms)
            scene['keywords'] = default_terms
    
    return scene_terms_list


def process_scene(task_id, params, scene, scene_index, total_scenes):
    """
    Process a single scene:
    1. Generate audio for scene
    2. Generate subtitle for scene
    3. Get video materials for scene
    4. Combine scene video clip (without BGM)
    
    Args:
        task_id: Task ID
        params: Video parameters
        scene: Scene dictionary
        scene_index: Index of this scene (0-based)
        total_scenes: Total number of scenes
    
    Returns:
        Scene result dictionary with video clip path, audio path, subtitle path
    """
    scene_num = scene_index + 1
    logger.info(f"\n\n## processing scene {scene_num}/{total_scenes}: {scene.get('title', '')}")
    
    scene_id = scene.get('id', f'scene_{scene_num}')
    scene_script = scene.get('script', '')
    scene_keywords = scene.get('keywords', [])
    
    logger.info(f"scene {scene_num}: scene_id={scene_id}, script={scene_script[:50]}...")
    
    # Create scene-specific directory
    scene_dir = path.join(utils.task_dir(task_id), scene_id)
    os.makedirs(scene_dir, exist_ok=True)
    
    # 1. Generate audio for scene
    logger.info(f"generating audio for scene {scene_num}")
    audio_file = path.join(scene_dir, "audio.mp3")
    logger.info(f"scene {scene_num}: audio_file={audio_file}")
    sub_maker = voice.tts(
        text=scene_script,
        voice_name=voice.parse_voice_name(params.voice_name),
        voice_rate=params.voice_rate,
        voice_file=audio_file,
        emotion=getattr(params, 'voice_emotion', ''),
        is_preview=False,
    )
    
    if not sub_maker and not os.path.exists(audio_file):
        logger.error(f"failed to generate audio for scene {scene_num}")
        return None
    
    # Get audio duration
    if sub_maker is None and os.path.exists(audio_file):
        audio_duration = voice.get_audio_duration(audio_file)
    else:
        audio_duration = voice.get_audio_duration(sub_maker)
    
    if audio_duration == 0:
        logger.error(f"failed to get audio duration for scene {scene_num}")
        return None
    
    logger.success(f"scene {scene_num} audio duration: {audio_duration:.2f}s")
    
    # 2. Generate subtitle for scene
    logger.info(f"generating subtitle for scene {scene_num}")
    subtitle_path = ""
    if params.subtitle_enabled:
        subtitle_path = path.join(scene_dir, "subtitle.srt")
        logger.info(f"scene {scene_num}: subtitle path: {subtitle_path}")
        subtitle_provider = config.app.get("subtitle_provider", "edge").strip().lower()
        
        subtitle_fallback = False
        if sub_maker is None:
            logger.info(f"scene {scene_num}: sub_maker is None, using Whisper")
            subtitle_fallback = True
        elif subtitle_provider == "edge":
            voice.create_subtitle(
                text=scene_script, sub_maker=sub_maker, subtitle_file=subtitle_path
            )
            if not os.path.exists(subtitle_path):
                subtitle_fallback = True
        
        if subtitle_provider == "whisper" or subtitle_fallback:
            logger.info(f"scene {scene_num}: using Whisper to generate subtitle from audio file: {audio_file}")
            logger.info(f"scene {scene_num}: audio file exists: {os.path.exists(audio_file)}, size: {os.path.getsize(audio_file) if os.path.exists(audio_file) else 0} bytes")
            logger.info(f"scene {scene_num}: scene_script for subtitle: {scene_script[:100]}...")
            try:
                subtitle.create(audio_file=audio_file, subtitle_file=subtitle_path)
                if os.path.exists(subtitle_path):
                    subtitle.correct(subtitle_file=subtitle_path, video_script=scene_script)
            except Exception as e:
                logger.error(f"scene {scene_num}: failed to generate subtitle with Whisper: {str(e)}")
                subtitle_fallback = True
        
        if not os.path.exists(subtitle_path):
            logger.warning(f"scene {scene_num}: subtitle file not found")
            # Fallback: create subtitle from script directly
            try:
                logger.info(f"scene {scene_num}: creating subtitle from script directly")
                # Split script into lines
                script_lines = utils.split_string_by_punctuations(scene_script)
                script_lines = [line.strip() for line in script_lines if line.strip()]
                
                if script_lines:
                    # Create subtitle file with simple timing
                    with open(subtitle_path, 'w', encoding='utf-8') as f:
                        start_time = 0.0
                        for i, line in enumerate(script_lines):
                            # Calculate end time (approx 2 seconds per line)
                            end_time = start_time + 2.0
                            # Format time for SRT
                            def format_time(seconds):
                                hours = int(seconds // 3600)
                                minutes = int((seconds % 3600) // 60)
                                secs = int(seconds % 60)
                                ms = int((seconds % 1) * 1000)
                                return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"
                            
                            # Write subtitle entry
                            f.write(f"{i+1}\n")
                            f.write(f"{format_time(start_time)} --> {format_time(end_time)}\n")
                            f.write(f"{line}\n\n")
                            
                            # Update start time for next line
                            start_time = end_time
                    
                    logger.success(f"scene {scene_num}: subtitle file created from script: {subtitle_path}")
                else:
                    logger.warning(f"scene {scene_num}: script is empty, cannot create subtitle")
                    subtitle_path = ""
            except Exception as e:
                logger.error(f"scene {scene_num}: failed to create subtitle from script: {e}")
                subtitle_path = ""
        else:
            logger.success(f"scene {scene_num}: subtitle file created: {subtitle_path}")
    
    # 3. Get video materials for scene
    logger.info(f"getting video materials for scene {scene_num}")
    downloaded_videos = []
    
    if params.video_source == "local":
        # For local source, use the same materials for all scenes
        # This could be enhanced to support scene-specific material selection
        materials = video.preprocess_video(
            materials=params.video_materials, clip_duration=params.video_clip_duration
        )
        if materials:
            downloaded_videos = [m.url for m in materials]
    else:
        # Download videos based on scene keywords
        downloaded_videos = material.download_videos(
            task_id=task_id,
            search_terms=scene_keywords,
            source=params.video_source,
            video_aspect=params.video_aspect,
            video_concat_mode=params.video_concat_mode,
            audio_duration=audio_duration,
            max_clip_duration=params.video_clip_duration,
        )
    
    if not downloaded_videos:
        logger.error(f"failed to get video materials for scene {scene_num}")
        return None
    
    logger.success(f"scene {scene_num}: downloaded {len(downloaded_videos)} video clips")
    
    # 4. Combine scene video clip (without BGM)
    logger.info(f"combining video clip for scene {scene_num}")
    combined_video_path = path.join(scene_dir, "combined.mp4")
    
    result = video.combine_videos(
        combined_video_path=combined_video_path,
        video_paths=downloaded_videos,
        audio_file=audio_file,
        video_aspect=params.video_aspect,
        video_concat_mode=params.video_concat_mode,
        video_transition_mode=params.video_transition_mode,
        max_clip_duration=params.video_clip_duration,
        threads=params.n_threads,
        scene_info=f"(scene {scene_num}/{total_scenes})")
    
    if result is None or not os.path.exists(combined_video_path):
        logger.error(f"failed to combine video for scene {scene_num}")
        return None
    
    logger.success(f"scene {scene_num}: video clip created")
    
    # Return scene result
    return {
        "scene_id": scene_id,
        "scene_index": scene_index,
        "audio_file": audio_file,
        "audio_duration": audio_duration,
        "subtitle_path": subtitle_path,
        "combined_video_path": combined_video_path,
    }


def combine_all_scenes(task_id, params, scene_results):
    """
    Combine all scene clips into final video with background music.
    
    Args:
        task_id: Task ID
        params: Video parameters
        scene_results: List of scene result dictionaries
    
    Returns:
        Final video path (temp file without BGM, will be processed by generate_video)
    """
    logger.info("\n\n## combining all scenes into final video")
    
    # Collect all scene video clips
    scene_clips = []
    for result in scene_results:
        if result and os.path.exists(result.get('combined_video_path', '')):
            scene_clips.append(result['combined_video_path'])
    
    if not scene_clips:
        logger.error("no scene clips available for final combination")
        return None
    
    logger.info(f"combining {len(scene_clips)} scene clips")
    
    # Concatenate all scene clips to a temp file (without BGM, will be processed later)
    temp_video_path = path.join(utils.task_dir(task_id), "temp_combined_scenes.mp4")
    
    # Use moviepy to concatenate videos
    from moviepy import VideoFileClip, concatenate_videoclips
    
    try:
        clips = []
        for clip_path in scene_clips:
            logger.info(f"loading scene clip: {clip_path}")
            clip = VideoFileClip(clip_path)
            logger.info(f"clip duration: {clip.duration}s, size: {clip.size}")
            clips.append(clip)
        
        # Concatenate all clips using chain method for proper sequential concatenation
        logger.info(f"concatenating {len(clips)} clips")
        final_clip = concatenate_videoclips(clips, method="chain")
        logger.info(f"final clip duration: {final_clip.duration}s")
        
        # Get video encoding parameters (loaded once at module initialization)
        video_encoding_params = video.get_video_encoding_params()
        logger.info(f"using video encoding params: bitrate={video_encoding_params['bitrate']}, preset={video_encoding_params['preset']}, crf={video_encoding_params['crf']}, codec={video.video_codec}")
        
        # Build ffmpeg parameters
        ffmpeg_params = ["-pix_fmt", "yuv420p"]
        if video_encoding_params["crf"] is not None:
            ffmpeg_params.extend(["-crf", str(video_encoding_params["crf"])])
        
        # Write temp video with audio
        final_clip.write_videofile(
            temp_video_path,
            codec=video.video_codec,
            audio_codec="aac",
            fps=video.fps,
            bitrate=video_encoding_params["bitrate"],
            preset=video_encoding_params["preset"],
            logger=None,
            ffmpeg_params=ffmpeg_params,
        )
        
        # Close clips to free memory
        for clip in clips:
            clip.close()
        final_clip.close()
        
        logger.success(f"combined scenes created: {temp_video_path}")
        return temp_video_path
        
    except Exception as e:
        logger.error(f"failed to combine scenes: {e}")
        return None


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
    custom_audio_file = params.custom_audio_file
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
            emotion=getattr(params, 'voice_emotion', ''),
        )
        # 检查音频文件是否存在，即使sub_maker为None（如Coze预览音频的情况）
        if sub_maker is None and not os.path.exists(audio_file):
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error(
                """failed to generate audio:
1. check if the language of the voice matches the language of the video script.
2. check if the network is available. If you are in China, it is recommended to use a VPN and enable the global traffic mode.
            """.strip()
            )
            return None, None, None
        # 获取音频时长
        if sub_maker is None and os.path.exists(audio_file):
            # 使用音频文件路径获取时长
            audio_duration = voice.get_audio_duration(audio_file)
        else:
            # 使用sub_maker获取时长
            audio_duration = voice.get_audio_duration(sub_maker)
        if audio_duration == 0:
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            logger.error("failed to get audio duration.")
            return None, None, None
        logger.info(f"audio duration: {audio_duration:.2f}s")
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
    If subtitle generation is disabled, it will return an empty string.
    If no subtitle maker is provided (sub_maker is None), it will use Whisper to generate subtitle.
    Otherwise, it will generate the subtitle using the specified provider.
    Returns:
        - subtitle_path: path to the generated subtitle file
    '''
    logger.info("\n\n## generating subtitle")
    if not params.subtitle_enabled:
        return ""

    subtitle_path = path.join(utils.task_dir(task_id), "subtitle.srt")
    subtitle_provider = config.app.get("subtitle_provider", "edge").strip().lower()
    logger.info(f"\n\n## generating subtitle, provider: {subtitle_provider}")

    subtitle_fallback = False
    
    # 如果sub_maker为None（如Coze TTS），直接使用Whisper生成字幕
    if sub_maker is None:
        logger.info("sub_maker is None, using Whisper to generate subtitle")
        subtitle_fallback = True
    elif subtitle_provider == "edge":
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
            scene_info=f"(video {index}/{params.video_count})"
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


def start(task_id, params: VideoParams, stop_at: str = "video"):
    # Create task log file
    task_log_path = os.path.join(utils.task_dir(task_id), "task.log")
    # Add file handler to logger
    log_handler_id = logger.add(
        task_log_path,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {file}:{line} | {message}",
        level="INFO",
        rotation="10 MB",
        compression="zip"
    )
    
    # Log GPU configuration for video codec
    from app.config import config
    use_gpu = config.app.get("use_gpu", False)
    logger.info(f"GPU configuration for video codec: use_gpu={use_gpu}")
    
    logger.info(f"start task: {task_id}, stop_at: {stop_at}")
    logger.info(f"Task log file created: {task_log_path}")
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=5)

    if type(params.video_concat_mode) is str:
        params.video_concat_mode = VideoConcatMode(params.video_concat_mode)

    # Unified multi-scene architecture - always use multi-scene flow
    # The old single-scene mode is mapped to a single scene in multi-scene architecture
    logger.info("using unified multi-scene architecture")
    try:
        return start_multi_scene(task_id, params, stop_at)
    finally:
        # Remove the file handler to release the log file
        try:
            logger.remove(log_handler_id)
            logger.info(f"Task log file closed: {task_log_path}")
        except ValueError:
            # Handler already removed, ignore
            pass


def start_single_scene(task_id, params: VideoParams, stop_at: str = "video"):
    """Original single-scene video generation flow."""
    logger.info("using single-scene mode")
    
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


def start_multi_scene(task_id, params: VideoParams, stop_at: str = "video"):
    """Multi-scene video generation flow."""
    logger.info("using multi-scene mode")
    
    # 1. Generate multi-scene script
    video_script, scenes = generate_multi_scene_script(task_id, params)
    if not video_script or not scenes:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return
    
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=10)
    
    if stop_at == "script":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, script=video_script
        )
        return {"script": video_script, "scenes": scenes}
    
    # 2. Generate terms for each scene
    scene_terms_list = generate_scene_terms(task_id, params, scenes)
    if not scene_terms_list:
        logger.warning("failed to generate scene terms, continuing with defaults")
    
    save_script_data(task_id, video_script, scene_terms_list, params)
    
    if stop_at == "terms":
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, terms=scene_terms_list
        )
        return {"script": video_script, "terms": scene_terms_list, "scenes": scenes}
    
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)
    
    # 3. Process each scene
    total_scenes = len(scenes)
    scene_results = []
    
    for i, scene in enumerate(scenes):
        progress = 20 + (i / total_scenes) * 40  # Progress from 20% to 60%
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=int(progress))
        
        result = process_scene(task_id, params, scene, i, total_scenes)
        if result:
            scene_results.append(result)
        else:
            logger.error(f"failed to process scene {i+1}, skipping")
    
    if not scene_results:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error("no scenes were successfully processed")
        return
    
    logger.success(f"successfully processed {len(scene_results)}/{total_scenes} scenes")
    
    if stop_at == "audio":
        # Return audio info from first scene as representative
        if scene_results:
            first_scene = scene_results[0]
            return {
                "audio_file": first_scene.get("audio_file"),
                "audio_duration": first_scene.get("audio_duration"),
                "scenes": scenes,
                "scene_results": scene_results
            }
        return {"scenes": scenes, "scene_results": scene_results}
    
    if stop_at == "subtitle":
        return {"scenes": scenes, "scene_results": scene_results}
    
    if stop_at == "materials":
        return {"scenes": scenes, "scene_results": scene_results}
    
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=70)
    
    # 4. Combine all scenes into final video
    final_video_path = combine_all_scenes(task_id, params, scene_results)
    if not final_video_path:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return
    
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=90)
    
    # 5. Add background music and final processing for multi-scene video
    final_output_path = path.join(utils.task_dir(task_id), "final-1.mp4")
    
    # For multi-scene mode, we need to add BGM to the combined video
    # The combined video already has all scene audio, so we just need to add BGM
    logger.info("adding background music to multi-scene video")
    
    try:
        from moviepy import VideoFileClip, AudioFileClip, CompositeAudioClip, afx
        import app.services.video as video_module
        
        # Load the combined video (which already has all scene audio)
        video_clip = VideoFileClip(final_video_path)
        logger.info(f"loaded combined video, duration: {video_clip.duration}s")
        
        # Get BGM file
        bgm_file = video_module.get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
        
        if bgm_file:
            try:
                # Load and process BGM
                bgm_clip = AudioFileClip(bgm_file).with_effects([
                    afx.MultiplyVolume(params.bgm_volume),
                    afx.AudioFadeOut(3),
                    afx.AudioLoop(duration=video_clip.duration),
                ])
                
                # Get existing audio from video
                existing_audio = video_clip.audio
                
                # Combine existing audio with BGM
                combined_audio = CompositeAudioClip([existing_audio, bgm_clip])
                video_clip = video_clip.with_audio(combined_audio)
                
                logger.success("BGM added to multi-scene video")
            except Exception as e:
                logger.error(f"failed to add BGM: {str(e)}")
        
        # Add subtitle if enabled
        if params.subtitle_enabled and scene_results:
            # Collect all scene subtitles and adjust timestamps
            all_subtitles = []
            current_offset = 0
            
            for scene_result in scene_results:
                scene_subtitle = scene_result.get("subtitle_path")
                scene_video = scene_result.get("combined_video_path")
                
                # Get scene duration - always get this, even if no subtitle
                scene_duration = 0
                try:
                    if scene_video and os.path.exists(scene_video):
                        clip = VideoFileClip(scene_video)
                        scene_duration = clip.duration
                        # Use close_clip function for proper cleanup
                        from app.services import video as video_module
                        video_module.close_clip(clip)
                    else:
                        scene_duration = scene_result.get("audio_duration", 0)
                except Exception as e:
                    logger.error(f"failed to get scene duration: {e}")
                    scene_duration = scene_result.get("audio_duration", 0)
                
                # Process subtitles if available
                if scene_subtitle and os.path.exists(scene_subtitle):
                    try:
                        from app.services import subtitle
                        scene_subs = subtitle.file_to_subtitles(scene_subtitle)
                        logger.info(f"scene {scene_result.get('scene_index', 0) + 1}: loaded {len(scene_subs)} subtitles from {scene_subtitle}")
                        
                        # Adjust timestamps and add to all_subtitles
                        for sub in scene_subs:
                            index, time_str, text = sub
                            # Parse time string
                            start_end = time_str.split(" --> ")
                            if len(start_end) == 2:
                                # Convert to seconds and add offset
                                start_time = _srt_time_to_seconds(start_end[0]) + current_offset
                                end_time = _srt_time_to_seconds(start_end[1]) + current_offset
                                # Convert back to SRT format
                                new_time_str = f"{_seconds_to_srt_time(start_time)} --> {_seconds_to_srt_time(end_time)}"
                                all_subtitles.append((len(all_subtitles) + 1, new_time_str, text))
                    except Exception as e:
                        logger.error(f"failed to process scene subtitle: {e}")
                else:
                    logger.warning(f"scene {scene_result.get('scene_index', 0) + 1}: subtitle file not found or does not exist: {scene_subtitle}")
                
                # Update offset for next scene
                current_offset += scene_duration
            
            # Create merged subtitle file if we have subtitles
            merged_subtitle_path = None
            if all_subtitles:
                merged_subtitle_path = path.join(utils.task_dir(task_id), "merged_subtitle.srt")
                try:
                    with open(merged_subtitle_path, "w", encoding="utf-8") as f:
                        for sub in all_subtitles:
                            f.write(f"{sub[0]}\n")
                            f.write(f"{sub[1]}\n")
                            f.write(f"{sub[2]}\n\n")
                    logger.info(f"merged subtitle file created: {merged_subtitle_path}")
                    logger.info(f"total subtitles merged: {len(all_subtitles)}")
                except Exception as e:
                    logger.error(f"failed to create merged subtitle file: {e}")
                    merged_subtitle_path = None
            
            # Use merged subtitle if available, otherwise fall back to first scene
            if merged_subtitle_path and os.path.exists(merged_subtitle_path):
                subtitle_path = merged_subtitle_path
                logger.info(f"using merged subtitle file: {subtitle_path}")
            else:
                subtitle_path = scene_results[0].get("subtitle_path")
                logger.warning(f"merged subtitle not available, falling back to first scene subtitle: {subtitle_path}")
            
            if subtitle_path and os.path.exists(subtitle_path):
                logger.info("adding subtitle to multi-scene video")
                try:
                    from moviepy import TextClip, CompositeVideoClip
                    from moviepy.video.tools.subtitles import SubtitlesClip
                    import app.services.subtitle as subtitle_module
                    
                    # Load font
                    font_path = ""
                    if not params.font_name:
                        params.font_name = "STHeitiMedium.ttc"
                    font_path = os.path.join(utils.font_dir(), params.font_name)
                    if os.name == "nt":
                        font_path = font_path.replace("\\", "/")
                    
                    # Load subtitles
                    subtitle_lines = subtitle_module.file_to_subtitles(subtitle_path)
                    if subtitle_lines:
                        logger.info(f"Loaded {len(subtitle_lines)} subtitles from {subtitle_path}")
                        
                        # Create text clips
                        text_clips = []
                        video_width, video_height = video_clip.size
                        
                        # Check if font file exists
                        if not os.path.exists(font_path):
                            logger.warning(f"Font file not found: {font_path}, using default font")
                            font_path = None  # Use default font
                        
                        # Use subtitle_lines directly
                        for i, (index, time_str, text) in enumerate(subtitle_lines):
                            phrase = text
                            logger.debug(f"Processing subtitle {i+1}: {phrase[:50]}...")
                            
                            # Get subtitle margin from config (default 0.05 = 5% on each side)
                            # Reload config to get latest values
                            _cfg = load_config()
                            ui_config = _cfg.get("ui", {})
                            subtitle_margin = ui_config.get("subtitle_margin", 0.05)
                            max_width = video_width * (1 - 2 * subtitle_margin)
                            
                            try:
                                # Wrap text to fit within video width
                                wrapped_txt, txt_height = video_module.wrap_text(
                                    phrase, max_width=max_width, font=font_path if font_path else "Arial", fontsize=int(params.font_size)
                                )
                                
                                # Parse time string
                                start_end = time_str.split(" --> ")
                                if len(start_end) == 2:
                                    # Convert to seconds
                                    start_time = _srt_time_to_seconds(start_end[0])
                                    end_time = _srt_time_to_seconds(start_end[1])
                                    
                                    # Create text clip with proper encoding
                                    try:
                                        _clip = TextClip(
                                            text=wrapped_txt,
                                            font=font_path,
                                            font_size=int(params.font_size),
                                            color=params.text_fore_color,
                                            bg_color=params.text_background_color,
                                            stroke_color=params.stroke_color,
                                            stroke_width=int(params.stroke_width),
                                            method='label'  # Use label method for better text rendering
                                        )
                                        
                                        duration = end_time - start_time
                                        _clip = _clip.with_start(start_time)
                                        _clip = _clip.with_end(end_time)
                                        _clip = _clip.with_duration(duration)
                                        
                                        # Position subtitle
                                        if params.subtitle_position == "bottom":
                                            _clip = _clip.with_position(("center", video_height * 0.95 - _clip.h))
                                        elif params.subtitle_position == "top":
                                            _clip = _clip.with_position(("center", video_height * 0.05))
                                        elif params.subtitle_position == "custom":
                                            margin = 10
                                            max_y = video_height - _clip.h - margin
                                            min_y = margin
                                            custom_y = (video_height - _clip.h) * (params.custom_position / 100)
                                            custom_y = max(min_y, min(custom_y, max_y))
                                            _clip = _clip.with_position(("center", custom_y))
                                        else:  # center
                                            _clip = _clip.with_position(("center", "center"))
                                        
                                        text_clips.append(_clip)
                                        logger.debug(f"Created text clip for subtitle {i+1}")
                                    except Exception as e:
                                        logger.error(f"Failed to create text clip: {e}")
                            except Exception as e:
                                logger.error(f"Failed to process subtitle {i+1}: {e}")
                        
                        # Composite video with subtitles
                        if text_clips:
                            logger.info(f"Adding {len(text_clips)} text clips to video")
                            try:
                                video_clip = CompositeVideoClip([video_clip, *text_clips])
                                logger.success("subtitle added to multi-scene video")
                            except Exception as e:
                                logger.error(f"Failed to composite video with subtitles: {e}")
                        else:
                            logger.warning("No text clips created, skipping subtitle addition")
                except Exception as e:
                    logger.error(f"failed to add subtitle: {str(e)}")
        
        # Write final video
        logger.info(f"writing final video to: {final_output_path}")
        
        # Get video encoding parameters (loaded once at module initialization)
        video_encoding_params = video_module.get_video_encoding_params()
        logger.info(f"using video encoding params: bitrate={video_encoding_params['bitrate']}, preset={video_encoding_params['preset']}, crf={video_encoding_params['crf']}, codec={video_module.video_codec}")
        
        # Build ffmpeg parameters
        ffmpeg_params = ["-pix_fmt", "yuv420p"]
        if video_encoding_params["crf"] is not None:
            ffmpeg_params.extend(["-crf", str(video_encoding_params["crf"])])
        
        video_clip.write_videofile(
            final_output_path,
            codec=video_module.video_codec,
            audio_codec="aac",
            fps=video_module.fps,
            bitrate=video_encoding_params["bitrate"],
            preset=video_encoding_params["preset"],
            logger=None,
            ffmpeg_params=ffmpeg_params,
        )
        # Use close_clip function for proper cleanup
        video_module.close_clip(video_clip)
        
        logger.success(f"final video created: {final_output_path}")
        
    except Exception as e:
        logger.error(f"failed to generate final multi-scene video: {e}")
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return
    
    logger.success(f"task {task_id} finished, generated multi-scene video")
    
    # Collect all scene clips for reference
    combined_video_paths = [r.get("combined_video_path") for r in scene_results if r]
    
    kwargs = {
        "videos": [final_output_path],
        "combined_videos": combined_video_paths,
        "script": video_script,
        "terms": scene_terms_list,
        "scenes": scenes,
        "scene_results": scene_results,
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
