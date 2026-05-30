import glob
import itertools
import io
import os
import random
import gc
import shutil
import subprocess
from contextlib import redirect_stdout
from typing import List
from loguru import logger
from moviepy import (
    AudioFileClip,
    ColorClip,
    CompositeAudioClip,
    CompositeVideoClip,
    ImageClip,
    TextClip,
    VideoFileClip,
    afx,
)
from moviepy.video.tools.subtitles import SubtitlesClip
from PIL import Image, ImageFont

from app.models import const
from app.models.schema import (
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoParams,
    VideoTransitionMode,
)
from app.services.utils import video_effects
from app.utils import file_security, utils

class SubClippedVideoClip:
    def __init__(self, file_path, start_time=None, end_time=None, width=None, height=None, duration=None):
        self.file_path = file_path
        self.start_time = start_time
        self.end_time = end_time
        self.width = width
        self.height = height
        if duration is None:
            self.duration = end_time - start_time
        else:
            self.duration = duration

    def __str__(self):
        return f"SubClippedVideoClip(file_path={self.file_path}, start_time={self.start_time}, end_time={self.end_time}, duration={self.duration}, width={self.width}, height={self.height})"


audio_codec = "aac"
# Docker 환경의 ffmpeg/AAC 조합은 기본 설정에서 음질 변동이 발생하기 쉬우므로,
# 여기서 오디오 비트레이트를 명시적으로 높여, 완성 단계에서 기본값이 너무 낮아 뚜렷한 음질 손상이 생기는 것을 방지한다.
audio_bitrate = "192k"
video_codec = "libx264"
fps = 30
_BGM_EXTENSIONS = (".mp3",)


def get_ffmpeg_binary():
    # 사용자가 config.toml / 환경 변수에 명시적으로 지정한 ffmpeg를 우선 재사용하여,
    # Windows 휴대용 패키지, Docker, 커스텀 설치 디렉터리 등에서 PATH가 일치하지 않는 문제를 방지한다.
    configured_ffmpeg = os.environ.get("IMAGEIO_FFMPEG_EXE")
    if configured_ffmpeg:
        return configured_ffmpeg

    system_ffmpeg = shutil.which("ffmpeg")
    if system_ffmpeg:
        return system_ffmpeg

    try:
        import imageio_ffmpeg

        bundled_ffmpeg = imageio_ffmpeg.get_ffmpeg_exe()
        if bundled_ffmpeg:
            return bundled_ffmpeg
    except Exception as exc:
        logger.warning(f"failed to resolve bundled ffmpeg binary: {str(exc)}")

    return "ffmpeg"


def _escape_ffmpeg_concat_path(file_path: str) -> str:
    # concat demuxer는 경로를 작은따옴표로 감싸므로, 경로에 포함된 작은따옴표는 먼저 이스케이프해야 한다.
    return file_path.replace("'", "'\\''")


def concat_video_clips_with_ffmpeg(
    clip_files: List[str], output_file: str, threads: int, output_dir: str
):
    concat_list_file = os.path.join(output_dir, "ffmpeg-concat-list.txt")
    with open(concat_list_file, "w", encoding="utf-8") as fp:
        for clip_file in clip_files:
            absolute_path = os.path.abspath(clip_file)
            fp.write(f"file '{_escape_ffmpeg_concat_path(absolute_path)}'\n")

    command = [
        get_ffmpeg_binary(),
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_list_file,
        "-c:v",
        video_codec,
        "-threads",
        str(threads or 2),
        "-pix_fmt",
        "yuv420p",
        output_file,
    ]

    try:
        # ffmpeg로 이어붙이기와 인코딩을 한 번만 수행하여, MoviePy가 구간별로 병합하며 반복적으로 재인코딩하는 것을 피하고,
        # 이를 통해 화질 저하와 색상 변형 위험을 줄인다.
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            error_message = (result.stderr or result.stdout or "").strip()
            raise RuntimeError(error_message or "ffmpeg concat failed")
    finally:
        delete_files(concat_list_file)


