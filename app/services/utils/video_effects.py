import numpy as np
from moviepy import Clip, ColorClip, CompositeVideoClip, vfx
from PIL import Image


# FadeIn
def fadein_transition(clip: Clip, t: float) -> Clip:
    return clip.with_effects([vfx.FadeIn(t)])


# FadeOut
def fadeout_transition(clip: Clip, t: float) -> Clip:
    return clip.with_effects([vfx.FadeOut(t)])


# SlideIn
def slidein_transition(clip: Clip, t: float, side: str) -> Clip:
    width, height = clip.size

    # MoviePy 내장 SlideIn 은 현재 처리 체인에서 전체 화면 소재에 불안정해서,
    # '논리적으로는 전환이 적용됐지만 화면상 변화가 거의 보이지 않는' 상황이 생긴다.
    # 여기서는 명시적인 검은 배경 + 이동 애니메이션으로 바꿔, 전환 효과가 눈에 보이고
    # 동작을 통제할 수 있게 한다.
    def position(current_time: float):
        progress = min(max(current_time / max(t, 0.001), 0), 1)

        if side == "left":
            return (-width + width * progress, 0)
        if side == "right":
            return (width - width * progress, 0)
        if side == "top":
            return (0, -height + height * progress)
        if side == "bottom":
            return (0, height - height * progress)
        return (0, 0)

    background = ColorClip(size=(width, height), color=(0, 0, 0)).with_duration(
        clip.duration
    )
    moving_clip = clip.with_position(position)
    return CompositeVideoClip([background, moving_clip], size=(width, height)).with_duration(
        clip.duration
    )


# SlideOut
def slideout_transition(clip: Clip, t: float, side: str) -> Clip:
    width, height = clip.size
    transition_start = max(clip.duration - t, 0)

    # SlideOut 도 마찬가지로 명시적 이동으로 바꿔, 클립 끝에서 화면 밖으로 안정적으로 빠져나가게 한다.
    def position(current_time: float):
        if current_time <= transition_start:
            return (0, 0)

        progress = min(
            max((current_time - transition_start) / max(t, 0.001), 0), 1
        )

        if side == "left":
            return (-width * progress, 0)
        if side == "right":
            return (width * progress, 0)
        if side == "top":
            return (0, -height * progress)
        if side == "bottom":
            return (0, height * progress)
        return (0, 0)

    background = ColorClip(size=(width, height), color=(0, 0, 0)).with_duration(
        clip.duration
    )
    moving_clip = clip.with_position(position)
    return CompositeVideoClip([background, moving_clip], size=(width, height)).with_duration(
        clip.duration
    )


# 원래 설계의 20% 확대 폭을 유지해, 3초 내외의 짧은 클립에서도 Ken Burns 움직임이
# 뚜렷하게 보이도록 한다. 확대의 안정성은 아래의 서브픽셀 중심 샘플링이 보장하며,
# 효과 폭을 줄여서 원본 영상 인코딩의 깜빡임을 가리지 않는다.
_ZOOM_MAX_SCALE = 1.2


def _zoom_frame(frame: np.ndarray, scale_factor: float) -> np.ndarray:
    """서브픽셀 중심 크롭으로 검은 여백 없이 안정적인 확대 효과를 구현한다.

    크롭 폭과 높이를 먼저 정수로 바꾸면 안 된다. 확대 비율이 연속으로 변할 때 정수
    경계가 서로 다른 보폭으로 튀고, 홀짝 크기가 바뀌는 순간 반픽셀 샘플링 위상이
    달라져 결국 화면 떨림으로 나타난다. Pillow 의 EXTENT 변환은 부동소수점 경계를
    그대로 받아 고정된 출력 캔버스 위에서 서브픽셀 샘플링을 끝낼 수 있다. 좌우와
    상하 경계가 항상 같은 부동소수점 중심을 기준으로 대칭이므로, 영상 전체를 계속
    천천히 확대하는 경우에 적합하다.
    """
    if scale_factor <= 0:
        raise ValueError("scale_factor must be greater than zero")

    # 1 배 확대는 원본 프레임을 그대로 반환한다. 의미 없는 리샘플링으로 첫 프레임이 살짝 흐려지는 것을 막는다.
    if abs(scale_factor - 1.0) < 1e-9:
        return frame

    height, width = frame.shape[:2]
    crop_width = width / scale_factor
    crop_height = height / scale_factor
    left = (width - crop_width) / 2
    top = (height - crop_height) / 2
    right = left + crop_width
    bottom = top + crop_height

    image = Image.fromarray(frame)
    transformed = image.transform(
        (width, height),
        Image.Transform.EXTENT,
        (left, top, right, bottom),
        # 영상의 연속 확대에서는 인접 프레임 간 일관성이 더 중요하다. BICUBIC/LANCZOS 는
        # 단일 프레임이 더 선명하지만, 고주파 텍스처가 샘플링 격자를 가로지를 때 링잉과
        # 밝기 깜빡임이 생기기 쉽다. BILINEAR 는 더 부드러워서 선명도를 약간 포기하는
        # 대신 움직임이 더 안정적으로 보인다.
        resample=Image.Resampling.BILINEAR,
    )
    return np.asarray(transformed)


def zoomin_transition(clip: Clip, t: float) -> Clip:
    """클립 전체에 걸쳐 원본 화면에서 1.2 배까지 부드럽게 확대한다."""
    # t 는 다른 전환 함수와 호출 시그니처를 맞추려고 일단 남겨 둔다. 확대는 클립 전체를
    # 덮어야 하며, 그러지 않으면 짧은 확대가 끝난 뒤 화면이 갑자기 멈춰 정적이거나
    # 움직임이 적은 소재에는 어울리지 않는다.
    _ = t
    duration = max(clip.duration, 0.001)

    def scale_effect(get_frame, current_time: float):
        progress = min(max(current_time / duration, 0), 1)
        scale_factor = 1 + (_ZOOM_MAX_SCALE - 1) * progress
        return _zoom_frame(get_frame(current_time), scale_factor)

    return clip.transform(scale_effect)


def zoomout_transition(clip: Clip, t: float) -> Clip:
    """클립 전체에 걸쳐 1.2 배에서 원본 화면까지 부드럽게 축소한다."""
    # zoomin_transition 과 마찬가지로, t 는 통일된 전환 호출 인터페이스 호환용으로만 쓴다.
    _ = t
    duration = max(clip.duration, 0.001)

    def scale_effect(get_frame, current_time: float):
        progress = min(max(current_time / duration, 0), 1)
        scale_factor = _ZOOM_MAX_SCALE - (_ZOOM_MAX_SCALE - 1) * progress
        return _zoom_frame(get_frame(current_time), scale_factor)

    return clip.transform(scale_effect)
