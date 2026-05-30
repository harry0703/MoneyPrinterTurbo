import ast
import math
import os.path
import re
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
    If user provides scenes directly, use them as-is.
    
    Returns:
        Tuple of (script_text, scenes_list)
    """
    logger.info("\n\n## generating multi-scene script")
    
    # Check if user provided scenes directly
    if params.scenes and len(params.scenes) > 0:
        logger.info(f"using {len(params.scenes)} user-provided scenes directly")
        # Generate a simple combined script for logging
        combined_script = ""
        for i, scene in enumerate(params.scenes):
            combined_script += f"[Scene {i+1}] {scene.get('title', '')}\n"
            combined_script += f"{scene.get('script', '')}\n\n"
        return combined_script, params.scenes
    
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
        video_script = llm.generate_multi_scene_script(
            video_content=params.video_subject,
            language=params.video_language,
            max_scenes=16,
            content_type=content_type_result['content_type']
        )
    else:
        # User provided script, convert to multi-scene format
        logger.info("converting provided script to multi-scene format")
        video_script = llm.convert_to_multi_scene(
            video_script=video_script,
            video_subject=params.video_subject,
            language=params.video_language,
            content_type=content_type_result['content_type']
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
    total_video_duration = 0
    scene_durations = []
    
    for result in scene_results:
        if result and os.path.exists(result.get('combined_video_path', '')):
            # Load each scene video as a clip
            try:
                clip = video.VideoFileClip(result['combined_video_path'])
                scene_clips.append(clip)
                scene_duration = clip.duration
                scene_durations.append(scene_duration)
                total_video_duration += scene_duration
                logger.info(f"loaded scene clip: {result['combined_video_path']} (duration: {scene_duration:.2f}s)")
            except Exception as e:
                logger.error(f"failed to load scene clip {result['combined_video_path']}: {e}")
    
    if not scene_clips:
        logger.error("no scene clips available for final combination")
        return None
    
    logger.info(f"combining {len(scene_clips)} scene clips")
    logger.info(f"total video duration: {total_video_duration:.2f}s")
    logger.info(f"scene durations: {[f'{d:.2f}s' for d in scene_durations]}")
    
    # Note: Idle period is now added AFTER video+audio+subtitle synchronization
    # This ensures proper sync - moved to start_multi_scene() after subtitle processing
    
    # Audio is already merged into each scene video at scene level
    # Simply concatenate all scene clips without audio operations
    processed_clips = scene_clips
    logger.info(f"Audio already embedded in scene videos, concatenating {len(processed_clips)} clips")
    
    # Concatenate all scene clips to a temp file (without BGM, will be processed later)
    temp_video_path = path.join(utils.task_dir(task_id), "temp_combined_scenes.mp4")
    
    # Finalize video
    try:
        result = video.finalize_video(
            processed_clips=processed_clips,
            combined_video_path=temp_video_path,
            audio_file=None,  # No audio here, will be added later
            threads=params.n_threads
        )
        
        if result:
            # Verify the combined video can be read and has valid duration
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
            
            # Close all clips
            for clip in processed_clips:
                clip.close()
            return temp_video_path
        else:
            logger.error("failed to finalize video")
            # Close all clips
            for clip in processed_clips:
                clip.close()
            return None
            
    except Exception as e:
        logger.error(f"failed to combine scenes: {e}")
        # Close all clips
        for clip in processed_clips:
            clip.close()
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
    local_materials = []
    supplement_videos = []
    
    if params.video_source == "local" or (params.video_materials and len(params.video_materials) > 0):
        # For local source or when local materials are provided, use them first
        logger.info("\n\n## preprocess local materials")
        materials = video.preprocess_video(
            materials=params.video_materials, clip_duration=params.video_clip_duration
        )
        
        # Copy local materials to task-specific directory for isolation
        if materials:
            logger.info("Copying local materials to task directory for isolation")
            materials = video.copy_local_materials_to_task(task_id, materials)
        
        # Match local videos by scene keywords for better semantic relevance
        if materials and video_terms:
            materials = video.match_local_videos_by_keywords(materials, video_terms)
        
        if materials:
            local_materials = [material_info.url for material_info in materials]
            logger.success(f"Found {len(local_materials)} local materials")
        else:
            logger.error("No local materials found. When local materials are provided, they must be used for video generation.")
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
            return None
    
    # Add online videos as supplement if needed
    supplement_videos = []
    if params.video_source != "local":
        online_source = params.video_source
        logger.info(f"\n\n## downloading videos from {online_source}")
        # Use video subject as fallback when video_terms is empty
        search_terms = video_terms if video_terms else [params.video_subject]
        # Calculate how many clips are needed
        total_required_duration = audio_duration * params.video_count
        target_online_clips = max(1, int(math.ceil(total_required_duration / params.video_clip_duration)))
        supplement_videos = material.download_videos(
            task_id=task_id,
            search_terms=search_terms,
            source=online_source,
            video_aspect=params.video_aspect,
            video_concat_mode=params.video_concat_mode,
            audio_duration=total_required_duration,
            max_clip_duration=params.video_clip_duration,
            style_keyword=params.video_style,
            target_number_of_clips=target_online_clips,
        )
        
        if supplement_videos:
            logger.success(f"Downloaded {len(supplement_videos)} videos from {online_source}")
    
    # Combine local materials (must be first) and supplement videos
    downloaded_videos = local_materials.copy()
    if supplement_videos:
        downloaded_videos.extend(supplement_videos)
    
    if not downloaded_videos:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        logger.error(
            "failed to get video materials. Please check your local materials or network connection."
        )
        return None
    
    logger.success(f"Total obtained {len(downloaded_videos)} video clips (local: {len(local_materials)}, supplement: {len(downloaded_videos) - len(local_materials)})")
    return downloaded_videos, local_materials, supplement_videos


def generate_final_videos(
    task_id, params, downloaded_videos, audio_file, subtitle_path, local_materials=None, supplement_videos=None
):
    final_video_paths = []
    combined_video_paths = []
    video_concat_mode = (
        params.video_concat_mode if params.video_count == 1 else VideoConcatMode.random
    )
    video_transition_mode = params.video_transition_mode

    # Pass local video paths to build_scene_video so it can apply different quality check rules
    local_video_paths = local_materials.copy() if local_materials else []
    if local_video_paths:
        logger.info(f"Passing {len(local_video_paths)} local video paths for quality check exemption")

    _progress = 50
    for i in range(params.video_count):
        index = i + 1
        combined_video_path = path.join(
            utils.task_dir(task_id), f"combined-{index}.mp4"
        )
        logger.info(f"\n\n## combining video: {index} => {combined_video_path}")
        video.build_scene_video(
            combined_video_path=combined_video_path,
            video_paths=downloaded_videos,
            audio_file=audio_file,
            video_aspect=params.video_aspect,
            video_concat_mode=video_concat_mode,
            video_transition_mode=video_transition_mode,
            max_clip_duration=params.video_clip_duration,
            threads=params.n_threads,
            scene_info=f"(video {index}/{params.video_count})",
            local_video_paths=local_video_paths
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


def start_async(task_id, params: VideoParams, stop_at: str = "video"):
    """Start task (async version)
    
    Args:
        task_id: Task ID
        params: Video parameters
        stop_at: Stop point
        
    Returns:
        Tuple of (Task ID, status message)
    """
    logger.debug(f"start_async: task_id={task_id}, thread_manager_id={id(thread_manager)}")
    logger.info(f"Submitting task {task_id} to background thread")
    result = thread_manager.submit_task(task_id, start, task_id, params, stop_at)
    logger.debug(f"start_async: task_id={task_id} submitted, result={result}")
    return result


def start(task_id, params: VideoParams, stop_at: str = "video", check_cancelled=None):
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
    # The old single-scene mode is mapped to a single scene in multi-scene architecture
    logger.info("using unified multi-scene architecture")
    
    result = None
    exception_occurred = None
    try:
        # Check for cancellation before starting
        if check_cancelled and check_cancelled():
            logger.info(f"Task {task_id} cancelled before starting")
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, **{"status": "cancelled"})
            return None
            
        result = start_multi_scene(task_id, params, stop_at, task_start_time, check_cancelled=check_cancelled)
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
        
        # Remove the file handler to release the log file
        try:
            logger.remove(log_handler_id)
            logger.info(f"Task log file closed: {task_log_path}")
        except ValueError:
            # Handler already removed, ignore
            pass
    
    return result


def start_single_scene(task_id, params: VideoParams, stop_at: str = "video"):
    """Original single-scene video generation flow."""
    logger.info("using single-scene mode", extra={"task_id": task_id})
    
    # Print local materials list at the beginning
    if params.video_materials and len(params.video_materials) > 0:
        logger.info(f"User provided {len(params.video_materials)} local materials:", extra={"task_id": task_id})
        for i, material in enumerate(params.video_materials):
            logger.info(f"  {i+1}. {os.path.basename(material.url)}", extra={"task_id": task_id})
    else:
        logger.info("No local materials provided by user", extra={"task_id": task_id})
    
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

    # 2. Skip terms generation as it's no longer needed
    video_terms = ""
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
    result = get_video_materials(
        task_id, params, video_terms, audio_duration
    )
    if not result:
        sm.state.update_task(task_id, state=const.TASK_STATE_FAILED)
        return
    downloaded_videos, local_materials, supplement_videos = result

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
        task_id, params, downloaded_videos, audio_file, subtitle_path, local_materials, supplement_videos
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


def start_multi_scene(task_id, params: VideoParams, stop_at: str = "video", task_start_time=None, check_cancelled=None):
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
    used_local_materials = set()  # Stores material URLs
    
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
    
    for i, scene in enumerate(scenes):
        if check_cancelled and check_cancelled():
            logger.info(f"Task {task_id} cancelled during scene processing")
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, **{"status": "cancelled"})
            return None
            
        progress = 20 + (i / total_scenes) * 40  # Progress from 20% to 60%
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=int(progress))
        
        logger.info(f"========================================")
        logger.info(f"Processing scene {i+1}/{total_scenes}")
        logger.info(f"========================================")
        
        result = process_scene(task_id, params, scene, i, total_scenes, used_local_materials, check_cancelled=check_cancelled)
        if result:
            scene_results.append(result)
            logger.info(f"Scene {i+1} processed successfully, combined_video_path: {result.get('combined_video_path')}")
        else:
            logger.error(f"========================================")
            logger.error(f"FAILED to process scene {i+1}/{total_scenes}")
            logger.error(f"The scene result is None, skipping this scene")
            logger.error(f"========================================")
    
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
    final_output_path = path.join(utils.task_dir(task_id), "final-1.mp4")
    step5_start_time = time.time()
    
    # For multi-scene mode, we need to add BGM to the combined video
    # The combined video already has all scene audio, so we just need to add BGM
    logger.info("========================================")
    logger.info("Step 5: Adding background music and final processing")
    logger.info(f"Combined video path: {final_video_path}")
    logger.info(f"Final output path: {final_output_path}")
    logger.info(f"BGM type: {params.bgm_type}")
    logger.info(f"Subtitle enabled: {params.subtitle_enabled}")
    logger.info(f"[TIMESTAMP] Step 5 started at: {time.strftime('%H:%M:%S')}")
    logger.info("========================================")
    
    try:
        from moviepy import VideoFileClip, AudioFileClip, CompositeAudioClip, afx, ColorClip
        import app.services.video as video_module
        from app.services.video_utils import create_encoding_progress_monitor
        
        # Load the combined video (which already has all scene audio)
        logger.info(f"Loading combined video file: {final_video_path}")
        if not os.path.exists(final_video_path):
            logger.error(f"Combined video file does not exist: {final_video_path}")
            raise FileNotFoundError(f"Combined video not found: {final_video_path}")
        
        video_load_start = time.time()
        logger.info(f"[TIMESTAMP] Reading video file with VideoFileClip... ({time.strftime('%H:%M:%S')})")
        video_clip = VideoFileClip(final_video_path)
        video_load_time = time.time() - video_load_start
        logger.info(f"Video loaded successfully in {video_load_time:.2f}s, duration: {video_clip.duration}s, size: {video_clip.size}")
        logger.info(f"[TIMESTAMP] Video loaded at: {time.strftime('%H:%M:%S')}")
        
        # Add pillarbox bars for 3:4 aspect ratio (convert to 9:16)
        # This must happen BEFORE subtitles are added so subtitles are positioned relative to output aspect
        if params.video_aspect:
            from app.models.schema import VideoAspect
            video_aspect = params.video_aspect
            if isinstance(video_aspect, str):
                try:
                    video_aspect = VideoAspect(video_aspect)
                except ValueError:
                    video_aspect = None
            
            if video_aspect == VideoAspect.portrait_3_4:
                from moviepy import ColorClip
                from app.utils.composite_clip_factory import create_composite_video_clip
                from app.services.video_utils import parse_color
                
                clip_w, clip_h = video_clip.size
                target_width, target_height = 1080, 1920
                
                # Calculate scale to fit within target width
                scale_factor = target_width / clip_w
                new_width = round(clip_w * scale_factor)
                new_height = round(clip_h * scale_factor)
                
                # Resize clip to fit target width
                scaled_clip = video_clip.resized(new_size=(new_width, new_height))
                
                # Calculate offset to center vertically
                y_offset = (target_height - new_height) // 2
                
                # Get output background color from params or config
                output_bg_color = getattr(params, 'output_bg_color', None) or 'black'
                bg_color = parse_color(output_bg_color)
                
                # Create background layer with configurable color
                background = ColorClip(
                    size=(target_width, target_height),
                    color=bg_color,
                    duration=video_clip.duration
                )
                
                # Composite the scaled clip on background
                video_clip = create_composite_video_clip([
                    background,
                    scaled_clip.with_position(("center", y_offset))
                ])
                logger.info(f"Added pillarbox for 3:4 -> 9:16: {clip_w}x{clip_h} -> {target_width}x{target_height}")
        
        # Load config for silence duration first
        from app.config.config import silence_duration as config_silence_duration
        silence_duration = 0
        
        # Add Silence Prefix FIRST
        if config_silence_duration > 0:
            from moviepy import ImageClip
            from app.utils.composite_clip_factory import safe_concatenate_videoclips, ensure_clip_duration
            
            # Ensure video_clip has duration first
            video_clip = ensure_clip_duration(video_clip)
            
            # Extract first frame and create a still frame clip
            # Ensure frame is in RGB format (0-255)
            import numpy as np
            first_frame = video_clip.get_frame(0)
            if len(first_frame.shape) == 2:
                # Convert grayscale to RGB
                first_frame = np.stack([first_frame] * 3, axis=-1)
            
            # Create still frame with explicit duration
            still_frame_clip = ImageClip(first_frame, duration=config_silence_duration)
            
            logger.debug(f"- Still frame clip created: type={type(still_frame_clip)}, duration={getattr(still_frame_clip, 'duration', 'NOT SET')}")
            logger.debug(f"- Original video clip before concat: type={type(video_clip)}, duration={getattr(video_clip, 'duration', 'NOT SET')}")
            
            # Concatenate still frame with original video using safe version.
            # The still_frame (ImageClip, no audio) naturally creates a silence gap in the
            # audio track equal to its duration. Do NOT prepend audio silence separately —
            # that would double-shift the audio, causing voice-to-subtitle desync.
            video_clip = safe_concatenate_videoclips([still_frame_clip, video_clip])
            logger.debug(f"- After safe_concatenate_videoclips: type={type(video_clip)}, duration={getattr(video_clip, 'duration', 'NOT SET')}")
            
            silence_duration = config_silence_duration
            
            logger.info(f"Silence Prefix prepended: {silence_duration}s clean still frame")
        
        # Add title AFTER Silence Prefix so it starts at the beginning of the still frame
        if hasattr(params, 'title_enabled') and params.title_enabled and hasattr(params, 'title_text') and params.title_text:
            logger.info("Adding title to multi-scene video")
            from app.services.title import add_title_to_video
            video_clip_before_title = video_clip
            video_clip = add_title_to_video(video_clip, params)
            if video_clip is not video_clip_before_title:
                logger.success("Title overlay added successfully")
            # Note: add_title_to_video logs its own error if title creation fails
        
        # Add subtitle if enabled - with silence prefix offset
        if params.subtitle_enabled and scene_results:
            # Use the new merge_scene_subtitles function to merge subtitles
            from app.services import subtitle
            merged_subtitle_path = subtitle.merge_scene_subtitles(
                task_id, scene_results, silence_duration=silence_duration
            )
            
            # Use merged subtitle if available, otherwise fall back to first scene
            using_merged_subtitle = False
            if merged_subtitle_path and os.path.exists(merged_subtitle_path):
                subtitle_path = merged_subtitle_path
                using_merged_subtitle = True
                logger.info(f"using merged subtitle file: {subtitle_path}")
            else:
                subtitle_path = scene_results[0].get("subtitle_path")
                logger.warning(f"merged subtitle not available, falling back to first scene subtitle: {subtitle_path}")
            
            if subtitle_path and os.path.exists(subtitle_path):
                logger.info("adding subtitle to multi-scene video")
                try:
                    from moviepy import TextClip
                    from app.utils.composite_clip_factory import create_composite_video_clip
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
                            # Apply 5% safety buffer to account for getbbox vs TextClip rendering difference
                            max_width = video_width * (1 - 2 * subtitle_margin) * 0.95
                            subtitle_auto_fit = ui_config.get("subtitle_auto_fit", False)
                            
                            try:
                                # Wrap text to fit within video width
                                wrapped_txt, txt_height, actual_fontsize = video_module.wrap_text(
                                    phrase, max_width=max_width, font=font_path if font_path else "Arial",
                                    fontsize=int(params.font_size), auto_fit=subtitle_auto_fit
                                )
                                # Use the potentially reduced font size from auto-fit
                                _font_size = int(actual_fontsize) if subtitle_auto_fit else int(params.font_size)
                                
                                # Parse time string
                                start_end = time_str.split(" --> ")
                                if len(start_end) == 2:
                                    # Merged subtitles already include silence prefix offset.
                                    # Fallback subtitles (from first scene) do NOT, so add it here.
                                    start_time = _srt_time_to_seconds(start_end[0])
                                    end_time = _srt_time_to_seconds(start_end[1])
                                    if not using_merged_subtitle:
                                        start_time += silence_duration
                                        end_time += silence_duration
                                    
                                    # Create text clip with proper encoding
                                    try:
                                        _clip = TextClip(
                                            text=wrapped_txt,
                                            font=font_path,
                                            font_size=_font_size,
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
                                        margin_px = video_height * subtitle_margin
                                        if params.subtitle_position == "bottom":
                                            _clip = _clip.with_position(("center", video_height - margin_px - _clip.h))
                                        elif params.subtitle_position == "top":
                                            _clip = _clip.with_position(("center", margin_px))
                                        elif params.subtitle_position == "custom":
                                            max_y = video_height - _clip.h - margin_px
                                            min_y = margin_px
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
                                video_clip = create_composite_video_clip([video_clip, *text_clips])
                                logger.success("subtitle added to multi-scene video")
                            except Exception as e:
                                logger.error(f"Failed to composite video with subtitles: {e}")
                        else:
                            logger.warning("No text clips created, skipping subtitle addition")
                except Exception as e:
                    logger.error(f"failed to add subtitle: {str(e)}")
        
        # Add BGM
        logger.info(f"Getting BGM file: bgm_type={params.bgm_type}, bgm_file={params.bgm_file}")
        bgm_file = video_module.get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
        logger.info(f"BGM file result: {bgm_file}")
        
        if bgm_file and os.path.exists(bgm_file):
            try:
                logger.info(f"Loading BGM file: {bgm_file}")
                
                logger.info(f"Processing BGM with effects: volume={params.bgm_volume}")
                bgm_clip = AudioFileClip(bgm_file).with_effects([
                    afx.MultiplyVolume(params.bgm_volume),
                    afx.AudioFadeOut(3),
                    afx.AudioLoop(duration=video_clip.duration),
                ])
                logger.info("BGM loaded and processed successfully")
                
                logger.info("Getting existing audio from video...")
                existing_audio = video_clip.audio
                logger.info(f"Existing audio loaded, duration: {existing_audio.duration if existing_audio else 'None'}s")
                
                logger.info("Combining existing audio with BGM...")
                combined_audio = CompositeAudioClip([existing_audio, bgm_clip])
                video_clip = video_clip.with_audio(combined_audio)
                
                logger.success("BGM added to multi-scene video")
            except Exception as e:
                logger.error(f"failed to add BGM: {str(e)}")
        
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=90)
        
        # Get video encoding parameters (loaded once at module initialization)
        video_encoding_params = video_module.get_video_encoding_params()
        
        # Write final video
        logger.info(f"========================================")
        logger.info(f"[TIMESTAMP] Starting final video encoding at: {time.strftime('%H:%M:%S')}")
        logger.info(f"Writing final video to: {final_output_path}")
        logger.info(f"Encoding parameters: codec={video_module.video_codec}, fps={video_module.fps}, bitrate={video_encoding_params['bitrate']}")
        logger.info("========================================")
        
        logger.info(f"using video encoding: bitrate={video_encoding_params['bitrate']}, codec={video_module.video_codec}")
        
        # Build ffmpeg parameters
        ffmpeg_params = ["-pix_fmt", "yuv420p"]
        if video_encoding_params["crf"] is not None:
            ffmpeg_params.extend(["-crf", str(video_encoding_params["crf"])])
        
        encoding_start_time = time.time()
        logger.info(f"[TIMESTAMP] Video encoding started at: {time.strftime('%H:%M:%S')} (this may take a while)...")
        
        # Create and start progress monitor
        progress_monitor = create_encoding_progress_monitor(
            task_id=task_id,
            output_file=final_output_path,
            progress_callback=None,  # Can be added later if needed
            log_interval=60  # Log every 60 seconds (1 minute)
        )
        progress_monitor.start_monitoring()
        
        try:
            video_clip.write_videofile(
                final_output_path,
                codec=video_module.video_codec,
                audio_codec="aac",
                fps=video_module.fps,
                bitrate=video_encoding_params["bitrate"],
                preset=video_encoding_params["preset"],
                logger=None,  # Keep None to avoid MoviePy compatibility issues
                ffmpeg_params=ffmpeg_params,
            )
        finally:
            # Stop progress monitor after encoding completes
            progress_monitor.stop_monitoring()
        
        encoding_time = time.time() - encoding_start_time
        step5_total_time = time.time() - step5_start_time
        
        # Use close_clip function for proper cleanup
        video_module.close_clip(video_clip)
        
        logger.info(f"========================================")
        logger.info(f"[TIMESTAMP] Video encoding completed at: {time.strftime('%H:%M:%S')}")
        logger.info(f"Video encoding took: {encoding_time:.2f}s")
        logger.info(f"Step 5 total time: {step5_total_time:.2f}s")
        logger.success(f"Final video created: {final_output_path}")
        
        # Calculate total task duration from submission to final video creation
        if task_start_time:
            total_duration = time.time() - task_start_time
            hours = int(total_duration // 3600)
            minutes = int((total_duration % 3600) // 60)
            seconds = int(total_duration % 60)
            formatted_duration = f"{hours}:{minutes:02d}:{seconds:02d}"
            logger.info(f"Total task duration: {formatted_duration}")
        logger.info("========================================")
        
    except Exception as e:
        logger.error(f"========================================")
        logger.error(f"Multi-scene EXCEPTION: {str(e)}")
        logger.error(f"========================================")
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
