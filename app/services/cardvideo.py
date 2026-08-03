"""
카드 대본을 영상 파일로 만든다.

카드마다 나레이션을 따로 합성한다. 통째로 한 번 읽히고 나서 카드 경계를 추정하면
글자 수 비율로 나누는 수밖에 없는데, 문장마다 읽는 속도가 달라 뒤로 갈수록 화면과
소리가 밀린다. 카드별로 만들면 그 카드의 실제 길이가 그대로 노출 시간이 된다.
"""

import os
from contextlib import ExitStack
from dataclasses import dataclass

from loguru import logger

import numpy as np
from moviepy import AudioFileClip

from app.services import bgm as bgm_service
from app.services import cardnews, llm, task_artifacts, video as video_service, voice
from app.services.cardscript import CardScript
from app.utils import file_security, utils

SILENCE_FPS = 44100

MAX_NARRATION_ATTEMPTS = 2
# 나레이션이 없는 카드도 잠깐은 보여 준다. 글이 있는데 지나쳐 버리면 안 된다.
FALLBACK_CARD_SECONDS = 2.5


@dataclass(frozen=True)
class CardVideoResult:
    video_path: str
    duration: float
    card_count: int


def _silence_clip(seconds: float):
    """
    무음 조각. 화면만 있고 소리가 없는 카드의 자리를 메운다.

    ffmpeg 를 부르지 않고 메모리에서 만든다. 타임라인을 맞추는 일이 외부 도구의
    성공 여부에 걸리면, 그 도구가 실패했을 때 어긋난 영상이 나온다.
    """
    from moviepy import AudioArrayClip

    frames = max(1, int(SILENCE_FPS * max(seconds, 0.1)))
    return AudioArrayClip(np.zeros((frames, 2)), fps=SILENCE_FPS)


def _audio_segment(clips: ExitStack, path: str | None, seconds: float):
    """
    카드 하나가 차지할 오디오를 정확히 ``seconds`` 만큼 만든다.

    영상 쪽은 카드 길이를 상·하한으로 조인다. 오디오가 원래 길이를 그대로 쓰면 그
    차이만큼 뒤로 밀리고, 카드가 넘어갈수록 벌어진다. 짧으면 뒤에 무음을 붙이고
    길면 잘라, 두 타임라인의 길이를 같게 만든다.
    """
    from moviepy import concatenate_audioclips

    if path is None:
        return clips.enter_context(_silence_clip(seconds))

    source = clips.enter_context(AudioFileClip(path))
    if source.duration > seconds:
        return clips.enter_context(source.subclipped(0, seconds))
    if source.duration < seconds:
        tail = clips.enter_context(_silence_clip(seconds - source.duration))
        return clips.enter_context(concatenate_audioclips([source, tail]))
    return source


def _narrate(text: str, target_path: str, params) -> float:
    """
    카드 하나의 나레이션을 만들고 길이를 돌려준다. 실패하면 ``0``.

    한 장이 실패했다고 영상 전체를 버리지 않는다. 그 카드는 소리 없이 지나가고
    나머지는 그대로 나온다.
    """
    for attempt in range(MAX_NARRATION_ATTEMPTS):
        # 같은 task 를 다시 돌리면 지난 실행의 파일이 그 자리에 남아 있다. 지우지
        # 않으면, 합성이 조용히 실패했을 때 예전 소리를 새 카드에 붙이게 된다.
        try:
            os.remove(target_path)
        except FileNotFoundError:
            pass
        except OSError as exc:
            # 못 지웠다면 이 자리에 옛 파일이 그대로 있다는 뜻이다. 그 상태로
            # 합성에 들어가면 실패해도 옛 소리가 성공처럼 통과한다.
            logger.warning(f"could not clear a stale narration: {type(exc).__name__}")
            return 0.0
        try:
            # 음량은 아래에서 클립에 한 번만 건다. 여기서도 걸면 제공자에 따라 두 번
            # 곱해져, 0.2 를 넣은 사람이 0.04 를 듣게 된다.
            sub_maker = voice.tts(
                text=text,
                voice_name=params.voice_name,
                voice_rate=params.voice_rate,
                voice_file=target_path,
                voice_volume=1.0,
            )
            if sub_maker and os.path.exists(target_path):
                return voice.get_audio_duration(target_path)
        except Exception as exc:
            # 제공자는 실패를 반환값이 아니라 예외로 알리기도 한다. 그대로 두면
            # 재시도도 무음 처리도 건너뛰고 영상 전체가 죽는다.
            logger.warning(
                f"card narration raised: {type(exc).__name__}: "
                f"{llm.sanitize_error_message(exc)}"
            )
        logger.warning(f"card narration failed, retrying... {attempt + 1}")
    return 0.0