def _sanitize_image_file(image_path: str) -> str:
    # 일부 로컬 이미지는 Pillow로 열 수는 있지만, 손상된 EXIF/eXIf 메타데이터 때문에
    # ImageClip이 파싱 단계에서 곧바로 예외를 던질 수 있다. 여기서 "깨끗한 이미지"로 다시 내보내, 손상된 메타데이터를 제거한다.
    image_root, _ = os.path.splitext(image_path)
    sanitized_path = f"{image_root}.sanitized.png"

    with Image.open(image_path) as image:
        image.load()
        # 일괄적으로 PNG로 내보내, JPEG/PNG의 서로 다른 메타데이터 경로가 손상된 블록을 계속 끌고 가는 것을 방지한다.
        cleaned_image = Image.new(image.mode, image.size)
        cleaned_image.putdata(list(image.getdata()))
        cleaned_image.save(sanitized_path)

    return sanitized_path


def _open_image_clip_with_fallback(image_path: str):
    # 원본 이미지를 직접 여는 것을 우선하되, 손상된 메타데이터로 인해 실패하면 메타데이터 없는 사본을 생성해 다시 시도한다.
    try:
        return ImageClip(image_path), image_path
    except Exception as exc:
        logger.warning(
            f"failed to open image directly, trying sanitized copy: {image_path}, error: {str(exc)}"
        )
        sanitized_path = _sanitize_image_file(image_path)
        return ImageClip(sanitized_path), sanitized_path


def _open_video_clip_quietly(video_path: str, audio: bool = False) -> VideoFileClip:
    """
    조용히 비디오 파일을 열어, MoviePy 2.1.x가 ffmpeg 탐지 정보를 stdout에 직접 출력하는 것을 방지한다.

    배경:
    현재 의존성 버전의 `FFMPEG_VideoReader` 내부에는 `print(self.infos)`와
    `print(ffmpeg command)`가 있어, 오디오 트랙이 없는 중간 비디오를 읽을 때
    `audio_found: False`를 출력한다. 이는 입력 소재의 metadata일 뿐 최종 완성본에 오디오가 없다는 뜻은 아니지만,
    WebUI/터미널 사용자가 생성이 실패했다고 오해하게 만든다.

    구현:
    1. VideoFileClip을 여는 짧은 구간에서만 stdout을 리다이렉트한다.
    2. 기본값을 `audio=False`로 둔다. 프로젝트의 비디오 소재 단계에서는 소재의 원본 음성을 유지할 필요가 없고,
       최종 오디오는 `generate_video()` 단계에서 일괄적으로 입혀지기 때문이다.
    3. 의존성 라이브러리가 실제로 무언가를 출력했다면 debug 로그로 낮춰, 필요할 때 진단하기 쉽게 한다.
    """
    captured_stdout = io.StringIO()
    with redirect_stdout(captured_stdout):
        clip = VideoFileClip(video_path, audio=audio)

    moviepy_stdout = captured_stdout.getvalue().strip()
    if moviepy_stdout:
        logger.debug(
            "suppressed MoviePy video reader stdout for "
            f"{video_path}, chars: {len(moviepy_stdout)}"
        )

    return clip


def close_clip(clip):
    if clip is None:
        return
        
    try:
        # close main resources
        if hasattr(clip, 'reader') and clip.reader is not None:
            clip.reader.close()
            
        # close audio resources
        if hasattr(clip, 'audio') and clip.audio is not None:
            if hasattr(clip.audio, 'reader') and clip.audio.reader is not None:
                clip.audio.reader.close()
            del clip.audio
            
        # close mask resources
        if hasattr(clip, 'mask') and clip.mask is not None:
            if hasattr(clip.mask, 'reader') and clip.mask.reader is not None:
                clip.mask.reader.close()
            del clip.mask
            
        # handle child clips in composite clips
        if hasattr(clip, 'clips') and clip.clips:
            for child_clip in clip.clips:
                if child_clip is not clip:  # avoid possible circular references
                    close_clip(child_clip)
            
        # clear clip list
        if hasattr(clip, 'clips'):
            clip.clips = []
            
    except Exception as e:
        logger.error(f"failed to close clip: {str(e)}")
    
    del clip
    gc.collect()

