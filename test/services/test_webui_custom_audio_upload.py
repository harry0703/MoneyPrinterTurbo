import ast
import io
import os
import tempfile
import wave
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from loguru import logger

from app.models.schema import VideoParams
from app.services import bgm as bgm_service
from app.utils import utils


WEBUI_MAIN = Path(__file__).parents[2] / "webui" / "Main.py"


class _StoppedUpload(Exception):
    pass


class _FakeStreamlit:
    def __init__(self):
        self.errors = []

    def error(self, message):
        self.errors.append(message)

    def stop(self):
        raise _StoppedUpload()


def _upload(name: str, content: bytes) -> io.BytesIO:
    uploaded = io.BytesIO(content)
    uploaded.name = name
    return uploaded


def _wav_bytes() -> bytes:
    output = io.BytesIO()
    with wave.open(output, "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(16000)
        wav.writeframes(b"\x00\x00" * 1600)
    return output.getvalue()


def _run_webui_audio_block(uploaded_audio_file, task_dir, stage_dir):
    """Execute the real generation handler's custom-audio upload branch."""
    tree = ast.parse(WEBUI_MAIN.read_text(encoding="utf-8"))
    generation = next(
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "_render_generation_controls"
    )
    upload_branch = next(
        node for node in ast.walk(generation)
        if isinstance(node, ast.If)
        and isinstance(node.test, ast.Name)
        and node.test.id == "uploaded_audio_file"
    )
    helpers = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_build_uploaded_file_path", "_stage_task_audio"}
    ]
    body = ast.fix_missing_locations(
        ast.Module(body=[*helpers, *upload_branch.body], type_ignores=[])
    )
    st = _FakeStreamlit()
    params = VideoParams(video_subject="Custom audio test")
    namespace = {
        "os": os,
        "tempfile": tempfile,
        "uuid4": uuid4,
        "logger": logger,
        "utils": utils,
        "bgm_service": bgm_service,
        "CUSTOM_AUDIO_EXTENSIONS": {".wav", ".mp3"},
        "uploaded_audio_file": uploaded_audio_file,
        "params": params,
        "st": st,
        "task_id": "task-1",
        "_remove_active_generation_task": lambda task_id: None,
        "tr": lambda value: value,
    }
    with (
        patch.object(utils, "task_dir", return_value=task_dir),
        patch.object(bgm_service, "uploaded_bgm_dir", return_value=stage_dir),
    ):
        try:
            exec(compile(body, str(WEBUI_MAIN), "exec"), namespace)
        except _StoppedUpload:
            pass
    return params, st


def test_webui_rejects_corrupt_custom_audio_before_task_start():
    with tempfile.TemporaryDirectory() as temp_dir:
        task_dir = Path(temp_dir, "task")
        stage_dir = Path(temp_dir, "bgm")
        task_dir.mkdir()
        stage_dir.mkdir()
        params, st = _run_webui_audio_block(
            _upload("voice.wav", b"not a WAV file"), str(task_dir), str(stage_dir)
        )

        assert st.errors
        assert not params.custom_audio_file
        assert list(task_dir.iterdir()) == []
        assert list(stage_dir.iterdir()) == []


def test_webui_enforces_custom_audio_size_limit():
    with tempfile.TemporaryDirectory() as temp_dir:
        task_dir = Path(temp_dir, "task")
        stage_dir = Path(temp_dir, "bgm")
        task_dir.mkdir()
        stage_dir.mkdir()
        with patch.object(bgm_service, "MAX_BGM_UPLOAD_BYTES", 4):
            params, st = _run_webui_audio_block(
                _upload("voice.wav", _wav_bytes()), str(task_dir), str(stage_dir)
            )

        assert st.errors
        assert not params.custom_audio_file
        assert list(task_dir.iterdir()) == []
        assert list(stage_dir.iterdir()) == []


def test_webui_keeps_valid_voiceover_in_the_current_task_directory():
    audio_data = _wav_bytes()
    with tempfile.TemporaryDirectory() as temp_dir:
        task_dir = Path(temp_dir, "task")
        stage_dir = Path(temp_dir, "bgm")
        task_dir.mkdir()
        stage_dir.mkdir()
        params, st = _run_webui_audio_block(
            _upload("voice.wav", audio_data), str(task_dir), str(stage_dir)
        )

        assert st.errors == []
        saved_path = Path(params.custom_audio_file)
        assert saved_path.parent == task_dir.resolve()
        assert saved_path.read_bytes() == audio_data
        assert list(stage_dir.iterdir()) == []