def render_card_news(
    task_id: str, script: CardScript, params
) -> CardVideoResult | None:
    """
    카드 대본으로 영상 하나를 만든다. 만들지 못하면 ``None``.

    출력 위치는 받지 않고 task 에서 유도한다. 경로를 인자로 받으면 그 값을 검사할
    책임이 생기고, 여기서 만드는 파일은 지우고 덮어쓰는 것들이라 잘못된 위치를
    받으면 남의 파일을 건드린다. task 이름도 밖에서 오는 값이므로 작업 디렉터리
    안에 있는지 공용 검사기로 확인한다.

    ``params`` 는 기존 영상 파라미터를 그대로 쓴다. 음성, 배속, BGM 설정이 이미
    거기 있고, 카드뉴스라고 다른 값을 쓸 이유가 없다.
    """
    from moviepy import CompositeAudioClip, afx, concatenate_audioclips

    try:
        output_dir = file_security.resolve_path_within_directory(
            utils.task_dir(), str(task_id), require_file=False
        )
    except (ValueError, OSError) as exc:
        logger.error(f"refusing to render outside the task directory: {exc}")
        return None
    os.makedirs(output_dir, exist_ok=True)
    durations: list[float] = []
    # 경로가 ``None`` 이면 그 자리는 무음이다.
    narration_paths: list[str | None] = []

    for index, narration in enumerate(script.narrations, start=1):
        target = os.path.join(output_dir, f"card-{index:02d}.mp3")
        seconds = _narrate(narration, target, params) if narration.strip() else 0.0
        if seconds > 0:
            narration_paths.append(target)
            durations.append(cardnews.card_seconds(seconds))
            continue

        # 소리 없이 지나가는 카드. 오디오 쪽에도 같은 길이의 자리를 만들어야 한다.
        # 빼 버리면 그 뒤 카드의 소리가 화면보다 먼저 나오고, 어긋남이 끝까지 남는다.
        # 파일로 만들지 않고 메모리에서 만드는 이유는, 이 자리를 채우는 일이
        # 외부 도구의 성공 여부에 걸려서는 안 되기 때문이다.
        narration_paths.append(None)
        durations.append(cardnews.card_seconds(FALLBACK_CARD_SECONDS))

    if not durations:
        logger.error(f"card news has nothing to render: {task_id}")
        return None

    video_path = os.path.join(output_dir, "cardnews.mp4")
    # 원본 리더까지 확실히 닫는다. 합쳐진 클립만 닫으면 자식 리더가 남아 ffmpeg
    # 프로세스와 파일 잠금이 쌓인다.
    with ExitStack() as clips:
        video_clip = clips.enter_context(
            cardnews.build_card_news_clip(script.cards, durations)
        )
        audio_clip = None
        if narration_paths:
            narration_clips = [
                _audio_segment(clips, path, seconds)
                for path, seconds in zip(narration_paths, durations)
            ]
            audio_clip = clips.enter_context(
                concatenate_audioclips(narration_clips).with_effects(
                    [afx.MultiplyVolume(params.voice_volume)]
                )
            )

        bgm_clip = None
        bgm_file = video_service.get_bgm_file(
            bgm_type=params.bgm_type, bgm_file=params.bgm_file
        )
        if bgm_file and bgm_service.should_use_bgm(params.bgm_type, params.bgm_volume):
            bgm_source = clips.enter_context(AudioFileClip(bgm_file))
            bgm_clip = clips.enter_context(
                bgm_source.with_effects(
                    [
                        afx.MultiplyVolume(params.bgm_volume),
                        afx.AudioLoop(duration=video_clip.duration),
                        afx.AudioFadeOut(2),
                    ]
                )
            )

        tracks = [track for track in (audio_clip, bgm_clip) if track is not None]
        if tracks:
            mixed = clips.enter_context(CompositeAudioClip(tracks))
            video_clip = clips.enter_context(video_clip.with_audio(mixed))

        video_clip.write_videofile(
            video_path,
            fps=24,
            codec="libx264",
            audio_codec="aac",
            threads=params.n_threads or 2,
            temp_audiofile_path=output_dir,
            logger=None,
        )

    duration = sum(durations)
    # 요청한 카드 수와 실제로 그려진 수, 요청한 나레이션 길이와 실제 노출 시간이
    # 다를 수 있다. 기록에는 실제 값이 남아야 한다.
    task_artifacts.patch_script_data(
        task_id,
        card_news={
            "cards": len(script.cards),
            "durations": [round(value, 3) for value in durations],
            "silent_cards": [
                index for index, path in enumerate(narration_paths, start=1) if not path
            ],
            "video": video_path,
        },
    )
    logger.success(
        f"card news rendered: {video_path}, {len(script.cards)} cards, {duration:.1f}s"
    )
    return CardVideoResult(
        video_path=video_path,
        duration=duration,
        card_count=len(script.cards),
    )