def delete_files(files: List[str] | str):
    if isinstance(files, str):
        files = [files]

    for file in files:
        try:
            os.remove(file)
        except Exception as e:
            logger.debug(f"failed to delete file {file}: {str(e)}")


def _resolve_bgm_file_path(song_dir: str, bgm_file: str) -> str:
    # 배경 음악은 resource/songs 디렉터리 내의 파일만 읽도록 허용하여, 사용자가 임의의 경로를 입력해
    # MoviePy가 열게 되는 것을 방지한다. 여기서는 흔한 두 가지 입력을 호환한다.
    # 1. output000.mp3: BGM 목록에서 왔거나 사용자가 파일명만 입력한 경우
    # 2. ./resource/songs/output000.mp3: 사용자가 프로젝트 디렉터리 구조에 맞춰 입력한 상대 경로
    # 두 표기 모두 최종적으로 resource/songs 화이트리스트 검증을 다시 거치므로, 디렉터리 제한을 우회할 수 없다.
    try:
        return file_security.resolve_path_within_directory(song_dir, bgm_file)
    except ValueError as song_dir_exc:
        if os.path.isabs(bgm_file):
            raise song_dir_exc

        project_relative_file = os.path.join(utils.root_dir(), bgm_file)
        try:
            return file_security.resolve_path_within_directory(
                song_dir, project_relative_file
            )
        except ValueError as root_dir_exc:
            raise ValueError(str(root_dir_exc)) from song_dir_exc


def get_bgm_file(bgm_type: str = "random", bgm_file: str = ""):
    if not bgm_type:
        return ""

    if bgm_file:
        song_dir = utils.song_dir()
        try:
            resolved_bgm_file = _resolve_bgm_file_path(song_dir, bgm_file)
        except ValueError as exc:
            # API 요청의 bgm_file은 사용자 입력에서 오므로, 임의의 절대 경로를 그대로
            # MoviePy에 넘겨 열어서는 안 된다. 여기서 resource/songs 디렉터리로 강제 제한하여
            # /etc/passwd, 설정 파일, 키 등 배경 음악이 아닌 파일을 읽는 것을 차단한다.
            logger.warning(
                f"reject unsafe bgm file: {bgm_file}, song_dir: {song_dir}, error: {str(exc)}"
            )
            return ""

        if not resolved_bgm_file.lower().endswith(_BGM_EXTENSIONS):
            logger.warning(f"reject unsupported bgm file extension: {resolved_bgm_file}")
            return ""

        return resolved_bgm_file

    if bgm_type == "random":
        suffix = "*.mp3"
        song_dir = utils.song_dir()
        files = glob.glob(os.path.join(song_dir, suffix))
        # 배경 음악 디렉터리가 비어 있으면 곧바로 "BGM 미사용"으로 폴백하여, random.choice([])가 예외를 던지는 것을 방지한다.
        if not files:
            logger.warning(f"no bgm files found in song directory: {song_dir}")
            return ""
        return random.choice(files)

    return ""


