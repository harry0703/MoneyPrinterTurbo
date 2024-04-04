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
    audio_clip = AudioFileClip(audio_file)
    audio_duration = audio_clip.duration
    logger.info(f"max duration of audio: {audio_duration} seconds")
    # Required duration of each clip
    req_dur = audio_duration / len(video_paths)
    req_dur = max_clip_duration
    logger.info(f"each clip will be maximum {req_dur} seconds long")

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()

    clips = []
    video_duration = 0
    # Add downloaded clips over and over until the duration of the audio (max_duration) has been reached
    while video_duration < audio_duration:
        # random video_paths order
        if video_concat_mode.value == VideoConcatMode.random.value:
            random.shuffle(video_paths)

        for video_path in video_paths:
            clip = VideoFileClip(video_path).without_audio()
            # Check if clip is longer than the remaining audio
            if (audio_duration - video_duration) < clip.duration:
                clip = clip.subclip(0, (audio_duration - video_duration))
            # Only shorten clips if the calculated clip length (req_dur) is shorter than the actual clip to prevent still image
            elif req_dur < clip.duration:
                clip = clip.subclip(0, req_dur)
            clip = clip.set_fps(30)

            # Not all videos are same size, so we need to resize them
            clip_w, clip_h = clip.size
            if clip_w != video_width or clip_h != video_height:
                clip_ratio = clip.w / clip.h
                video_ratio = video_width / video_height

                if clip_ratio == video_ratio:
                    # 等比例缩放
                    clip = clip.resize((video_width, video_height))
                else:
                    # 等比缩放视频
                    if clip_ratio > video_ratio:
                        # 按照目标宽度等比缩放
                        scale_factor = video_width / clip_w
                    else:
                        # 按照目标高度等比缩放
                        scale_factor = video_height / clip_h

                    new_width = int(clip_w * scale_factor)
                    new_height = int(clip_h * scale_factor)
                    clip_resized = clip.resize(newsize=(new_width, new_height))

                    background = ColorClip(size=(video_width, video_height), color=(0, 0, 0))
                    clip = CompositeVideoClip([
                        background.set_duration(clip.duration),
                        clip_resized.set_position("center")
                    ])

                logger.info(f"resizing video to {video_width} x {video_height}, clip size: {clip_w} x {clip_h}")

            if clip.duration > max_clip_duration:
                clip = clip.subclip(0, max_clip_duration)

            clips.append(clip)
            video_duration += clip.duration

    final_clip = concatenate_videoclips(clips)
    final_clip = final_clip.set_fps(30)
    logger.info(f"writing")
    # https://github.com/harry0703/MoneyPrinterTurbo/issues/111#issuecomment-2032354030
    final_clip.write_videofile(combined_video_path, threads=threads, logger=None)
    logger.success(f"completed")
    return combined_video_path


