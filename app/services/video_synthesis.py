import os
import math
import time
from typing import List
from loguru import logger

from app.config import config
from app.config.config import load_config
from app.models import const
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.utils import utils
from app.services.video_utils import (
    analyze_video_params,
)


def scan_task_files(task_id_or_path: str) -> dict:
    """
    Scan task directory and return detected files.
    
    Args:
        task_id_or_path: Task ID or direct directory path
        
    Returns:
        Dictionary containing detected files and their status
    """
    # Check if it's a direct directory path
    if os.path.isdir(task_id_or_path):
        task_dir = task_id_or_path
        task_id = os.path.basename(task_dir)
    else:
        # It's a task ID
        task_id = task_id_or_path
        task_dir = utils.task_dir(task_id)
    
    result = {
        "task_id": task_id,
        "task_dir": task_dir,
        "scene_videos": [],
        "audio_files": [],
        "subtitle_files": [],
        "is_valid": False,
        "total_scenes": 0,
        "combined_video": None,
        "global_audio": None,
        "global_subtitle": None,
    }
    
    if not os.path.exists(task_dir):
        logger.error(f"Task directory does not exist: {task_dir}")
        return result
    
    # Check global audio and subtitle files
    global_audio_path = os.path.join(task_dir, "audio.mp3")
    if os.path.exists(global_audio_path):
        result["global_audio"] = global_audio_path
        result["audio_files"].append(global_audio_path)
        logger.info(f"Found global audio: {global_audio_path}")
    
    global_subtitle_path = os.path.join(task_dir, "subtitle.srt")
    if os.path.exists(global_subtitle_path):
        result["global_subtitle"] = global_subtitle_path
        result["subtitle_files"].append(global_subtitle_path)
        logger.info(f"Found global subtitle: {global_subtitle_path}")
    
    # Scan for scene directories
    scene_dirs = []
    for item in os.listdir(task_dir):
        item_path = os.path.join(task_dir, item)
        if os.path.isdir(item_path) and item.startswith("scene_"):
            try:
                scene_num = int(item.split("_")[1])
                scene_dirs.append((scene_num, item_path))
            except (IndexError, ValueError):
                pass
    
    # Sort by scene number
    scene_dirs.sort(key=lambda x: x[0])
    
    for scene_num, scene_dir in scene_dirs:
        scene_video_path = os.path.join(scene_dir, "combined.mp4")
        scene_audio_path = os.path.join(scene_dir, "audio.mp3")
        scene_subtitle_path = os.path.join(scene_dir, "subtitle.srt")
        
        scene_info = {
            "scene_num": scene_num,
            "scene_dir": scene_dir,
            "video": scene_video_path if os.path.exists(scene_video_path) else None,
            "audio": scene_audio_path if os.path.exists(scene_audio_path) else None,
            "subtitle": scene_subtitle_path if os.path.exists(scene_subtitle_path) else None,
        }
        
        result["scene_videos"].append(scene_info)
        
        if scene_info["audio"]:
            result["audio_files"].append(scene_audio_path)
        if scene_info["subtitle"]:
            result["subtitle_files"].append(scene_subtitle_path)
        
        logger.info(f"Scene {scene_num}: video={scene_info['video'] is not None}, "
                   f"audio={scene_info['audio'] is not None}, "
                   f"subtitle={scene_info['subtitle'] is not None}")
    
    result["total_scenes"] = len(scene_dirs)
    
    # Check if we have valid scene videos to combine
    valid_scenes = [s for s in result["scene_videos"] if s["video"] is not None]
    if valid_scenes:
        result["is_valid"] = True
        logger.info(f"Task scan complete: {len(valid_scenes)} valid scenes found")
    else:
        logger.warning(f"No valid scene videos found in task directory: {task_dir}")
    
    return result