def combine_videos(
    combined_video_path: str,
    video_paths: List[str],
    audio_file: str,
    video_aspect: VideoAspect = VideoAspect.portrait,
    video_concat_mode: VideoConcatMode = VideoConcatMode.random,
    video_transition_mode: VideoTransitionMode = None,
    max_clip_duration: int = 5,
    threads: int = 2,
) -> str:
    audio_clip = AudioFileClip(audio_file)
    try:
        # 여기서는 소재 비디오 이어붙이기 길이를 결정하기 위해 내레이션 오디오 길이만 읽으면 되고, 이후
        # audio_clip은 다시 사용하지 않는다. 읽기를 마치면 즉시 닫아, 조기 반환이나 예외 경로에서 파일 핸들이 누수되는 것을 방지한다.
        audio_duration = audio_clip.duration
    finally:
        close_clip(audio_clip)
    logger.info(f"audio duration: {audio_duration} seconds")
    logger.info(f"maximum clip duration: {max_clip_duration} seconds")

    # API를 직접 호출할 때 전환 모드를 전달하지 않은 경우를 호환하여, 이후 .value에 접근할 때 크래시가 나는 것을 방지한다.
    transition_value = getattr(video_transition_mode, "value", video_transition_mode)
    output_dir = os.path.dirname(combined_video_path)

    aspect = VideoAspect(video_aspect)
    video_width, video_height = aspect.to_resolution()

    processed_clips = []
    subclipped_items = []
    video_duration = 0
    for video_path in video_paths:
        clip = _open_video_clip_quietly(video_path)
        clip_duration = clip.duration
        clip_w, clip_h = clip.size
        close_clip(clip)
        
        start_time = 0

        while start_time < clip_duration:
            end_time = min(start_time + max_clip_duration, clip_duration)

            # 유효한 모든 구간을 보존한다.
            # 이렇게 하면 "영상 전체가 애초에 max_clip_duration보다 짧은" 소재를 잃지 않고,
            # 긴 영상의 마지막에 남은 짧은 꼬리 구간도 삼키지 않는다.
            if end_time > start_time:
                subclipped_items.append(
                    SubClippedVideoClip(
                        file_path=video_path,
                        start_time=start_time,
                        end_time=end_time,
                        width=clip_w,
                        height=clip_h,
                    )
                )

            start_time = end_time
            if video_concat_mode.value == VideoConcatMode.sequential.value:
                break

    # random subclipped_items order
    if video_concat_mode.value == VideoConcatMode.random.value:
        random.shuffle(subclipped_items)
        
    logger.debug(f"total subclipped items: {len(subclipped_items)}")
    
    # Add downloaded clips over and over until the duration of the audio (max_duration) has been reached
    for i, subclipped_item in enumerate(subclipped_items):
        if video_duration > audio_duration:
            break
        
        logger.debug(f"processing clip {i+1}: {subclipped_item.width}x{subclipped_item.height}, current duration: {video_duration:.2f}s, remaining: {audio_duration - video_duration:.2f}s")
        
        try:
            clip = _open_video_clip_quietly(subclipped_item.file_path).subclipped(
                subclipped_item.start_time, subclipped_item.end_time
            )
            clip_duration = clip.duration
            # Not all videos are same size, so we need to resize them
            clip_w, clip_h = clip.size
            if clip_w != video_width or clip_h != video_height:
                clip_ratio = clip.w / clip.h
                video_ratio = video_width / video_height
                logger.debug(f"resizing clip, source: {clip_w}x{clip_h}, ratio: {clip_ratio:.2f}, target: {video_width}x{video_height}, ratio: {video_ratio:.2f}")
                
                if clip_ratio == video_ratio:
                    clip = clip.resized(new_size=(video_width, video_height))
                else:
                    if clip_ratio > video_ratio:
                        scale_factor = video_width / clip_w
                    else:
                        scale_factor = video_height / clip_h

                    new_width = int(clip_w * scale_factor)
                    new_height = int(clip_h * scale_factor)

                    background = ColorClip(size=(video_width, video_height), color=(0, 0, 0)).with_duration(clip_duration)
                    clip_resized = clip.resized(new_size=(new_width, new_height)).with_position("center")
                    clip = CompositeVideoClip([background, clip_resized])
                    
            shuffle_side = random.choice(["left", "right", "top", "bottom"])
            if transition_value in (None, VideoTransitionMode.none.value):
                clip = clip
            elif transition_value == VideoTransitionMode.fade_in.value:
                clip = video_effects.fadein_transition(clip, 1)
            elif transition_value == VideoTransitionMode.fade_out.value:
                clip = video_effects.fadeout_transition(clip, 1)
            elif transition_value == VideoTransitionMode.slide_in.value:
                clip = video_effects.slidein_transition(clip, 1, shuffle_side)
            elif transition_value == VideoTransitionMode.slide_out.value:
                clip = video_effects.slideout_transition(clip, 1, shuffle_side)
            elif transition_value == VideoTransitionMode.shuffle.value:
                transition_funcs = [
                    lambda c: video_effects.fadein_transition(c, 1),
                    lambda c: video_effects.fadeout_transition(c, 1),
                    lambda c: video_effects.slidein_transition(c, 1, shuffle_side),
                    lambda c: video_effects.slideout_transition(c, 1, shuffle_side),
                ]
                shuffle_transition = random.choice(transition_funcs)
                clip = shuffle_transition(clip)

            if clip.duration > max_clip_duration:
                clip = clip.subclipped(0, max_clip_duration)
                
            # wirte clip to temp file
            clip_file = f"{output_dir}/temp-clip-{i+1}.mp4"
            clip.write_videofile(clip_file, logger=None, fps=fps, codec=video_codec)

            # Store clip duration before closing
            clip_duration_saved = clip.duration
            close_clip(clip)

            processed_clips.append(SubClippedVideoClip(file_path=clip_file, duration=clip_duration_saved, width=clip_w, height=clip_h))
            video_duration += clip_duration_saved
            
        except Exception as e:
            logger.error(f"failed to process clip: {str(e)}")
    
    # loop processed clips until the video duration matches or exceeds the audio duration.
    if video_duration < audio_duration:
        logger.warning(f"video duration ({video_duration:.2f}s) is shorter than audio duration ({audio_duration:.2f}s), looping clips to match audio length.")
        base_clips = processed_clips.copy()
        for clip in itertools.cycle(base_clips):
            if video_duration >= audio_duration:
                break
            processed_clips.append(clip)
            video_duration += clip.duration
        logger.info(f"video duration: {video_duration:.2f}s, audio duration: {audio_duration:.2f}s, looped {len(processed_clips)-len(base_clips)} clips")
     
    # merge video clips progressively, avoid loading all videos at once to avoid memory overflow
    logger.info("starting clip merging process")
    if not processed_clips:
        logger.warning("no clips available for merging")
        return combined_video_path
    
    # if there is only one clip, use it directly
    if len(processed_clips) == 1:
        logger.info("using single clip directly")
        shutil.copy(processed_clips[0].file_path, combined_video_path)
        delete_files([processed_clips[0].file_path])
        logger.info("video combining completed")
        return combined_video_path

    clip_files = [clip.file_path for clip in processed_clips]
    logger.info(f"concatenating {len(clip_files)} clips with ffmpeg")
    concat_video_clips_with_ffmpeg(
        clip_files=clip_files,
        output_file=combined_video_path,
        threads=threads,
        output_dir=output_dir,
    )
    
    # clean temp files
    delete_files(clip_files)
            
    logger.info("video combining completed")
    return combined_video_path


