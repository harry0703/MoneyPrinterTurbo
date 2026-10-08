import shutil
import subprocess

import pytest
from app.services import bgm, material_upload
from app.utils import utils


@pytest.fixture
def standalone_media(tmp_path):
    ffmpeg = utils.get_ffmpeg_binary()
    audio = tmp_path / "standalone.wav"
    video = tmp_path / "standalone.mp4"
    for path, options in [
        (audio, ["-f", "lavfi", "-i", "sine=frequency=440:duration=0.1"]),
        (video, ["-f", "lavfi", "-i", "color=c=red:s=32x32:r=10", "-t", "0.2", "-c:v", "libx264"]),
    ]:
        subprocess.run([ffmpeg, "-nostdin", "-v", "error", *options, "-y", str(path)], check=True, capture_output=True)
    return audio, video


@pytest.mark.parametrize("kind", ["audio", "video"])
def test_upload_rejects_concat_reference_disguised_as_media(standalone_media, kind):
    audio, video = standalone_media
    target = audio if kind == "audio" else video
    disguised = target.with_name("disguised" + target.suffix)
    disguised.write_text("ffconcat version 1.0\nfile '" + target.name + "'\n")
    validate = bgm.validate_audio_file if kind == "audio" else material_upload._validate_video
    error = bgm.BgmUploadError if kind == "audio" else material_upload.MaterialUploadError
    with pytest.raises(error):
        validate(str(disguised))


def test_standalone_uploads_still_decode_and_use_content_detection(standalone_media):
    audio, video = standalone_media
    bgm.validate_audio_file(str(audio))
    material_upload._validate_video(str(video))
    # TTS/media validators have historically detected actual containers rather
    # than forcing a demuxer solely from the filename extension.
    renamed_audio = audio.with_suffix(".mp3")
    renamed_video = video.with_suffix(".mov")
    shutil.copyfile(audio, renamed_audio)
    shutil.copyfile(video, renamed_video)
    bgm.validate_audio_file(str(renamed_audio))
    material_upload._validate_video(str(renamed_video))