def recover_video_synthesis(task_id_or_path: str, progress_callback=None, start_scene=None, end_scene=None, task_id: str = None, subtitle_params: dict = None, bgm_params: dict = None) -> str:
    """
    Recover video synthesis from existing task files.
    
    This function scans the task directory for existing scene videos,
    audio files, and subtitle files, then combines them into the final video.
    
    Args:
        task_id_or_path: Task ID or direct directory path
        progress_callback: Optional callback function for progress updates
        start_scene: Starting scene number (1-based), None for first scene
        end_scene: Ending scene number (1-based), None for last scene
        task_id: Optional task ID for tracking purposes
        subtitle_params: Optional dictionary of subtitle parameters to override defaults
        bgm_params: Optional dictionary of BGM parameters to override defaults
        
    Returns:
        Path to the final video file, or None if failed
    """
    from app.services import state as sm
    from app.services.state import set_task_running, set_task_completed
    
    start_time = time.time()
    
    # Determine task ID and directory
    if os.path.isdir(task_id_or_path):
        task_dir = task_id_or_path
        if task_id is None:
            task_id = os.path.basename(task_dir)
    else:
        if task_id is None:
            task_id = task_id_or_path
        task_dir = utils.task_dir(task_id)
    
    # Create task log file for scene integration
    task_log_path = os.path.join(task_dir, "scene_integration.log")
    log_handler_id = logger.add(
        task_log_path,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level} | {file}:{line} | {message}\n",
        level="DEBUG",
        rotation="10 MB",
        compression="zip"
    )
    logger.info(f"Scene integration task log file: {task_log_path}")
    
    # Register task in state management
    sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=0, task_type="scene_integration")
    set_task_running("scene_integration", task_id)
    
    logger.info(f"\n\n## Starting video synthesis recovery for task: {task_id}")
    
    try:
        # Scan task directory
        task_files = scan_task_files(task_id_or_path)
        
        if not task_files["is_valid"]:
            end_time = time.time()
            total_time = end_time - start_time
            hours, remainder = divmod(total_time, 3600)
            minutes, seconds = divmod(remainder, 60)
            logger.error("No valid scene videos found in task directory")
            logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, progress=0)
            return None
    
        task_dir = task_files["task_dir"]
        valid_scenes = [s for s in task_files["scene_videos"] if s["video"] is not None]
        
        if not valid_scenes:
            end_time = time.time()
            total_time = end_time - start_time
            hours, remainder = divmod(total_time, 3600)
            minutes, seconds = divmod(remainder, 60)
            logger.error("No valid scenes found")
            logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, progress=0)
            return None
        
        # Apply scene range filtering
        # Default to first scene if start_scene not specified
        actual_start_scene = start_scene if start_scene is not None else 1
        # Default to last scene if end_scene not specified
        actual_end_scene = end_scene if end_scene is not None else len(task_files['scene_videos'])
        
        # Convert to 0-based indices
        start_idx = actual_start_scene - 1
        end_idx = actual_end_scene - 1
        
        # Ensure indices are within bounds
        start_idx = max(0, start_idx)
        end_idx = min(len(valid_scenes) - 1, end_idx)
        
        # Filter scenes
        valid_scenes = valid_scenes[start_idx:end_idx + 1]
        
        if not valid_scenes:
            end_time = time.time()
            total_time = end_time - start_time
            hours, remainder = divmod(total_time, 3600)
            minutes, seconds = divmod(remainder, 60)
            logger.error("No valid scenes in the specified range")
            logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, progress=0)
            return None
        
        logger.info(f"Filtered to {len(valid_scenes)} valid scenes (range: {actual_start_scene}-{actual_end_scene})")
        
        # Determine which audio and subtitle files to use
        subtitle_file = task_files["global_subtitle"]
        
        # Initialize audio_file as None (scene videos already contain audio)
        audio_file = None
        
        if not subtitle_file:
            logger.info("No global subtitle found, searching for scene subtitles...")
            # Collect subtitles from scene directories
            scene_subtitles = []
            for scene in valid_scenes:
                scene_subtitle = scene.get("subtitle")
                if scene_subtitle and os.path.exists(scene_subtitle):
                    scene_subtitles.append(scene_subtitle)
                    logger.info(f"Found scene subtitle: {scene_subtitle}")
    
        if scene_subtitles:
            # Use merge_scene_subtitles function to merge scene subtitles with time offset
            logger.info(f"Merging {len(scene_subtitles)} scene subtitles into global subtitle")
            merged_subtitle_path = os.path.join(task_dir, "merged_subtitle.srt")
            
            try:
                from app.services.subtitle import merge_scene_subtitles
                # Create scene_results list with duration info
                scene_results = []
                for i, scene in enumerate(valid_scenes):
                    scene_result = {
                        "scene_index": i,
                        "subtitle_path": scene.get("subtitle"),
                        "combined_video_path": scene.get("video")
                    }
                    scene_results.append(scene_result)
                
                subtitle_file = merge_scene_subtitles(task_id, scene_results, merged_subtitle_path)
                
                if not subtitle_file:
                    logger.error("Failed to merge subtitles")
            except Exception as e:
                logger.error(f"Failed to merge subtitles: {e}")
        else:
            logger.info("No scene subtitles found, will proceed without subtitles")
        
        # Collect video paths
        video_paths = [s["video"] for s in valid_scenes]
        
        # Get scene integration task directory for the final video
        # Use the provided task_id parameter for the scene integration task
        scene_integration_task_dir = utils.task_dir(task_id)
        logger.info(f"Scene integration task directory: {scene_integration_task_dir}")
        
        # Record the original video generation task ID (where scenes are located)
        original_task_id = os.path.basename(task_dir)
        original_task_info_path = os.path.join(scene_integration_task_dir, "original_task_id.txt")
        with open(original_task_info_path, 'w') as f:
            f.write(original_task_id)
        logger.info(f"Original video generation task ID recorded: {original_task_id}")
        
        # Determine output path with scene range format
        # Use the scene integration task directory instead of scenes directory
        output_path = os.path.join(scene_integration_task_dir, f"scenes_{actual_start_scene}_to_{actual_end_scene}.mp4")
        
        # Get video parameters from config
        _cfg = load_config()
        app_config = _cfg.get("app", {})
        ui_config = _cfg.get("ui", {})
        
        # Handle BGM parameters
        if bgm_params is None:
            bgm_params = {}
        
        bgm_type = bgm_params.get('bgm_type', app_config.get('bgm_type', 'random'))
        bgm_file_param = bgm_params.get('bgm_file', '')
        bgm_volume = float(bgm_params.get('bgm_volume', app_config.get('bgm_volume', 0.2)))
        
        # Get BGM file if BGM is enabled
        if bgm_type and bgm_type != 'none':
            from app.services.video_utils import get_bgm_file
            bgm_file = get_bgm_file(bgm_type=bgm_type, bgm_file=bgm_file_param)
            if bgm_file and os.path.exists(bgm_file):
                logger.info(f"Adding BGM: {bgm_file} with volume: {bgm_volume}")
                audio_file = bgm_file
            else:
                logger.info("No valid BGM file found, using existing audio from scene videos")
        else:
            logger.info("BGM not enabled, using existing audio from scene videos")
        
        # Analyze video parameters from scene videos
        video_params = None
        if video_paths:
            # Analyze first scene video as reference
            video_params = analyze_video_params(video_paths[0])
            
            # Verify other videos
            for i, video_path in enumerate(video_paths[1:], 1):
                other_params = analyze_video_params(video_path)
                if other_params:
                    # Check if parameters match
                    if other_params["width"] != video_params["width"] or \
                       other_params["height"] != video_params["height"]:
                        logger.warning(f"Scene {i+1} video parameters don't match reference")
                else:
                    logger.warning(f"Failed to analyze scene {i+1} video")
        
        # Create VideoParams object
        from app.models.schema import VideoParams, VideoAspect, VideoConcatMode
        
        # Determine video aspect ratio
        if video_params:
            # Calculate aspect ratio from video dimensions
            width, height = video_params["width"], video_params["height"]
            # Simplify aspect ratio
            gcd = math.gcd(width, height)
            aspect_ratio = f"{width//gcd}:{height//gcd}"
            logger.info(f"Using detected aspect ratio: {aspect_ratio}")
        else:
            # Fall back to config
            aspect_ratio = app_config.get("video_aspect", "9:16")
            logger.info(f"Using config aspect ratio: {aspect_ratio}")
        
        # Use subtitle_params if provided, otherwise fall back to config
        if subtitle_params is None:
            subtitle_params = {}
        
        # Use bgm_params if provided, otherwise fall back to config
        if bgm_params is None:
            bgm_params = {}
        
        params = VideoParams(
            video_subject="Recovered Video",
            video_aspect=VideoAspect(aspect_ratio),
            video_concat_mode=VideoConcatMode(app_config.get("video_concat_mode", "random")),
            subtitle_enabled=subtitle_params.get('subtitle_enabled', app_config.get("subtitle_enabled", ui_config.get("subtitle_enabled", True))),
            font_name=subtitle_params.get('font_name', app_config.get("font_name", ui_config.get("font_name", "STHeitiMedium.ttc"))),
            font_size=subtitle_params.get('font_size', app_config.get("font_size", ui_config.get("font_size", 60))),
            text_fore_color=subtitle_params.get('text_fore_color', app_config.get("text_fore_color", ui_config.get("text_fore_color", "white"))),
            text_background_color=subtitle_params.get('text_background_color', app_config.get("text_background_color", ui_config.get("text_background_color", "transparent"))),
            stroke_color=subtitle_params.get('stroke_color', app_config.get("stroke_color", ui_config.get("stroke_color", "black"))),
            stroke_width=subtitle_params.get('stroke_width', app_config.get("stroke_width", ui_config.get("stroke_width", 2))),
            subtitle_position=subtitle_params.get('subtitle_position', app_config.get("subtitle_position", ui_config.get("subtitle_position", "bottom"))),
            custom_position=subtitle_params.get('custom_position', app_config.get("subtitle_custom_position", ui_config.get("subtitle_custom_position", 70.0))),
            bgm_type=bgm_params.get('bgm_type', app_config.get("bgm_type", ui_config.get("bgm_type", "random"))),
            bgm_file=bgm_params.get('bgm_file', ''),
            bgm_volume=float(bgm_params.get('bgm_volume', app_config.get("bgm_volume", ui_config.get("bgm_volume", 0.2)))),
            # Title parameters from UI config (title settings are in [ui] section)
            title_enabled=ui_config.get("title_enabled", False),
            title_text=ui_config.get("title_text", ""),
            title_duration=ui_config.get("title_duration", 3.0),
            title_font_name=ui_config.get("title_font_name", ui_config.get("title_font", "MicrosoftYaHeiBold.ttc")),
            title_font_size=ui_config.get("title_font_size", 72),
            title_text_color=ui_config.get("title_text_color", ui_config.get("title_color", "#FFFFFF")),
            title_stroke_color=ui_config.get("title_stroke_color", "#000000"),
            title_stroke_width=ui_config.get("title_stroke_width", 2.0),
            title_background_color=ui_config.get("title_background_color", ui_config.get("title_bg_color", "transparent")),
            title_position=ui_config.get("title_position", "center"),
            title_margin=ui_config.get("title_margin", 0.05),
            title_margin_left=ui_config.get("title_margin_left", 0.05),
            title_margin_right=ui_config.get("title_margin_right", 0.05),
            title_animation=ui_config.get("title_animation", "none"),
            title_animation_duration=ui_config.get("title_animation_duration", 0.5),
            title_background_overlay=ui_config.get("title_background_overlay", False),
            title_overlay_color=ui_config.get("title_overlay_color", "rgba(0,0,0,0.5)"),
            title_align=ui_config.get("title_align", "center")
        )
        
        # Log title parameters for debugging
        logger.info(f"=== Title Configuration ===")
        logger.info(f"title_enabled: {params.title_enabled}")
        logger.info(f"title_text: '{params.title_text}'")
        logger.info(f"title_duration: {params.title_duration}")
        logger.info(f"title_font_name: {params.title_font_name}")
        logger.info(f"title_font_size: {params.title_font_size}")
        logger.info(f"title_text_color: {params.title_text_color}")
        logger.info(f"title_stroke_color: {params.title_stroke_color}")
        logger.info(f"title_stroke_width: {params.title_stroke_width}")
        logger.info(f"title_position: {params.title_position}")
        logger.info(f"title_margin: {params.title_margin}")
        logger.info(f"title_align: {params.title_align}")
        logger.info(f"title_animation: {params.title_animation}")
        logger.info(f"=== Title Configuration End ===")
        
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=20)
        
        if progress_callback:
            progress_callback(20, "Preparing video files...")
        
        # For scene integration tasks (target video level), use combine_all_scenes
        logger.info(f"Combining {len(video_paths)} scene videos using combine_all_scenes for scene integration task")
        
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=40)
        
        if progress_callback:
            progress_callback(40, "Combining scene videos...")
        
        try:
            # Create scene_results list for combine_all_scenes and process_final_video
            scene_results = []
            for i, video_path in enumerate(video_paths):
                scene_result = {
                    "combined_video_path": video_path
                }
                scene_results.append(scene_result)
            
            # Use combine_all_scenes function
            # Use scene integration task directory for temporary file
            combined_video_path = os.path.join(scene_integration_task_dir, "temp_combined_scenes.mp4")
            
            # Import combine_all_scenes from task module
            from app.services.task import combine_all_scenes
            combined_video_path = combine_all_scenes(
                task_id=task_id,
                params=params,
                scene_results=scene_results
            )
            
            if not combined_video_path:
                end_time = time.time()
                total_time = end_time - start_time
                hours, remainder = divmod(total_time, 3600)
                minutes, seconds = divmod(remainder, 60)
                logger.error("Failed to combine scene videos")
                logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
                sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, progress=0)
                set_task_completed()
                return None
            
            logger.success(f"Combined video created: {combined_video_path}")
            
        except Exception as e:
            end_time = time.time()
            total_time = end_time - start_time
            hours, remainder = divmod(total_time, 3600)
            minutes, seconds = divmod(remainder, 60)
            logger.error(f"Failed to combine scene videos: {e}")
            logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, progress=0)
            set_task_completed()
            return None
        
        sm.state.update_task(task_id, state=const.TASK_STATE_PROCESSING, progress=60)
        
        if progress_callback:
            progress_callback(60, "Generating final video...")
        
        # Use the shared process_final_video function to handle silence prefix, title, subtitles, and BGM
        try:
            from app.services.video_target import process_final_video
            output_path = process_final_video(
                task_id=task_id,
                params=params,
                scene_results=scene_results,
                combined_video_path=combined_video_path,
                subtitle_file=subtitle_file,
                audio_file=audio_file,
                output_file=output_path,
                progress_callback=progress_callback
            )
            
            if output_path and os.path.exists(output_path):
                end_time = time.time()
                total_time = end_time - start_time
                hours, remainder = divmod(total_time, 3600)
                minutes, seconds = divmod(remainder, 60)
                logger.success(f"Final video generated: {output_path}")
                logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
                
                sm.state.update_task(task_id, state=const.TASK_STATE_COMPLETE, progress=100, videos=[output_path])
                set_task_completed()
                return output_path
            else:
                end_time = time.time()
                total_time = end_time - start_time
                hours, remainder = divmod(total_time, 3600)
                minutes, seconds = divmod(remainder, 60)
                logger.error("Failed to generate final video")
                logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
                sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, progress=0)
                set_task_completed()
                return None
                
        except Exception as e:
            end_time = time.time()
            total_time = end_time - start_time
            hours, remainder = divmod(total_time, 3600)
            minutes, seconds = divmod(remainder, 60)
            logger.error(f"Failed to generate final video: {e}")
            logger.info(f"Task duration: {int(hours):02d}:{int(minutes):02d}:{int(seconds):02d}")
            sm.state.update_task(task_id, state=const.TASK_STATE_FAILED, progress=0)
            set_task_completed()
            return None
    
    finally:
        # Remove log handler
        try:
            logger.remove(log_handler_id)
        except:
            pass
        set_task_completed()