def wrap_text(text, max_width, font="Arial", fontsize=60):
    # 자막 줄바꿈은 반드시 TextClip을 실제로 생성하기 전에 완료해야 한다. 그렇지 않으면 MoviePy가 원본 텍스트 기준으로만
    # 렌더링 영역을 계산한다. 여기서는 PIL로 현재 폰트와 폰트 크기에 맞춰 너비를 측정하여, 각 줄이 최대한
    # 영상의 사용 가능한 너비 안에 들어오도록 하고, 큰 폰트나 긴 중국어 문장이 화면 밖으로 넘치는 것을 방지한다.
    font = ImageFont.truetype(font, fontsize)
    max_width = int(max_width)

    def get_text_size(inner_text):
        inner_text = inner_text.strip()
        if not inner_text:
            return 0, fontsize
        left, top, right, bottom = font.getbbox(inner_text)
        return right - left, bottom - top

    width, height = get_text_size(text)
    if width <= max_width:
        return text, height

    def split_long_token(token):
        # 하나의 token 자체가 너비를 초과하는 경우(공백 없는 긴 중국어 문장이나 지나치게 긴 영어 단어에서 흔함),
        # 문자 단위 분할로 전환한다. 핵심은, candidate가 너비를 초과한 것을 감지하면 먼저 아직
        # 유효한 직전 current를 확정하고, 현재 문자를 다음 줄에 넣는 것이다. 너비 초과 문자를 이전 줄에 다시 밀어 넣어서는 안 된다.
        lines = []
        current = ""
        for char in token:
            candidate = f"{current}{char}"
            candidate_width, _ = get_text_size(candidate)
            if candidate_width <= max_width or not current:
                current = candidate
                continue
            lines.append(current)
            current = char
        if current:
            lines.append(current)
        return lines

    lines = []
    current = ""
    words = text.split(" ")
    for word in words:
        candidate = f"{current} {word}".strip() if current else word
        candidate_width, _ = get_text_size(candidate)
        if candidate_width <= max_width:
            current = candidate
            continue

        if current:
            lines.append(current)

        word_width, _ = get_text_size(word)
        if word_width <= max_width:
            current = word
        else:
            lines.extend(split_long_token(word))
            current = ""

    if current:
        lines.append(current)

    result = "\n".join(line.strip() for line in lines if line.strip()).strip()
    height = len(lines) * height
    return result, height