def wrap_text(text, max_width, font='Arial', fontsize=60):
    # 创建字体对象
    font = ImageFont.truetype(font, fontsize)

    def get_text_size(inner_text):
        inner_text = inner_text.strip()
        left, top, right, bottom = font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    if width <= max_width:
        return text

    logger.warning(f"wrapping text, max_width: {max_width}, text_width: {width}, text: {text}")

    processed = True

    _wrapped_lines_ = []
    words = text.split(" ")
    _txt_ = ''
    for word in words:
        _before = _txt_
        _txt_ += f"{word} "
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            if _txt_.strip() == word.strip():
                processed = False
                break
            _wrapped_lines_.append(_before)
            _txt_ = f"{word} "
    _wrapped_lines_.append(_txt_)
    if processed:
        _wrapped_lines_ = [line.strip() for line in _wrapped_lines_]
        result = '\n'.join(_wrapped_lines_).strip()
        logger.warning(f"wrapped text: {result}")
        return result

    _wrapped_lines_ = []
    chars = list(text)
    _txt_ = ''
    for word in chars:
        _txt_ += word
        _width, _height = get_text_size(_txt_)
        if _width <= max_width:
            continue
        else:
            _wrapped_lines_.append(_txt_)
            _txt_ = ''
    _wrapped_lines_.append(_txt_)
    result = '\n'.join(_wrapped_lines_).strip()
    logger.warning(f"wrapped text: {result}")
    return result


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

    if params.subtitle_position == "top":
        position_height = video_height * 0.1
    elif params.subtitle_position == "bottom":
        position_height = video_height * 0.9
    else:
        position_height = "center"

    def generator(txt, **kwargs):
        max_width = video_width * 0.9
        # logger.debug(f"rendering text: {txt}")
        wrapped_txt = wrap_text(txt,
                                max_width=max_width,
                                font=font_path,
                                fontsize=params.font_size
                                )  # 调整max_width以适应你的视频

        clip = TextClip(
            wrapped_txt,
            font=font_path,
            fontsize=params.font_size,
            color=params.text_fore_color,
            bg_color=params.text_background_color,
            stroke_color=params.stroke_color,
            stroke_width=params.stroke_width,
            print_cmd=False,
        )
        return clip

    clips = [
        VideoFileClip(video_path),
    ]

    if subtitle_path and os.path.exists(subtitle_path):
        sub = SubtitlesClip(subtitles=subtitle_path, make_textclip=generator, encoding='utf-8')
        sub_clip = sub.set_position(lambda _t: ('center', position_height))
        clips.append(sub_clip)

    result = CompositeVideoClip(clips)

    audio = AudioFileClip(audio_path)
    result = result.set_audio(audio)

    temp_output_file = f"{output_file}.temp.mp4"
    logger.info(f"writing to temp file: {temp_output_file}")
    result.write_videofile(temp_output_file, threads=params.n_threads or 2, logger=None)

    video_clip = VideoFileClip(temp_output_file)

    bgm_file = get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
    if bgm_file:
        logger.info(f"adding background music: {bgm_file}")
        # Add song to video at 30% volume using moviepy
        original_duration = video_clip.duration
        original_audio = video_clip.audio
        song_clip = AudioFileClip(bgm_file).set_fps(44100)
        # Set the volume of the song to 10% of the original volume
        song_clip = song_clip.volumex(params.bgm_volume)
        # Add the song to the video
        comp_audio = CompositeAudioClip([original_audio, song_clip])
        video_clip = video_clip.set_audio(comp_audio)
        video_clip = video_clip.set_fps(30)
        video_clip = video_clip.set_duration(original_duration)

    logger.info(f"encoding audio codec to aac")
    video_clip.write_videofile(output_file, audio_codec="aac", threads=params.n_threads or 2, logger=None)

    os.remove(temp_output_file)
    logger.success(f"completed")


if __name__ == "__main__":
    txt_en = "Here's your guide to travel hacks for budget-friendly adventures"
    txt_zh = "测试长字段这是您的旅行技巧指南帮助您进行预算友好的冒险"
    font = utils.resource_dir() + "/fonts/STHeitiMedium.ttc"
    for txt in [txt_en, txt_zh]:
        t = wrap_text(text=txt, max_width=1000, font=font, fontsize=60)
        print(t)

    task_id = "69232dfa-f6c5-4b5e-80ba-be3098d3f930"
    task_dir = utils.task_dir(task_id)
    video_file = f"{task_dir}/combined-1.mp4"
    audio_file = f"{task_dir}/audio.mp3"
    subtitle_file = f"{task_dir}/subtitle.srt"
    output_file = f"{task_dir}/final.mp4"

    video_paths = []
    for file in os.listdir(utils.storage_dir("test")):
        if file.endswith(".mp4"):
            video_paths.append(os.path.join(task_dir, file))

    combine_videos(combined_video_path=video_file,
                   audio_file=audio_file,
                   video_paths=video_paths,
                   video_aspect=VideoAspect.portrait,
                   video_concat_mode=VideoConcatMode.random,
                   max_clip_duration=5,
                   threads=2)

    cfg = VideoParams()
    cfg.video_aspect = VideoAspect.portrait
    cfg.font_name = "STHeitiMedium.ttc"
    cfg.font_size = 60
    cfg.stroke_color = "#000000"
    cfg.stroke_width = 1.5
    cfg.text_fore_color = "#FFFFFF"
    cfg.text_background_color = "transparent"
    cfg.bgm_file = ""
    cfg.bgm_volume = 0.2
    cfg.subtitle_enabled = True
    cfg.subtitle_position = "bottom"
    cfg.n_threads = 2
    cfg.paragraph_number = 1

    generate_video(video_path=video_file,
                   audio_path=audio_file,
                   subtitle_path=subtitle_file,
                   output_file=output_file,
                   params=cfg
                   )
