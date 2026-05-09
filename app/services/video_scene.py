import os
import random
import gc
import time
from typing import List

from loguru import logger
from moviepy import (
    AudioFileClip,
    VideoFileClip,
    concatenate_videoclips,
)

from app.config import config
from app.models.schema import (
    VideoAspect,
    VideoConcatMode,
    VideoTransitionMode,
)
from app.services.utils import video_effects
from app.services.video_utils import (
    SubClippedVideoClip,
    memory_safe_operation,
    memory_safe_wait,
    close_clip,
    crop_clip_to_target,
    fit_intro_video_to_target,
)
from app.services.video_target import finalize_video
from moviepy import ImageClip


@memory_safe_operation
def process_scene_videos(
    scene_video_paths: List[str],
    video_aspect: VideoAspect,
    video_concat_mode: VideoConcatMode,
    video_transition_mode: VideoTransitionMode,
    max_clip_duration: int,
    local_video_paths: List[str] = None,
) -> List:
    """
    Process videos for a single scene
    
    Args:
        scene_video_paths: List of video paths for the scene
        video_aspect: Video aspect ratio
        video_concat_mode: Video concatenation mode
        video_transition_mode: Video transition mode
        max_clip_duration: Maximum clip duration
        local_video_paths: List of local video paths
    
    Returns:
        List of processed video clips
    """
    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()
    
    processed_clips = []
    subclipped_items = []
    
    # Process videos
    for i, video_path in enumerate(scene_video_paths):
        try:
            # Check memory before processing each video
            memory_safe_wait()
            
            clip = VideoFileClip(video_path)
            clip_duration = clip.duration
            clip_w, clip_h = clip.size
            close_clip(clip)
            
            start_time = 0

            while start_time < clip_duration:
                end_time = min(start_time + max_clip_duration, clip_duration)            
                subclip = SubClippedVideoClip(file_path= video_path, start_time=start_time, end_time=end_time, width=clip_w, height=clip_h)
                subclipped_items.append(subclip)
                
                start_time = end_time    
                if video_concat_mode.value == VideoConcatMode.sequential.value:
                    break
        except Exception as e:
            logger.error(f"failed to process video file {video_path}: {str(e)}")
            # Release memory in case of error
            gc.collect()
            continue

    # Apply concat mode to scene's video clips
    if video_concat_mode.value == VideoConcatMode.random.value:
        random.shuffle(subclipped_items)
    
    # Process subclips
    for i, subclipped_item in enumerate(subclipped_items):
        try:
            # Check memory before processing each subclip
            memory_safe_wait()
            
            clip = VideoFileClip(subclipped_item.file_path).subclipped(subclipped_item.start_time, subclipped_item.end_time)
            clip_duration = clip.duration
            
            # Resize if needed
            clip_w, clip_h = clip.size
            if clip_w != video_width or clip_h != video_height:
                clip_ratio = clip.w / clip.h
                video_ratio = video_width / video_height
                
                # Use unified crop function
                if local_video_paths and subclipped_item.file_path in local_video_paths:
                    max_scale = 5.0  # Allow up to 500% upscaling for local materials
                else:
                    max_scale = 1.5 if video_aspect == VideoAspect.portrait_3_4 else 1.10
                
                # Check memory before crop
                memory_safe_wait()
                
                old_clip = clip
                clip = crop_clip_to_target(clip, video_width, video_height, max_scale=max_scale)
                
                # Close old clip to release memory
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")
                
                if clip is None:
                    if local_video_paths and subclipped_item.file_path in local_video_paths:
                        logger.warning(f"Local clip {i+1} could not be processed even with relaxed quality constraints, skipping")
                    else:
                        logger.warning(f"Online clip {i+1} could not be processed within quality constraints, skipping")
                    continue
            
            # Apply transitions
            shuffle_side = random.choice(["left", "right", "top", "bottom"])
            if video_transition_mode and video_transition_mode.value == VideoTransitionMode.none.value:
                clip = clip
            elif video_transition_mode and video_transition_mode.value == VideoTransitionMode.fade_in.value:
                old_clip = clip
                clip = video_effects.fadein_transition(clip,1)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")
            elif video_transition_mode and video_transition_mode.value == VideoTransitionMode.fade_out.value:
                old_clip = clip
                clip = video_effects.fadeout_transition(clip,1)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")
            elif video_transition_mode and video_transition_mode.value == VideoTransitionMode.slide_in.value:
                old_clip = clip
                clip = video_effects.slidein_transition(clip,1, shuffle_side)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")
            elif video_transition_mode and video_transition_mode.value == VideoTransitionMode.slide_out.value:
                old_clip = clip
                clip = video_effects.slideout_transition(clip,1, shuffle_side)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")
            elif video_transition_mode and video_transition_mode.value == VideoTransitionMode.shuffle.value:
                transition_funcs = [
                    lambda c: video_effects.fadein_transition(c,1),
                    lambda c: video_effects.fadeout_transition(c,1),
                    lambda c: video_effects.slidein_transition(c,1, shuffle_side),
                    lambda c: video_effects.slideout_transition(c,1, shuffle_side),
                ]
                shuffle_transition = random.choice(transition_funcs)
                old_clip = clip
                clip = shuffle_transition(clip)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")

            # Check brightness and filter out dark videos
            brightness_threshold = config.app.get("video_brightness_threshold", 0.3)
            try:
                brightness = video_effects.detect_brightness(clip)
                logger.debug(f"Clip brightness: {brightness:.3f}, threshold: {brightness_threshold}")
                
                if brightness < brightness_threshold:
                    logger.warning(f"Skipping dark video clip (brightness: {brightness:.3f} < {brightness_threshold})")
                    close_clip(clip)
                    continue
            except Exception as e:
                logger.debug(f"Error detecting brightness: {e}, continuing with clip")
            
            # Apply brightness and contrast enhancement
            brightness_factor = config.app.get("video_brightness", 1.0)
            contrast_factor = config.app.get("video_contrast", 1.0)
            
            if brightness_factor != 1.0:
                old_clip = clip
                clip = video_effects.brightness_enhance(clip, brightness_factor)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")
            
            if contrast_factor != 1.0:
                old_clip = clip
                clip = video_effects.contrast_enhance(clip, contrast_factor)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")

            if clip.duration > max_clip_duration:
                old_clip = clip
                clip = clip.subclipped(0, max_clip_duration)
                try:
                    if old_clip is not clip:
                        close_clip(old_clip)
                except Exception as e:
                    logger.debug(f"Error closing old clip: {e}")
            
            # Check memory before adding to processed clips
            memory_safe_wait()
            
            processed_clips.append(clip)
            
            # Release memory more frequently
            if len(processed_clips) % 3 == 0:
                logger.debug(f"Releasing memory after processing {len(processed_clips)} clips")
                gc.collect()
                
        except Exception as e:
            logger.error(f"failed to process clip {i+1}: {str(e)}")
            # Release memory in case of error
            gc.collect()
            continue
    
    # Final memory cleanup
    gc.collect()
    return processed_clips