def generate_video(
    video_path: str,
    audio_path: str,
    subtitle_path: str,
    output_file: str,
    params: VideoParams,
):
    aspect = VideoAspect(params.video_aspect)
    video_width, video_height = aspect.to_resolution()

    logger.info(f"generating video: {video_width} x {video_height}")
    logger.info(f"  ① video: {video_path}")
    logger.info(f"  ② audio: {audio_path}")
    logger.info(f"  ③ subtitle: {subtitle_path}")
    logger.info(f"  ④ output: {output_file}")

    # https://github.com/harry0703/MoneyPrinterTurbo/issues/217
    # PermissionError: [WinError 32] The process cannot access the file because it is being used by another process: 'final-1.mp4.tempTEMP_MPY_wvf_snd.mp3'
    # write into the same directory as the output file
    output_dir = os.path.dirname(output_file)

    font_path = ""
    if params.subtitle_enabled:
        if not params.font_name:
            params.font_name = "STHeitiMedium.ttc"
        font_path = os.path.join(utils.font_dir(), params.font_name)
        if os.name == "nt":
            font_path = font_path.replace("\\", "/")

        logger.info(f"  ⑤ font: {font_path}")

    def resolve_subtitle_background_color():
        # 과거 파라미터 호환: API의 `text_background_color`는 불리언 값일 수도 있고
        # 실제 색상 문자열일 수도 있다. 여기서 일괄적으로 정규화하여, True/False를
        # TextClip에 그대로 전달했을 때 예측 불가능한 렌더링 결과가 나오는 것을 방지한다.
        if isinstance(params.text_background_color, bool):
            return "#000000" if params.text_background_color else None
        return params.text_background_color

    def create_text_clip(subtitle_item):
        params.font_size = int(params.font_size)
        params.stroke_width = int(params.stroke_width)
        phrase = subtitle_item[1]
        max_width = video_width * 0.9
        wrapped_txt, txt_height = wrap_text(
            phrase, max_width=max_width, font=font_path, fontsize=params.font_size
        )
        interline = int(params.font_size * 0.25)
        line_count = wrapped_txt.count("\n") + 1
        vertical_padding = int(params.font_size * 0.35)
        # MoviePy는 `method=label`에서 텍스트 박스 높이를 자동으로 줄이는데, 여러 줄 자막,
        # 테두리, 배경색이 있으면 마지막 줄의 아래 절반이 잘리기 쉽다. 여기서는
        # 행 간격과 추가 상하 여백까지 함께 계산해 더 보수적인 높이를 명시적으로 전달하여, 자막
        # 배경 박스와 글자 자체가 모두 온전히 렌더링되도록 보장한다.
        size = (
            int(max_width),
            int(txt_height + vertical_padding + (interline * line_count)),
        )

        _clip = TextClip(
            text=wrapped_txt,
            font=font_path,
            font_size=params.font_size,
            color=params.text_fore_color,
            bg_color=resolve_subtitle_background_color(),
            stroke_color=params.stroke_color,
            stroke_width=params.stroke_width,
            interline=interline,
            size=size,
            text_align="center",
        )
        duration = subtitle_item[0][1] - subtitle_item[0][0]
        _clip = _clip.with_start(subtitle_item[0][0])
        _clip = _clip.with_end(subtitle_item[0][1])
        _clip = _clip.with_duration(duration)
        if params.subtitle_position == "bottom":
            _clip = _clip.with_position(("center", video_height * 0.95 - _clip.h))
        elif params.subtitle_position == "top":
            _clip = _clip.with_position(("center", video_height * 0.05))
        elif params.subtitle_position == "custom":
            # Ensure the subtitle is fully within the screen bounds
            margin = 10  # Additional margin, in pixels
            max_y = video_height - _clip.h - margin
            min_y = margin
            custom_y = (video_height - _clip.h) * (params.custom_position / 100)
            custom_y = max(
                min_y, min(custom_y, max_y)
            )  # Constrain the y value within the valid range
            _clip = _clip.with_position(("center", custom_y))
        else:  # center
            _clip = _clip.with_position(("center", "center"))
        return _clip

    video_clip = _open_video_clip_quietly(video_path)
    audio_clip = AudioFileClip(audio_path).with_effects(
        [afx.MultiplyVolume(params.voice_volume)]
    )

    def make_textclip(text):
        return TextClip(
            text=text,
            font=font_path,
            font_size=params.font_size,
        )

    if subtitle_path and os.path.exists(subtitle_path):
        sub = SubtitlesClip(
            subtitles=subtitle_path, encoding="utf-8", make_textclip=make_textclip
        )
        text_clips = []
        for item in sub.subtitles:
            clip = create_text_clip(subtitle_item=item)
            text_clips.append(clip)
        video_clip = CompositeVideoClip([video_clip, *text_clips])

    bgm_file = get_bgm_file(bgm_type=params.bgm_type, bgm_file=params.bgm_file)
    if bgm_file:
        try:
            bgm_clip = AudioFileClip(bgm_file).with_effects(
                [
                    afx.MultiplyVolume(params.bgm_volume),
                    afx.AudioFadeOut(3),
                    afx.AudioLoop(duration=video_clip.duration),
                ]
            )
            audio_clip = CompositeAudioClip([audio_clip, bgm_clip])
        except Exception as e:
            logger.error(f"failed to add bgm: {str(e)}")

    video_clip = video_clip.with_audio(audio_clip)
    # 입력 오디오의 샘플레이트를 명시적으로 그대로 사용하고, 가져올 수 없으면 MoviePy 기본값인 44100Hz로 폴백한다.
    # 이렇게 하면 서로 다른 실행 환경, 특히 Docker 환경에서 다시 리샘플링하며 생기는 음질 변동을 줄일 수 있다.
    output_audio_fps = int(getattr(audio_clip, "fps", 0) or 44100)
    video_clip.write_videofile(
        output_file,
        audio_codec=audio_codec,
        audio_fps=output_audio_fps,
        audio_bitrate=audio_bitrate,
        temp_audiofile_path=output_dir,
        threads=params.n_threads or 2,
        logger=None,
        fps=fps,
    )
    video_clip.close()
    del video_clip


