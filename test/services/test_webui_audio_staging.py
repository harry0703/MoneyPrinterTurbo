import ast
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch


class _StopGeneration(Exception):
    pass


class _PartialWrite:
    def __init__(self, file):
        self.file = file

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.file.close()

    def write(self, data):
        self.file.write(data[:4])
        raise OSError("no space left on device")


class TestWebuiAudioStaging(unittest.TestCase):
    def execute_audio_branch(self, kind, directory):
        tree = ast.parse((Path(__file__).parents[2] / "webui/Main.py").read_text(encoding="utf-8"))
        function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_render_generation_controls")
        branch = next(n for n in ast.walk(function) if isinstance(n, ast.If) and isinstance(n.test, ast.Name)
                      and n.test.id == kind)
        helpers = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_stage_task_audio"]
        target = Path(directory) / "audio.mp3"
        removed = Mock()
        preview = {"audio_bytes": b"complete narration", "duration": 1.0}
        st = SimpleNamespace(stop=Mock(side_effect=_StopGeneration), error=Mock())
        namespace = {
            "os": os, "tempfile": tempfile, "uploaded_audio_file": SimpleNamespace(name="voice.mp3", getbuffer=lambda: b"complete narration"),
            "reusable_voice_preview": preview, "task_id": "test-task", "params": SimpleNamespace(),
            "utils": SimpleNamespace(task_dir=lambda _id: directory),
            "_build_uploaded_file_path": lambda *_args: str(target), "CUSTOM_AUDIO_EXTENSIONS": (".mp3",),
            "bgm_service": SimpleNamespace(validate_bgm_upload=Mock(), BgmUploadError=type("UploadError", (Exception,), {}), BgmServiceError=type("ServiceError", (Exception,), {})),
            "_remove_active_generation_task": removed, "st": st, "tr": lambda value: value, "logger": Mock(),
        }
        original_open = open
        original_fdopen = os.fdopen
        namespace["open"] = lambda *args, **kwargs: _PartialWrite(original_open(*args, **kwargs))
        module = ast.fix_missing_locations(ast.Module(body=helpers + [branch], type_ignores=[]))
        with patch.object(os, "fdopen", side_effect=lambda *args, **kwargs: _PartialWrite(original_fdopen(*args, **kwargs))):
            with self.assertRaises(_StopGeneration):
                exec(compile(module, "webui-audio-branch", "exec"), namespace)
        removed.assert_called_once_with("test-task")
        st.error.assert_called_once()
        self.assertEqual(list(Path(directory).iterdir()), [])
        if kind == "reusable_voice_preview":
            self.assertEqual(preview["audio_bytes"], b"complete narration")

    def test_uploaded_narration_disk_failure_cleans_file_and_active_task(self):
        with tempfile.TemporaryDirectory() as directory:
            self.execute_audio_branch("uploaded_audio_file", directory)

    def test_reusable_preview_disk_failure_retains_cache_and_clears_active_task(self):
        with tempfile.TemporaryDirectory() as directory:
            self.execute_audio_branch("reusable_voice_preview", directory)

    def load_stage_helper(self):
        tree = ast.parse((Path(__file__).parents[2] / "webui/Main.py").read_text(encoding="utf-8"))
        helper = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_stage_task_audio")
        namespace = {"os": os, "tempfile": tempfile, "logger": Mock()}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[helper], type_ignores=[])), "audio-helper", "exec"), namespace)
        return namespace["_stage_task_audio"]

    def test_success_publishes_complete_audio_and_no_staging_files(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "audio.mp3"
            self.load_stage_helper()(str(target), b"complete narration")
            self.assertEqual(target.read_bytes(), b"complete narration")
            self.assertEqual(list(Path(directory).iterdir()), [target])

    def test_publish_failure_preserves_existing_audio_and_cleans_staging(self):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "audio.mp3"
            target.write_bytes(b"existing narration")
            with patch.object(os, "replace", side_effect=OSError("destination locked")):
                with self.assertRaisesRegex(OSError, "destination locked"):
                    self.load_stage_helper()(str(target), b"complete narration")
            self.assertEqual(target.read_bytes(), b"existing narration")
            self.assertEqual(list(Path(directory).iterdir()), [target])