def combine_scene_clips(
    scene_clips: List,
    audio_duration: float,
) -> List:
    """
    Combine clips for a single scene, handling duration matching
    
    Args:
        scene_clips: List of processed clips for the scene
        audio_duration: Target audio duration
    
    Returns:
        List of clips ready for final concatenation
    """
    processed_clips = []
    video_duration = 0
    
    # Add clips from the scene
    for clip in scene_clips:
        if video_duration > audio_duration:
            break
        processed_clips.append(clip)
        video_duration += clip.duration
        
        # Release memory periodically
        if len(processed_clips) % 10 == 0:
            gc.collect()
    
    # Loop if needed to match audio duration
    if video_duration < audio_duration:
        logger.warning(f"video duration ({video_duration:.2f}s) is shorter than audio duration ({audio_duration:.2f}s), looping clips to match audio length.")
        base_duration = video_duration
        if base_duration <= 0:
            logger.error(f"video duration is zero or negative ({video_duration:.2f}s), cannot loop clips")
            return []
        num_loops = int(audio_duration / base_duration) + 1
        logger.info(f"Need {num_loops} loops to match audio duration")
        
        # Only keep base clips in memory and reuse them
        base_clips = processed_clips.copy()
        for i in range(num_loops - 1):
            for clip in base_clips:
                if video_duration >= audio_duration:
                    break
                processed_clips.append(clip)
                video_duration += clip.duration
                # Release memory periodically
                if len(processed_clips) % 10 == 0:
                    gc.collect()
        logger.info(f"video duration: {video_duration:.2f}s, audio duration: {audio_duration:.2f}s, looped {len(processed_clips)-len(base_clips)} clips")
        # Force garbage collection after loop
        gc.collect()
    
    return processed_clips