def preprocess_video(materials: List[MaterialInfo], clip_duration=4):
    # WebUI는 일부 재생성 상황에서 빈 소재 목록을 전달할 수 있으므로, 여기서 곧바로 빈 결과를 반환하여 NoneType 예외가 발생하는 것을 방지한다.
    if not materials:
        return []

    # 전처리 검증을 통과한 소재만 반환하여, 저해상도 이미지가 이후 영상 합성 과정으로 계속 들어가는 것을 방지한다.
    valid_materials = []
    local_videos_dir = utils.storage_dir("local_videos", create=True)

    for material in materials:
        if not material.url:
            continue

        try:
            material_source_path = file_security.resolve_path_within_directory(
                local_videos_dir, material.url
            )
        except ValueError as exc:
            # local video_source의 소재 경로는 API 파라미터에서 오므로, 반드시 전용 소재 디렉터리로 제한해야 한다.
            # 사용자가 파일명을 전달하는 것을 허용하고 과거에 반환된 절대 경로도 호환하지만, 시스템의
            # 다른 디렉터리로 벗어나는 것은 허용하지 않아, 임의 파일 읽기나 MoviePy를 통한 로컬 민감 파일 탐지를 방지한다.
            logger.warning(
                f"skip unsafe local material: {material.url}, "
                f"local_videos_dir: {local_videos_dir}, error: {str(exc)}"
            )
            continue

        ext = utils.parse_extension(material_source_path)
        try:
            # 이미지 소재는 곧바로 이미지 방식으로 읽어, 먼저 VideoFileClip을 거치다 오판하여 불안정한 폴백 분기를 유발하는 것을 방지한다.
            if ext in const.FILE_TYPE_IMAGES:
                clip, material_source_path = _open_image_clip_with_fallback(
                    material_source_path
                )
            else:
                clip = _open_video_clip_quietly(material_source_path)
        except Exception:
            # 비표준 확장자이거나 탐지에 실패한 경우 이미지 모드로 폴백하여, 과거에 로컬 이미지 경로를 직접 전달하던 경우를 호환한다.
            try:
                clip, material_source_path = _open_image_clip_with_fallback(
                    material_source_path
                )
            except Exception as exc:
                logger.warning(
                    f"skip unreadable local material: {material.url}, error: {str(exc)}"
                )
                continue
        try:
            width = clip.size[0]
            height = clip.size[1]
            if width < 480 or height < 480:
                logger.warning(f"low resolution material: {width}x{height}, minimum 480x480 required")
                # 저해상도 소재를 감지하면 즉시 리소스를 닫고, 해당 소재를 이후 과정으로 반환하지 않는다.
                close_clip(clip)
                continue

            if ext in const.FILE_TYPE_IMAGES:
                logger.info(f"processing image: {material_source_path}")
                # 크기를 탐지하면서 소재를 이미 한 번 열었으므로, 여기서 먼저 탐지용 핸들을 해제한 뒤, 내보내기에 쓸 이미지 clip을 다시 생성한다.
                close_clip(clip)
                # Create an image clip and set its duration to 3 seconds
                clip = (
                    ImageClip(material_source_path)
                    .with_duration(clip_duration)
                    .with_position("center")
                )
                # Apply a zoom effect using the resize method.
                # A lambda function is used to make the zoom effect dynamic over time.
                # The zoom effect starts from the original size and gradually scales up to 120%.
                # t represents the current time, and clip.duration is the total duration of the clip (3 seconds).
                # Note: 1 represents 100% size, so 1.2 represents 120% size.
                zoom_clip = clip.resized(
                    lambda t: 1 + (clip_duration * 0.03) * (t / clip.duration)
                )

                # Optionally, create a composite video clip containing the zoomed clip.
                # This is useful when you want to add other elements to the video.
                final_clip = CompositeVideoClip([zoom_clip])

                # Output the video to a file.
                video_file = f"{material_source_path}.mp4"
                final_clip.write_videofile(video_file, fps=30, logger=None)
                close_clip(clip)
                close_clip(final_clip)
                material.url = video_file
                logger.success(f"image processed: {video_file}")
            else:
                # 일반 비디오 소재는 검증을 위해 크기만 읽으면 되며, 검증이 끝나면 즉시 핸들을 해제하면 된다.
                close_clip(clip)
        except Exception:
            close_clip(clip)
            raise

        valid_materials.append(material)

    return valid_materials
