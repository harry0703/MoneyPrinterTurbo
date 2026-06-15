import ast
import math
import os.path
import time
import logging
from os import path

# Set moviepy and imageio logging level to WARNING to suppress detailed metadata logs
logging.basicConfig(level=logging.WARNING)
for logger_name in ['moviepy', 'imageio', 'imageio_ffmpeg', 'ffmpeg', 'PIL']:
    logging.getLogger(logger_name).setLevel(logging.WARNING)

# Also set the root logger level to WARNING to suppress all debug logs
logging.getLogger().setLevel(logging.WARNING)

from loguru import logger

from app.config import config
from app.config.config import load_config
from app.models import const
from app.models.schema import Scene, VideoConcatMode, VideoParams
from app.services import llm, material, subtitle, video, voice
from app.services import state as sm
from app.services.material import extract_style_keyword
from app.services.scene_parser import detect_content_type, ContentType
from app.services.thread_manager import thread_manager
from app.services.video_target import concat_videos_stream_copy
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
    If user provides a script, convert to multi-scene format.
    If user provides scenes directly, use them as-is (host_visible only affects LLM generation).
    
    Returns:
        Tuple of (script_text, scenes_list)
    """
    logger.info("\n\n## generating multi-scene script")
    logger.info(f"[Task] host_visible parameter value: {params.host_visible}")
    
    # Check if user provided scenes directly
    if params.scenes and len(params.scenes) > 0:
        logger.info(f"using {len(params.scenes)} user-provided scenes directly")
        # Generate a simple combined script for logging
        combined_script = ""
        for i, scene in enumerate(params.scenes):
            combined_script += f"[Scene {i+1}] {scene.get('title', '')}\n"
            combined_script += f"{scene.get('script', '')}\n\n"
        return combined_script, params.scenes
    
    # Log params.host_visible value
    logger.info(f"[generate_multi_scene_script] Checking host_visible directly: {params.host_visible}")
    logger.info(f"[generate_multi_scene_script] hasattr(params, 'host_visible'): {hasattr(params, 'host_visible')}")
    
    video_script = params.video_script.strip()
    
    # Detect content type for optimized opening scene generation
    content_to_detect = params.video_script if params.video_script else params.video_subject
    content_type_result = detect_content_type(content_to_detect, params.video_language)
    
    # Log content type detection results
    logger.info(f"=== Content Type Detection ===")
    logger.info(f"Content Type: {content_type_result['content_type']}")
    logger.info(f"Confidence: {content_type_result['confidence']:.4f} ({content_type_result.get('confidence_level', 'UNKNOWN')})")
    logger.info(f"Detection Method: {content_type_result['detection_method']}")
    if content_type_result['matched_keywords']:
        logger.info(f"Matched Keywords: {', '.join(content_type_result['matched_keywords'])}")
    logger.info(f"=== Content Type Detection End ===")
    
    if not video_script:
        # User provided subject only, generate multi-scene script from scratch
        logger.info("generating multi-scene script from subject")
        host_visible_to_send = params.host_visible
        logger.info(f"[generate_multi_scene_script] Sending host_visible to LLM: {host_visible_to_send}")
        video_script = llm.generate_multi_scene_script(
            video_content=params.video_subject,
            language=params.video_language,
            max_scenes=16,
            content_type=content_type_result['content_type'],
            host_visible=host_visible_to_send
        )
    else:
        # User provided script, convert to multi-scene format
        logger.info("converting provided script to multi-scene format")
        host_visible_to_send = params.host_visible
        logger.info(f"[convert_to_multi_scene] Sending host_visible to LLM: {host_visible_to_send}")
        video_script = llm.convert_to_multi_scene(
            video_script=video_script,
            video_subject=params.video_subject,
            language=params.video_language,
            content_type=content_type_result['content_type'],
            host_visible=host_visible_to_send
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
        
        # Check if scene already has keywords (from UI/parsing)
        existing_keywords = scene.get('keywords', '')
        if existing_keywords:
            # Use existing keywords if they exist
            if isinstance(existing_keywords, str):
                # Try to parse as Python list literal first
                try:
                    parsed = ast.literal_eval(existing_keywords)
                    if isinstance(parsed, list):
                        terms = [str(term).strip() for term in parsed if term]
                    else:
                        # Not a list, treat as comma-separated string
                        terms = [term.strip() for term in existing_keywords.split(',') if term.strip()]
                except (ValueError, SyntaxError):
                    # Fallback to comma-separated string parsing
                    terms = [term.strip() for term in existing_keywords.split(',') if term.strip()]
            else:
                # Already a list
                terms = existing_keywords
            logger.info(f"Using existing keywords for scene {i+1}: {terms}")
        else:
            # Generate new keywords if none exist
            terms = llm.generate_scene_terms(
                video_subject=params.video_subject,
                scene_script=scene.get('audio', scene.get('script', '')),
                scene_camera=scene.get('visual', scene.get('camera', '')),  # Use visual field from new format
                amount=5
            )
        
        if terms and not (isinstance(terms, str) and "Error: " in terms):
            # Ensure video subject is included in keywords (add bilingual versions)
            if params.video_subject and params.video_subject.strip():
                subject_lower = params.video_subject.lower()
                terms_lower = [term.lower() for term in terms]
                if subject_lower not in terms_lower:
                    # Add video subject to terms if not already present
                    # Add both English and Chinese versions if possible
                    terms.insert(0, params.video_subject)
                    # Do not limit terms count to preserve bilingual keywords
            # Filter out any empty terms
            terms = [term for term in terms if term and term.strip()]
            scene_terms_list.append(terms)
            # Update scene keywords with final terms as comma-separated string
            scene['keywords'] = ", ".join(terms)
            logger.success(f"scene {i+1} terms: {terms}")
        else:
            logger.warning(f"failed to generate terms for scene {i+1}, using default terms")
            default_terms = []
            if params.video_subject and params.video_subject.strip():
                default_terms.append(params.video_subject)
            default_terms.extend(["video", "content"])
            scene_terms_list.append(default_terms)
            scene['keywords'] = ", ".join(default_terms)
    
    return scene_terms_list


def generate_scene_tags(scene_script, visual_requirement="", max_tags=3):
    """
    Generate 1-3 tags for a scene based on its script content and visual requirements.
    
    Args:
        scene_script: Scene script text
        visual_requirement: Scene visual requirements
        max_tags: Maximum number of tags to generate
        
    Returns:
        List of generated tags
    """
    if not scene_script or not scene_script.strip():
        return []
    
    try:
        # Use LLM to generate tags considering both script and visual requirements
        tags = llm.generate_tags(scene_script, visual_requirement=visual_requirement, max_tags=max_tags)
        if tags and len(tags) > 0:
            # Filter out empty tags
            tags = [tag for tag in tags if tag and tag.strip()]
            logger.info(f"Generated tags: {tags}")
            return tags
    except Exception as e:
        logger.error(f"Failed to generate tags with LLM: {str(e)}")
    
    # Fallback: extract keywords from script and visual requirements
    try:
        import jieba
        import collections
        
        # Combine script and visual requirements for keyword extraction
        combined_text = scene_script
        if visual_requirement and visual_requirement.strip():
            combined_text += " " + visual_requirement
        
        # Tokenize Chinese text
        words = jieba.cut(combined_text)
        
        # Filter out stop words and short words
        stop_words = set(['的', '了', '和', '是', '在', '有', '我', '他', '她', '它', '这', '那', '你', '我', '他', '她', '它', '也', '就', '都', '要', '而', '很', '到', '说', '要', '去', '你', '会', '着', '没有', '看', '好', '自己', '这'])
        filtered_words = [word for word in words if word not in stop_words and len(word) >= 2]
        
        # Count word frequency
        word_counts = collections.Counter(filtered_words)
        
        # Get top N words as tags
        top_words = [word for word, _ in word_counts.most_common(max_tags)]
        # Filter out empty tags
        top_words = [word for word in top_words if word and word.strip()]
        logger.info(f"Extracted tags from script and visual requirements: {top_words}")
        return top_words
    except Exception as e:
        logger.error(f"Failed to extract tags from script: {str(e)}")
    
    return []


def process_scene(task_id, params, scene, scene_index, total_scenes, used_local_materials=None, check_cancelled=None):
    if used_local_materials is None:
        used_local_materials = set()
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
    scene_title = scene.get('title', scene.get('visual_requirement', ''))
    logger.info(f"\n\n## processing scene {scene_num}/{total_scenes}: {scene_title}")
    logger.debug(f"process_scene - video_aspect from params: {params.video_aspect}")
    
    if check_cancelled and check_cancelled():
        logger.info(f"Task {task_id} cancelled at start of scene {scene_num}")
        return None
    
    scene_id = scene.get('id', f'scene_{scene_num}')
    scene_script = scene.get('audio', scene.get('script', ''))
    # Remove scene configuration keywords, only use generated tags based on scene content and visual requirements
    processed_keywords = []
    
    # Generate 1-3 tags for the scene
    scene_tags = generate_scene_tags(scene_script, visual_requirement=scene_title, max_tags=3)
    if scene_tags:
        # Add generated tags to scene keywords
        processed_keywords.extend(scene_tags)
        # Remove duplicates
        processed_keywords = list(set(processed_keywords))
        # Limit keywords to 3-5 per scene
        if len(processed_keywords) > 5:
            # Prioritize tags generated by LLM as they are more relevant
            # First keep all generated tags, then add remaining keywords up to 5
            prioritized_keywords = []
            # Add all generated tags first
            for tag in scene_tags:
                if tag in processed_keywords:
                    prioritized_keywords.append(tag)
                    processed_keywords.remove(tag)
            # Add remaining keywords up to total 5
            prioritized_keywords.extend(processed_keywords[:5 - len(prioritized_keywords)])
            processed_keywords = prioritized_keywords
        elif len(processed_keywords) < 3:
            # If less than 3 keywords, generate additional tags
            additional_tags = generate_scene_tags(scene_script, visual_requirement=scene_title, max_tags=5 - len(processed_keywords))
            for tag in additional_tags:
                if tag not in processed_keywords:
                    processed_keywords.append(tag)
                if len(processed_keywords) >= 3:
                    break
        logger.info(f"scene {scene_num}: updated keywords with generated tags: {processed_keywords}")
    else:
        # If no tags generated, ensure at least 3 keywords
        if len(processed_keywords) < 3:
            # Generate additional tags
            additional_tags = generate_scene_tags(scene_script, visual_requirement=scene_title, max_tags=3 - len(processed_keywords))
            processed_keywords.extend(additional_tags)
    
    # Use processed keywords
    scene_keywords = processed_keywords
    
    logger.info(f"scene {scene_num}: scene_id={scene_id}, script={scene_script[:50]}...")
    logger.info(f"scene {scene_num}: keywords={scene_keywords}")
    
    # Create scene-specific directory with sequential number for user-friendliness
    scene_dir = path.join(utils.task_dir(task_id), f'scene_{scene_num}')
    os.makedirs(scene_dir, exist_ok=True)
    
    # 1. Generate audio for scene
    if check_cancelled and check_cancelled():
        logger.info(f"Task {task_id} cancelled before generating audio for scene {scene_num}")
        return None
        
    logger.info(f"generating audio for scene {scene_num}")
    audio_file = path.join(scene_dir, "audio.mp3")
    logger.info(f"scene {scene_num}: audio_file={audio_file}")
    sub_maker = voice.tts(
        text=scene_script,
        voice_name=voice.parse_voice_name(params.voice_name),
        voice_rate=params.voice_rate,
        voice_file=audio_file,
        voice_volume=params.voice_volume,
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
    if check_cancelled and check_cancelled():
        logger.info(f"Task {task_id} cancelled before generating subtitle for scene {scene_num}")
        return None
        
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
    if check_cancelled and check_cancelled():
        logger.info(f"Task {task_id} cancelled before getting video materials for scene {scene_num}")
        return None
        
    logger.info(f"getting video materials for scene {scene_num}")
    downloaded_videos = []
    local_materials = []
    supplement_videos = []
    
    # Use global video style keyword from params
    style_keyword = params.video_style
    if style_keyword and style_keyword != "none":
        logger.info(f"Using global video style keyword: {style_keyword}")
    else:
        logger.info("No global video style keyword provided")
    
    local_materials = []
    has_local_materials = False
    
    if params.video_source == "local" or (params.video_materials and len(params.video_materials) > 0):
        # For local source or when local materials are provided, use them first
        logger.info(f"scene {scene_num}: processing local materials. Video materials count: {len(params.video_materials) if params.video_materials else 0}")
        logger.info(f"scene {scene_num}: already used local materials: {len(used_local_materials)}")
        
        # Debug: log the actual materials content
        if params.video_materials:
            for i, m in enumerate(params.video_materials):
                logger.info(f"scene {scene_num}: original material[{i}] = provider={m.provider}, url={m.url}, duration={m.duration}")
        
        # Filter out already used local materials
        available_materials = []
        if params.video_materials:
            for m in params.video_materials:
                if m.url not in used_local_materials:
                    available_materials.append(m)
                    logger.info(f"scene {scene_num}: available material: {os.path.basename(m.url)}")
                else:
                    logger.info(f"scene {scene_num}: skipping used material: {os.path.basename(m.url)}")
        
        logger.info(f"scene {scene_num}: available materials after filtering: {len(available_materials)}")
        
        # If video source is local but no materials available, fall back to online
        if params.video_source == "local" and len(available_materials) == 0:
            logger.warning(f"scene {scene_num}: video source is set to 'local' but no available local materials (all materials already used), falling back to online videos")
            # Don't return None, fall through to download online videos
        elif available_materials:
            materials = video.preprocess_video(
                materials=available_materials, clip_duration=(3, 5)
            )
            
            logger.info(f"scene {scene_num}: after preprocessing, materials count: {len(materials) if materials else 0}")
            
            # Copy local materials to task-specific directory for isolation
            if materials:
                logger.info(f"scene {scene_num}: copying local materials to task directory for isolation")
                materials = video.copy_local_materials_to_task(task_id, materials)
                logger.info(f"scene {scene_num}: after copying to task directory, materials count: {len(materials) if materials else 0}")
            
            # Match local videos by scene keywords for better semantic relevance
            if materials and scene_keywords:
                logger.info(f"scene {scene_num}: matching local materials with keywords: {scene_keywords}")
                materials = video.match_local_videos_by_keywords(materials, scene_keywords)
                logger.info(f"scene {scene_num}: after matching, materials count: {len(materials) if materials else 0}")
            elif materials:
                logger.info(f"scene {scene_num}: no keywords provided for matching, using all materials")
            elif scene_keywords:
                logger.info(f"scene {scene_num}: no materials provided for matching, but have keywords: {scene_keywords}")
            else:
                logger.info(f"scene {scene_num}: no materials and no keywords provided for matching")
            
            if materials:
                local_materials = [m.url for m in materials]
                logger.success(f"scene {scene_num}: found {len(local_materials)} local materials")
                has_local_materials = True
                # Note: Marking as used will be done AFTER build_scene_video succeeds
    
    # Add online videos as supplement if needed
    should_download_online = False
    online_source = "pexels"
    target_online_clips = 0
    
    if params.video_source == "local":
        # If local source but no local materials, download online videos
        if len(local_materials) == 0:
            logger.warning(f"scene {scene_num}: no local materials available, downloading online videos from {online_source}")
            should_download_online = True
            # Calculate how many online clips are needed
            target_online_clips = max(1, int(math.ceil(audio_duration / params.video_clip_duration)))
        elif len(local_materials) < len(scene_keywords):
            logger.info(f"scene {scene_num}: local materials ({len(local_materials)}) less than keywords ({len(scene_keywords)}), downloading supplement videos from {online_source}")
            should_download_online = True
            # Calculate how many online clips are needed to supplement
            target_online_clips = max(1, len(scene_keywords) - len(local_materials))
        else:
            logger.info(f"scene {scene_num}: local materials ({len(local_materials)}) >= keywords ({len(scene_keywords)}), no supplement videos needed")
    else:
        # Non-local source, always download
        online_source = params.video_source
        logger.info(f"scene {scene_num}: using {online_source} as video source, downloading videos")
        should_download_online = True
        # Calculate how many online clips are needed
        target_online_clips = max(1, int(math.ceil(audio_duration / params.video_clip_duration)))
    
    supplement_videos = []
    if should_download_online:
        supplement_videos = material.download_videos(
            task_id=task_id,
            search_terms=scene_keywords,
            source=online_source,
            video_aspect=params.video_aspect,
            video_concat_mode=params.video_concat_mode,
            audio_duration=audio_duration,
            max_clip_duration=params.video_clip_duration,
            style_keyword=style_keyword,
            target_number_of_clips=target_online_clips,
        )
        
        if supplement_videos:
            logger.success(f"scene {scene_num}: downloaded {len(supplement_videos)} supplement videos")
        else:
            logger.warning(f"scene {scene_num}: no supplement videos downloaded")
    
    # Combine local materials (must be first) and supplement videos
    downloaded_videos = local_materials.copy()
    if 'supplement_videos' in locals() and supplement_videos:
        downloaded_videos.extend(supplement_videos)
    
    if not downloaded_videos:
        logger.error(f"scene {scene_num}: failed to get video materials")
        return None
    
    # Check for intro video and insert at the beginning
    intro_video = scene.get("intro_video")
    intro_video_original_path = scene.get("intro_video_original_path")
    logger.info(f"scene {scene_num}: intro_video from scene: {intro_video}")
    logger.info(f"scene {scene_num}: intro_video_original_path: {intro_video_original_path}")
    
    # Determine the actual intro video path to use
    actual_intro_video = None
    if intro_video:
        # Check if intro video exists in local_videos
        if os.path.exists(intro_video):
            # Create task-specific intro_videos directory
            task_intro_videos_dir = path.join(utils.storage_dir("intro_videos"), task_id)
            if not os.path.exists(task_intro_videos_dir):
                os.makedirs(task_intro_videos_dir)
                logger.info(f"Created task intro_videos directory: {task_intro_videos_dir}")
            
            # Copy intro video from local_videos to task-specific directory
            intro_video_filename = os.path.basename(intro_video)
            task_intro_video_path = path.join(task_intro_videos_dir, intro_video_filename)
            
            if not os.path.exists(task_intro_video_path):
                import shutil
                shutil.copy2(intro_video, task_intro_video_path)
                logger.info(f"scene {scene_num}: copied intro video from {intro_video} to {task_intro_video_path}")
            else:
                logger.info(f"scene {scene_num}: intro video already exists in task directory: {task_intro_video_path}")
            
            actual_intro_video = task_intro_video_path
            logger.info(f"scene {scene_num}: adding intro video at the beginning: {actual_intro_video}")
            downloaded_videos.insert(0, actual_intro_video)
            logger.success(f"scene {scene_num}: intro video added, total clips: {len(downloaded_videos)}")
        else:
            logger.warning(f"scene {scene_num}: intro_video not found at original location: {intro_video}")
    else:
        logger.info(f"scene {scene_num}: no intro_video field in scene")
    
    logger.success(f"scene {scene_num}: obtained {len(downloaded_videos)} video clips (local: {len(local_materials)}, supplement: {len(downloaded_videos) - len(local_materials)})")
    
    # 4. Combine scene video clip (without BGM)
    if check_cancelled and check_cancelled():
        logger.info(f"Task {task_id} cancelled before combining scene {scene_num}")
        return None
        
    logger.info(f"combining video clip for scene {scene_num}")
    combined_video_path = path.join(scene_dir, "combined.mp4")
    
    # Pass local video paths to build_scene_video so it can apply different quality check rules
    local_video_paths = local_materials.copy()
    # Also add intro video to local_video_paths if exists (to avoid quality check issues)
    if actual_intro_video and os.path.exists(actual_intro_video):
        local_video_paths.insert(0, actual_intro_video)
    if local_video_paths:
        logger.info(f"scene {scene_num}: passing {len(local_video_paths)} local video paths for quality check exemption")
    
    logger.debug(f"scene {scene_num}: Calling build_scene_video with video_aspect: {params.video_aspect}")
    logger.debug(f"scene {scene_num}: Calling build_scene_video with video_aspect type: {type(params.video_aspect)}")
    
    build_result, used_local_paths = video.build_scene_video(
        combined_video_path=combined_video_path,
        video_paths=downloaded_videos,
        audio_file=audio_file,
        video_aspect=params.video_aspect,
        video_concat_mode=params.video_concat_mode,
        video_transition_mode=params.video_transition_mode,
        max_clip_duration=params.video_clip_duration,
        threads=params.n_threads,
        scene_info=f"(scene {scene_num}/{total_scenes})",
        local_video_paths=local_video_paths,
        intro_video_path=actual_intro_video if actual_intro_video and os.path.exists(actual_intro_video) else None,
        intro_duration=scene.get("intro_duration", 10))
    
    # build_result is the combined_video_path, used_local_paths contains actual used local material paths
    result = build_result
    
    if result is None or not os.path.exists(combined_video_path):
        logger.error(f"failed to combine video for scene {scene_num}")
        return None
    
    logger.success(f"scene {scene_num}: video clip created")
    
    # Mark only the local materials that were actually used in the video
    # used_local_paths contains the actual paths of local materials used
    if has_local_materials and available_materials and used_local_paths:
        for m in available_materials:
            # Check if this material's path is in used_local_paths
            # Note: m.url might be the original path, while used_local_paths contains task-specific paths
            material_used = False
            for used_path in used_local_paths:
                if used_path and os.path.basename(used_path) == os.path.basename(m.url):
                    material_used = True
                    break
            
            if material_used:
                used_local_materials.add(m.url)
                logger.info(f"scene {scene_num}: marked local material as used: {os.path.basename(m.url)}")
            else:
                logger.info(f"scene {scene_num}: local material NOT used in video: {os.path.basename(m.url)}")
        logger.info(f"scene {scene_num}: total used local materials now: {len(used_local_materials)}")
    elif has_local_materials and available_materials and not used_local_paths:
        # No local materials were used (e.g., intro video was sufficient)
        logger.info(f"scene {scene_num}: no local materials were used in the video (intro video may be sufficient)")
    
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

    Uses FFmpeg's concat demuxer with -c copy (zero re-encoding) when possible,
    falling back to MoviePy re-encode if stream-copy is not viable.

    Args:
        task_id: Task ID
        params: Video parameters
        scene_results: List of scene result dictionaries

    Returns:
        Final video path (temp file without BGM, will be processed by process_final_video)
    """
    logger.info("\n\n## combining all scenes into final video")

    # Collect valid scene file paths (for fast path) and clips (for slow path)
    scene_paths = []
    total_video_duration = 0
    scene_durations = []

    for result in scene_results:
        video_path = result.get('combined_video_path', '') if result else ''
        if video_path and os.path.exists(video_path):
            scene_paths.append(video_path)
        else:
            logger.warning(f"scene video missing: {video_path}")

    if not scene_paths:
        logger.error("no scene clips available for final combination")
        return None

    temp_video_path = path.join(utils.task_dir(task_id), "temp_combined_scenes.mp4")

    # --- Fast path: FFmpeg concat demuxer with -c copy (zero re-encoding) ---
    # Scene videos all come from the same build_scene_video() pipeline, so they share
    # codec, resolution, fps and pixel format — safe for stream-copy concatenation.
    fast_path_ok = False
    if len(scene_paths) >= 2:
        logger.info(
            f"Attempting fast-path concat for {len(scene_paths)} scenes (no re-encoding)"
        )
        fast_path_ok = concat_videos_stream_copy(scene_paths, temp_video_path)

    if fast_path_ok:
        # Verify the output is valid
        try:
            temp_clip = video.VideoFileClip(temp_video_path)
            if not hasattr(temp_clip, 'duration') or temp_clip.duration is None:
                logger.warning("fast-path output has no duration; falling back to re-encode")
                temp_clip.close()
                fast_path_ok = False
            else:
                logger.success(
                    f"combined scenes created (fast-path): {temp_video_path} "
                    f"(duration: {temp_clip.duration:.2f}s)"
                )
                temp_clip.close()
                return temp_video_path
        except Exception as e:
            logger.warning(f"fast-path output verification failed ({e}); falling back")
            fast_path_ok = False

    # --- Slow path: load clips into MoviePy, concatenate, re-encode ---
    logger.info(f"Using MoviePy re-encode path for {len(scene_paths)} scenes")
    scene_clips = []
    for p in scene_paths:
        try:
            clip = video.VideoFileClip(p)
            scene_clips.append(clip)
            dur = clip.duration
            scene_durations.append(dur)
            total_video_duration += dur
            logger.info(f"loaded scene clip: {p} (duration: {dur:.2f}s)")
        except Exception as e:
            logger.error(f"failed to load scene clip {p}: {e}")

    if not scene_clips:
        logger.error("no scene clips could be loaded for final combination")
        return None

    logger.info(f"combining {len(scene_clips)} scene clips")
    logger.info(f"total video duration: {total_video_duration:.2f}s")
    logger.info(f"scene durations: {[f'{d:.2f}s' for d in scene_durations]}")

    # Audio is already merged into each scene video at scene level
    processed_clips = scene_clips
    logger.info(f"Audio already embedded in scene videos, concatenating {len(processed_clips)} clips")

    try:
        result = video.finalize_video(
            processed_clips=processed_clips,
            combined_video_path=temp_video_path,
            audio_file=None,  # No audio here, will be added later
            threads=params.n_threads
        )

        if result:
            try:
                temp_clip = video.VideoFileClip(temp_video_path)
                if not hasattr(temp_clip, 'duration') or temp_clip.duration is None:
                    logger.error(f"Combined video has no duration: {temp_video_path}")
                    temp_clip.close()
                    for clip in processed_clips:
                        clip.close()
                    return None
                logger.success(f"combined scenes created: {temp_video_path} (duration: {temp_clip.duration:.2f}s)")
                temp_clip.close()
            except Exception as e:
                logger.error(f"Failed to verify combined video: {e}")
                for clip in processed_clips:
                    clip.close()
                return None

            for clip in processed_clips:
                clip.close()
            return temp_video_path
        else:
            logger.error("failed to finalize video")
            for clip in processed_clips:
                clip.close()
            return None

    except Exception as e:
        logger.error(f"failed to combine scenes: {e}")
        for clip in processed_clips:
            clip.close()
        return None