def combine_early_scenes(
    scene_clips_list: List[List],
    audio_duration: float,
) -> List:
    """
    Combine multiple scenes while maintaining scene order
    
    Args:
        scene_clips_list: List of processed clips for each scene
        audio_duration: Target audio duration
    
    Returns:
        List of clips ready for final concatenation
    """
    processed_clips = []
    video_duration = 0
    
    # Add clips from each scene in order
    for scene_index, scene_clips in enumerate(scene_clips_list):
        logger.info(f"Adding clips from scene {scene_index + 1}")
        for clip in scene_clips:
            if video_duration > audio_duration:
                break
            processed_clips.append(clip)
            video_duration += clip.duration
            
            # Release memory periodically
            if len(processed_clips) % 10 == 0:
                gc.collect()
    
    # Loop if needed to match audio duration
    if video_duration < audio_duration:
        logger.warning(f"video duration ({video_duration:.2f}s) is shorter than audio duration ({audio_duration:.2f}s), looping clips to match audio length.")
        base_duration = video_duration
        if base_duration <= 0:
            logger.error(f"video duration is zero or negative ({video_duration:.2f}s), cannot loop clips")
            return []
        num_loops = int(audio_duration / base_duration) + 1
        logger.info(f"Need {num_loops} loops to match audio duration")
        
        # Only keep base clips in memory and reuse them
        base_clips = processed_clips.copy()
        for i in range(num_loops - 1):
            for clip in base_clips:
                if video_duration >= audio_duration:
                    break
                processed_clips.append(clip)
                video_duration += clip.duration
                # Release memory periodically
                if len(processed_clips) % 10 == 0:
                    gc.collect()
        logger.info(f"video duration: {video_duration:.2f}s, audio duration: {audio_duration:.2f}s, looped {len(processed_clips)-len(base_clips)} clips")
        # Force garbage collection after loop
        gc.collect()
    
    return processed_clips


