import numpy as np
import pytest
from moviepy import ColorClip, CompositeVideoClip, ImageClip
from app.services.utils import video_effects


@pytest.mark.parametrize('effect,time', [(video_effects.zoomin_transition, 1.99), (video_effects.zoomout_transition, 0)])
def test_transparent_subject_mask_moves_with_zoomed_color(effect, time):
    pixels = np.zeros((100, 100, 4), dtype=np.uint8)
    pixels[:, :, :3] = 255
    pixels[35:65, 35:65, 3] = 255
    source = ImageClip(pixels).with_duration(2)
    transformed = effect(source, 1)
    background = ColorClip((100, 100), color=(0, 0, 0)).with_duration(2)
    composed = CompositeVideoClip([background, transformed])
    try:
        frame = composed.get_frame(time)
        # A20% zoom moves the subject's left edge35->32: atx33 the
        # transformed subject should now be visible over the black canvas.
        assert frame[50, 33, 0] > 150
        assert frame[50, 20, 0] == 0
        assert frame[50, 50, 0] == 255
    finally:
        composed.close()
        background.close()
        transformed.close()
        source.close()


def test_opaque_video_zoom_keeps_dimensions_and_center():
    source = ImageClip(np.full((100, 100, 3), (220, 10, 30), dtype=np.uint8)).with_duration(2)
    transformed = video_effects.zoomin_transition(source, 1)
    try:
        assert transformed.get_frame(1).shape == (100, 100, 3)
        assert tuple(transformed.get_frame(1)[50, 50]) == (220, 10, 30)
    finally:
        transformed.close()
        source.close()