def start_async(task_id, params: VideoParams, stop_at: str = "video", task_create_time: float = None):
    """Start task (async version)
    
    Args:
        task_id: Task ID
        params: Video parameters
        stop_at: Stop point
        task_create_time: Optional task creation timestamp (time.time())
        
    Returns:
        Tuple of (Task ID, status message)
    """
    logger.debug(f"start_async: task_id={task_id}, thread_manager_id={id(thread_manager)}")
    logger.info(f"Submitting task {task_id} to background thread")
    result = thread_manager.submit_task(task_id, start, task_id, params, stop_at, task_create_time=task_create_time)
    logger.debug(f"start_async: task_id={task_id} submitted, result={result}")
    return result


def start(task_id, params: VideoParams, stop_at: str = "video", check_cancelled=None, task_create_time: float = None):
    from app.services.state import set_task_running, set_task_completed
    from app.models import const
    from app.services import state as sm
    
    # Set task as running
    set_task_running("video_generation", task_id)
    
    # Update task state to PROCESSING
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=0)
    
    # Track task start time
    import time
    task_start_time = time.time()
    
    # Create task log file
    task_log_path = os.path.join(utils.task_dir(task_id), "task.log")
    # Add file handler to logger
    log_handler_id = logger.add(
        task_log_path,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {file}:{line} | {message}\n",
        level="DEBUG",
        rotation="10 MB",
        compression="zip"
    )
    
    # Log GPU configuration for video codec
    from app.config import config
    use_gpu = config.app.get("use_gpu", False)
    logger.info(f"GPU configuration for video codec: use_gpu={use_gpu}")
    
    logger.info(f"========================================")
    logger.info(f"TASK STARTED: {task_id}")
    logger.info(f"stop_at: {stop_at}")
    logger.info(f"Task log file: {task_log_path}")
    logger.info(f"========================================")
    
    # Clear per-task caches from previous runs
    from app.services.video_utils import clear_brightness_cache, clear_downscale_cache
    clear_brightness_cache()
    clear_downscale_cache()
    
    # Log video aspect ratio at task start
    logger.debug(f"Task start - video_aspect from params: {params.video_aspect}")
    logger.debug(f"Task start - video_aspect type: {type(params.video_aspect)}")
    
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=5, task_type="video_generation")

    if type(params.video_concat_mode) is str:
        params.video_concat_mode = VideoConcatMode(params.video_concat_mode)
    
    # Convert video_aspect from string to enum if needed
    if type(params.video_aspect) is str:
        try:
            params.video_aspect = VideoAspect(params.video_aspect)
            logger.debug(f"Converted video_aspect from string '{params.video_aspect.value}' to enum")
        except ValueError:
            logger.warning(f"Invalid video_aspect string '{params.video_aspect}', defaulting to 9:16")
            params.video_aspect = VideoAspect.portrait

    # Unified multi-scene architecture - always use multi-scene flow
    logger.info("using unified multi-scene architecture")
    
    result = None
    exception_occurred = None
    try:
        # Check for cancellation before starting
        if check_cancelled and check_cancelled():
            logger.info(f"Task {task_id} cancelled before starting")
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, **{"status": "cancelled"})
            return None
            
        result = start_multi_scene(task_id, params, stop_at, task_start_time, check_cancelled=check_cancelled, task_create_time=task_create_time)
    except Exception as e:
        exception_occurred = e
        import traceback
        tb_str = ''.join(traceback.format_exception(type(e), e, e.__traceback__))
        logger.error(f"========================================")
        logger.error(f"TASK FAILED WITH EXCEPTION:")
        logger.error(f"Exception Type: {type(e).__name__}")
        logger.error(f"Exception Message: {str(e)}")
        logger.error(f"Traceback:\n{tb_str}")
        logger.error(f"========================================")
        raise
    finally:
        # Set task as completed
        from app.services.state import set_task_completed
        set_task_completed()
        
        # Determine task status and log final status
        if exception_occurred:
            logger.warning(f"========================================")
            logger.warning(f"TASK ENDED WITH EXCEPTION (see error details above)")
            logger.warning(f"========================================")
        elif result is None:
            logger.warning(f"========================================")
            logger.warning(f"TASK ENDED: No result returned")
            logger.warning(f"The task likely failed during execution.")
            logger.warning(f"Check the logs above for error details.")
            logger.warning(f"========================================")
        else:
            logger.success(f"========================================")
            logger.success(f"TASK COMPLETED SUCCESSFULLY")
            logger.success(f"========================================")
        
        # Log task lifecycle and running duration before closing the log file
        import time as _time
        _end = _time.time()
        if task_create_time:
            _hours, _rem = divmod(_end - task_create_time, 3600)
            _mins, _secs = divmod(_rem, 60)
            logger.info(f"Task lifecycle: {int(_hours):02d}:{int(_mins):02d}:{int(_secs):02d}")
        _hours, _rem = divmod(_end - task_start_time, 3600)
        _mins, _secs = divmod(_rem, 60)
        logger.info(f"Task running duration: {int(_hours):02d}:{int(_mins):02d}:{int(_secs):02d}")
        
        # Remove the file handler to release the log file
        try:
            logger.remove(log_handler_id)
            logger.info(f"Task log file closed: {task_log_path}")
        except ValueError:
            # Handler already removed, ignore
            pass
    
    return result