def build_scene_video(
    combined_video_path: str,
    video_paths: List[str],
    audio_file: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    video_transition_mode: VideoTransitionMode = None,
    max_clip_duration: int = 5,
    threads: int = 2,
    scene_info: str = None,
    local_video_paths: List[str] = None,
    intro_video_path: str = None,
    intro_duration: int = 10,
) -> str:
    # Handle audio_file being None (scene videos already contain audio)
    if audio_file:
        audio_clip = AudioFileClip(audio_file)
        audio_duration = audio_clip.duration
        logger.info(f"audio duration: {audio_duration} seconds")
        # Close audio_clip immediately after getting duration, we'll reopen it later if needed
        close_clip(audio_clip)
        audio_clip = None
    else:
        # Calculate total video duration from scene videos
        audio_duration = 0
        for video_path in video_paths:
            try:
                clip = VideoFileClip(video_path)
                audio_duration += clip.duration
                close_clip(clip)
            except Exception as e:
                logger.error(f"Failed to get duration for {video_path}: {e}")
        logger.info(f"Total video duration: {audio_duration} seconds")
    
    output_dir = os.path.dirname(combined_video_path)

    # Process intro video separately if provided
    intro_clips = []
    if intro_video_path:
        # Check if intro video exists
        if os.path.exists(intro_video_path):
            logger.info(f"Found intro video: {intro_video_path}")
            # Process intro video
            try:
                # Check if intro video is actually an image
                if intro_video_path.endswith(('.png', '.jpg', '.jpeg', '.bmp', '.gif')):
                    # Handle image as intro video with specified duration
                    logger.info(f"Processing image as intro video with duration: {intro_duration:.1f}s")
                    
                    # Create video from image with specified duration
                    clip = ImageClip(intro_video_path).with_duration(intro_duration)
                    
                    clip_duration = intro_duration
                    clip_w, clip_h = clip.size
                    
                    # Process intro clip
                    aspect = VideoAspect(video_aspect)
                    video_width, video_height = aspect.to_resolution()
                    
                    # Process intro video differently: fit without cropping, center on blue background
                    clip = fit_intro_video_to_target(clip, video_width, video_height)
                    
                    # Apply brightness and contrast enhancement
                    brightness_factor = config.app.get("video_brightness", 1.0)
                    contrast_factor = config.app.get("video_contrast", 1.0)
                    
                    if brightness_factor != 1.0:
                        clip = video_effects.brightness_enhance(clip, brightness_factor)
                    
                    if contrast_factor != 1.0:
                        clip = video_effects.contrast_enhance(clip, contrast_factor)
                    
                    intro_clips.append(clip)
                    logger.info(f"Image intro video processed: {intro_video_path} (duration: {intro_duration:.1f}s)")
                else:
                    clip = VideoFileClip(intro_video_path)
                    clip_duration = clip.duration
                    clip_w, clip_h = clip.size
                    close_clip(clip)
                    
                    start_time = 0
                    end_time = min(start_time + intro_duration, clip_duration)
                    subclip = SubClippedVideoClip(file_path=intro_video_path, start_time=start_time, end_time=end_time, width=clip_w, height=clip_h)
                    
                    aspect = VideoAspect(video_aspect)
                    video_width, video_height = aspect.to_resolution()
                    
                    clip = VideoFileClip(subclip.file_path).subclipped(subclip.start_time, subclip.end_time)
                    clip = crop_clip_to_target(clip, video_width, video_height)
                    
                    brightness_factor = config.app.get("video_brightness", 1.0)
                    contrast_factor = config.app.get("video_contrast", 1.0)
                    
                    if brightness_factor != 1.0:
                        clip = video_effects.brightness_enhance(clip, brightness_factor)
                    
                    if contrast_factor != 1.0:
                        clip = video_effects.contrast_enhance(clip, contrast_factor)
                    
                    intro_clips.append(clip)
                    logger.info(f"Video intro processed: {intro_video_path}")
            except Exception as e:
                logger.error(f"Failed to process intro video: {str(e)}")
            
            # Remove intro video from regular video paths if it exists
            normalized_intro_path = os.path.abspath(intro_video_path)
            video_paths = [path for path in video_paths if os.path.abspath(path) != normalized_intro_path]
        else:
            logger.warning(f"Intro video path does not exist: {intro_video_path}")
    else:
        logger.info("No intro video provided")
    
    # Process regular videos as a single scene
    scene_clips = process_scene_videos(
        scene_video_paths=video_paths,
        video_aspect=video_aspect,
        video_concat_mode=video_concat_mode,
        video_transition_mode=video_transition_mode,
        max_clip_duration=max_clip_duration,
        local_video_paths=local_video_paths
    )
    
    # Combine intro clips with scene clips
    all_clips = intro_clips + scene_clips
    
    # Check if we have any processed clips
    if not all_clips:
        logger.error("No video clips were successfully processed")
        return None
    
    # Combine clips to match audio duration
    processed_clips = combine_scene_clips(
        scene_clips=all_clips,
        audio_duration=audio_duration
    )
    
    # Finalize video
    return finalize_video(
        processed_clips=processed_clips,
        combined_video_path=combined_video_path,
        audio_file=audio_file,
        threads=threads
    )
