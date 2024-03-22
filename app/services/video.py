import glob
import random
from typing import List
from PIL import ImageFont
from loguru import logger
from moviepy.editor import *
from moviepy.video.fx.crop import crop
from moviepy.video.tools.subtitles import SubtitlesClip

from app.models.schema import VideoAspect, VideoParams, VideoConcatMode
from app.utils import utils


def get_bgm_file(bgm_type: str = "random", bgm_file: str = ""):
    if not bgm_type:
        return ""
    if bgm_type == "random":
        suffix = "*.mp3"
        song_dir = utils.song_dir()
        files = glob.glob(os.path.join(song_dir, suffix))
        return random.choice(files)

    if os.path.exists(bgm_file):
        return bgm_file

    return ""


def combine_videos(combined_video_path: str,
                   video_paths: List[str],
                   audio_file: str,
                   video_aspect: VideoAspect = VideoAspect.portrait,
                   video_concat_mode: VideoConcatMode = VideoConcatMode.random,
                   max_clip_duration: int = 5,
                   threads: int = 2,
                   ) -> str:
    logger.info(f"combining {len(video_paths)} videos into one file: {combined_video_path}")
    audio_clip = AudioFileClip(audio_file)
    max_duration = audio_clip.duration
    logger.info(f"max duration of audio: {max_duration} seconds")
    # Required duration of each clip
    req_dur = max_duration / len(video_paths)
    logger.info(f"each clip will be maximum {req_dur} seconds long")

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()

    clips = []
    tot_dur = 0
    # Add downloaded clips over and over until the duration of the audio (max_duration) has been reached
    while tot_dur < max_duration:
        # random video_paths order
        if video_concat_mode.value == VideoConcatMode.random.value:
            random.shuffle(video_paths)

        for video_path in video_paths:
            clip = VideoFileClip(video_path)
            clip = clip.without_audio()
            # Check if clip is longer than the remaining audio
            if (max_duration - tot_dur) < clip.duration:
                clip = clip.subclip(0, (max_duration - tot_dur))
            # Only shorten clips if the calculated clip length (req_dur) is shorter than the actual clip to prevent still image
            elif req_dur < clip.duration:
                clip = clip.subclip(0, req_dur)
            clip = clip.set_fps(30)

            # Not all videos are same size, so we need to resize them
            # logger.info(f"{video_path}: size is {clip.w} x {clip.h}, expected {video_width} x {video_height}")
            if clip.w != video_width or clip.h != video_height:
                if round((clip.w / clip.h), 4) < 0.5625:
                    clip = crop(clip,
                                width=clip.w,
                                height=round(clip.w / 0.5625),
                                x_center=clip.w / 2,
                                y_center=clip.h / 2
                                )
                else:
                    clip = crop(clip,
                                width=round(0.5625 * clip.h),
                                height=clip.h,
                                x_center=clip.w / 2,
                                y_center=clip.h / 2
                                )
                logger.info(f"resizing video to {video_width} x {video_height}")
                clip = clip.resize((video_width, video_height))

            if clip.duration > max_clip_duration:
                clip = clip.subclip(0, max_clip_duration)

            clips.append(clip)
            tot_dur += clip.duration

    final_clip = concatenate_videoclips(clips)
    final_clip = final_clip.set_fps(30)
    logger.info(f"writing")
    final_clip.write_videofile(combined_video_path, threads=threads)
    logger.success(f"completed")
    return combined_video_path


def wrap_text(text, max_width, font='Arial', fontsize=60):
    # 创建字体对象
    font = ImageFont.truetype(font, fontsize)

    def get_text_size(inner_text):
        left, top, right, bottom = font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    if width <= max_width:
        return text

    logger.warning(f"wrapping text, max_width: {max_width}, text_width: {width}, text: {text}")
    _wrapped_lines_ = []
    # 使用textwrap尝试分行，然后检查每行是否符合宽度限制

    chars = list(text)
    _txt_ = ''
    for char in chars:
        _txt_ += char
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            _wrapped_lines_.append(_txt_)
            _txt_ = ''
    _wrapped_lines_.append(_txt_)
    return '\n'.join(_wrapped_lines_)


def generate_video(video_path: str,
                   audio_path: str,
                   subtitle_path: str,
                   output_file: str,
                   params: VideoParams,
                   ):
    aspect = VideoAspect(params.video_aspect)
    video_width, video_height = aspect.to_resolution()

    logger.info(f"start, video size: {video_width} x {video_height}")
    logger.info(f"  ① video: {video_path}")
    logger.info(f"  ② audio: {audio_path}")
    logger.info(f"  ③ subtitle: {subtitle_path}")
    logger.info(f"  ④ output: {output_file}")

    font_path = ""
    if params.subtitle_enabled:
        if not params.font_name:
            params.font_name = "STHeitiMedium.ttc"
        font_path = os.path.join(utils.font_dir(), params.font_name)
        if os.name == 'nt':
            font_path = font_path.replace("\\", "/")

        logger.info(f"using font: {font_path}")

    def generator(txt):
        wrapped_txt = wrap_text(txt, max_width=video_width - 100,
                                font=font_path,
                                fontsize=params.font_size)  # 调整max_width以适应你的视频
        return TextClip(
            wrapped_txt,
            font=font_path,
            fontsize=params.font_size,
            color=params.text_fore_color,
            bg_color=params.text_background_color,
            stroke_color=params.stroke_color,
            stroke_width=params.stroke_width,
            print_cmd=False,
        )

    position_height = video_height - 200
    if params.video_aspect == VideoAspect.landscape:
        position_height = video_height - 100

    clips = [
        VideoFileClip(video_path),
    ]

    if subtitle_path and os.path.exists(subtitle_path):
        subtitles = SubtitlesClip(subtitles=subtitle_path, make_textclip=generator, encoding='utf-8')
        clips.append(subtitles.set_position(lambda _t: ('center', position_height)))

    result = CompositeVideoClip(clips)

    audio = AudioFileClip(audio_path)
    result = result.set_audio(audio)

    temp_output_file = f"{output_file}.temp.mp4"
    logger.info(f"writing to temp file: {temp_output_file}")
    result.write_videofile(temp_output_file, threads=params.n_threads or 2)

    video_clip = VideoFileClip(temp_output_file)

    bgm_file = get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
    if bgm_file:
        logger.info(f"adding background music: {bgm_file}")
        # Add song to video at 30% volume using moviepy
        original_duration = video_clip.duration
        original_audio = video_clip.audio
        song_clip = AudioFileClip(bgm_file).set_fps(44100)
        # Set the volume of the song to 10% of the original volume
        song_clip = song_clip.volumex(0.2).set_fps(44100)
        # Add the song to the video
        comp_audio = CompositeAudioClip([original_audio, song_clip])
        video_clip = video_clip.set_audio(comp_audio)
        video_clip = video_clip.set_fps(30)
        video_clip = video_clip.set_duration(original_duration)

    logger.info(f"encoding audio codec to aac")
    video_clip.write_videofile(output_file, audio_codec="aac", threads=params.n_threads or 2)

    os.remove(temp_output_file)
    logger.success(f"completed")