def start_multi_scene(task_id, params: VideoParams, stop_at: str = "video", task_start_time=None, check_cancelled=None, task_create_time=None):
    """Multi-scene video generation flow."""

    # Log the aspect ratio at the very start
    logger.debug(f"========================================")
    logger.debug(f"start_multi_scene - video_aspect from params: {params.video_aspect}")
    logger.debug(f"start_multi_scene - video_aspect type: {type(params.video_aspect)}")
    if hasattr(params.video_aspect, 'value'):
        logger.debug(f"start_multi_scene - video_aspect.value: {params.video_aspect.value}")
    logger.debug(f"========================================")
    
    # Print local materials list at the beginning
    if params.video_materials and len(params.video_materials) > 0:
        logger.info(f"User provided {len(params.video_materials)} local materials:")
        for i, material in enumerate(params.video_materials):
            logger.info(f"  {i+1}. {os.path.basename(material.url)}")
    else:
        logger.info("No local materials provided by user")
    
    # 1. Generate multi-scene script
    if check_cancelled and check_cancelled():
        logger.info(f"Task {task_id} cancelled before generating script")
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, **{"status": "cancelled"})
        return None
        
    video_script, scenes = generate_multi_scene_script(task_id, params)
    if not video_script or not scenes:
        logger.error("Multi-scene: failed to generate script, returning None")
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return
    
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=10)
    
    if stop_at == "script":
        logger.info("Multi-scene: returning at stop_at='script'")
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, script=video_script
        )
        return {"script": video_script, "scenes": scenes}
    
    # 2. Generate terms for each scene
    if check_cancelled and check_cancelled():
        logger.info(f"Task {task_id} cancelled before generating scene terms")
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, **{"status": "cancelled"})
        return None
        
    scene_terms_list = generate_scene_terms(task_id, params, scenes)
    if not scene_terms_list:
        logger.warning("failed to generate scene terms, continuing with defaults")
    
    save_script_data(task_id, video_script, scene_terms_list, params)
    
    if stop_at == "terms":
        logger.info("Multi-scene: returning at stop_at='terms'")
        sm.state.update_task(
            task_id, state=const.TASK_STATE_COMPLETE, progress=100, terms=scene_terms_list
        )
        return {"script": video_script, "terms": scene_terms_list, "scenes": scenes}
    
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)
    
    # 3. Process each scene
    total_scenes = len(scenes)
    scene_results = []
    
    # Track used local materials - each material should be used only once
    # Use a thread-safe set wrapper for parallel scene processing
    import threading as _threading
    
    class _ThreadSafeSet(set):
        """Set subclass with lock-protected add/contains for parallel access."""
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._lock = _threading.Lock()
        def add(self, item):
            with self._lock:
                super().add(item)
        def __contains__(self, item):
            with self._lock:
                return super().__contains__(item)
        def __len__(self):
            with self._lock:
                return super().__len__()
    
    used_local_materials = _ThreadSafeSet()
    
    # Check if video source is local but no materials provided
    if params.video_source == "local" and (not params.video_materials or len(params.video_materials) == 0):
        error_msg = "Video source is set to 'local' but no local materials provided"
        logger.error(error_msg)
        # Instead of failing, let's warn and continue with online sources as fallback
        logger.warning("Falling back to online video sources")
        # Temporarily change video source to pexels for this task
        original_video_source = params.video_source
        params.video_source = "pexels"
        logger.info(f"Changed video source from {original_video_source} to pexels as fallback")
    else:
        # Log local materials info if available
        if params.video_materials and len(params.video_materials) > 0:
            logger.info(f"Found {len(params.video_materials)} local materials")
            for i, material in enumerate(params.video_materials):
                logger.info(f"  {i+1}. {os.path.basename(material.url)}")
        else:
            logger.info("No local materials provided")
    
    # Parallel scene processing
    max_parallel = config.app.get("max_parallel_scenes", 2)
    max_parallel = max(1, min(max_parallel, total_scenes))  # Clamp to [1, total_scenes]
    
    if max_parallel == 1:
        # Sequential fallback — same as before
        logger.info(f"Processing {total_scenes} scenes sequentially (max_parallel_scenes=1)")
        for i, scene in enumerate(scenes):
            if check_cancelled and check_cancelled():
                logger.info(f"Task {task_id} cancelled during scene processing")
                sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, **{"status": "cancelled"})
                return None
                
            progress = 20 + (i / total_scenes) * 40
            sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=int(progress))
            
            logger.info(f"========================================")
            logger.info(f"Processing scene {i+1}/{total_scenes}")
            logger.info(f"========================================")
            
            result = process_scene(task_id, params, scene, i, total_scenes, used_local_materials, check_cancelled=check_cancelled)
            if result:
                scene_results.append(result)
                logger.info(f"Scene {i+1} processed successfully, combined_video_path: {result.get('combined_video_path')}")
            else:
                logger.error(f"FAILED to process scene {i+1}/{total_scenes}, skipping")
    else:
        # Parallel execution via ThreadPoolExecutor
        from concurrent.futures import ThreadPoolExecutor, as_completed
        
        logger.info(f"Processing {total_scenes} scenes with {max_parallel} parallel workers")
        
        completed_count = 0
        completed_lock = _threading.Lock()
        
        def _process_and_track(i, scene):
            nonlocal completed_count
            logger.info(f"========================================")
            logger.info(f"Processing scene {i+1}/{total_scenes} (parallel)")
            logger.info(f"========================================")
            
            result = process_scene(task_id, params, scene, i, total_scenes, used_local_materials, check_cancelled=check_cancelled)
            
            with completed_lock:
                completed_count += 1
                progress = 20 + (completed_count / total_scenes) * 40
                sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=int(progress))
            
            if result:
                logger.info(f"Scene {i+1} processed successfully, combined_video_path: {result.get('combined_video_path')}")
            else:
                logger.error(f"FAILED to process scene {i+1}/{total_scenes}, skipping")
            
            return result
        
        # Check cancellation before starting
        if check_cancelled and check_cancelled():
            logger.info(f"Task {task_id} cancelled before parallel scene processing")
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, **{"status": "cancelled"})
            return None
        
        with ThreadPoolExecutor(max_workers=max_parallel) as executor:
            future_to_idx = {
                executor.submit(_process_and_track, i, scene): i
                for i, scene in enumerate(scenes)
            }
            
            for future in as_completed(future_to_idx):
                if check_cancelled and check_cancelled():
                    logger.info(f"Task {task_id} cancelled, shutting down parallel scenes")
                    executor.shutdown(wait=False, cancel_futures=True)
                    sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, **{"status": "cancelled"})
                    return None
                
                try:
                    result = future.result()
                    if result:
                        scene_results.append(result)
                except Exception as e:
                    idx = future_to_idx[future]
                    logger.error(f"Scene {idx+1} raised exception: {e}")
        
        # Sort results by scene_index to maintain correct ordering
        scene_results.sort(key=lambda r: r.get('scene_index', 0))
    
    logger.info(f"========================================")
    logger.info(f"All scenes processed")
    logger.info(f"Successful scenes: {len(scene_results)}/{total_scenes}")
    logger.info(f"========================================")
    
    if not scene_results:
        logger.error("Multi-scene: ALL scenes failed to process!")
        logger.error(f"Expected {total_scenes} scenes but got 0 successful results")
        logger.error("Possible reasons:")
        logger.error("  1. Video material download failed")
        logger.error("  2. Video combine process failed")
        logger.error("  3. No video materials found for search terms")
        logger.error("Please check the error logs above for details")
        logger.error("========================================")
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return
    
    logger.success(f"successfully processed {len(scene_results)}/{total_scenes} scenes")
    
    if stop_at == "audio":
        logger.info("Multi-scene: returning at stop_at='audio'")
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
        logger.info("Multi-scene: returning at stop_at='subtitle'")
        return {"scenes": scenes, "scene_results": scene_results}
    
    if stop_at == "materials":
        logger.info("Multi-scene: returning at stop_at='materials'")
        return {"scenes": scenes, "scene_results": scene_results}
    
    if check_cancelled and check_cancelled():
        logger.info(f"Task {task_id} cancelled before combining scenes")
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, **{"status": "cancelled"})
        return None
        
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=70)
    
    # 4. Combine all scenes into final video
    scene_synthesis_start_time = time.time()
    final_video_path = combine_all_scenes(task_id, params, scene_results)
    if not final_video_path:
        logger.error("Multi-scene: failed to combine all scenes, returning None")
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return
    
    if check_cancelled and check_cancelled():
        logger.info(f"Task {task_id} cancelled before final processing")
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, **{"status": "cancelled"})
        return None
        
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=88)
    
    # 5. Add background music and final processing for multi-scene video
    # Use the shared process_final_video function for consistency with scene integration
    final_output_path = path.join(utils.task_dir(task_id), "final-1.mp4")
    step5_start_time = time.time()
    
    logger.info("========================================")
    logger.info("Step 5: Using shared process_final_video for final processing")
    logger.info(f"Combined video path: {final_video_path}")
    logger.info(f"Final output path: {final_output_path}")
    logger.info(f"[TIMESTAMP] Step 5 started at: {time.strftime('%H:%M:%S')}")
    logger.info("========================================")
    
    try:
        from app.services.video_target import process_final_video
        
        logger.info("Calling process_final_video (shared flow for both video generation and scene integration)")
        
        # Use the shared process_final_video function
        # This handles: pillarbox, silence prefix, title, subtitles, BGM, and final encoding
        output_path = process_final_video(
            task_id=task_id,
            params=params,
            scene_results=scene_results,
            combined_video_path=final_video_path,
            subtitle_file=None,  # Will be merged from scene_results
            audio_file=None,      # Will use BGM from params
            output_file=final_output_path,
            progress_callback=None,
            task_create_time=task_create_time,
            task_start_time=task_start_time,
            scene_synthesis_start_time=scene_synthesis_start_time,
        )
        
        if output_path and os.path.exists(output_path):
            final_output_path = output_path
            logger.success(f"Final video created via shared process_final_video: {final_output_path}")
        else:
            logger.error("process_final_video returned None or file not found")
            raise Exception("Failed to generate final video")
            
    except Exception as e:
        logger.error(f"========================================")
        logger.error(f"Multi-scene EXCEPTION: {str(e)}")
        logger.error(f"========================================")
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return
    
    logger.success(f"Task {task_id} finished, generated multi-scene video")
        
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
