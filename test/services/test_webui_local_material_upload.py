import ast
import io
import os
import tempfile
from pathlib import Path
from uuid import uuid4
from unittest.mock import patch

from loguru import logger
from PIL import Image

from app.models.schema import MaterialInfo, VideoParams
from app.services import material_upload as material_upload_service
from app.utils import utils


WEBUI_MAIN = Path(__file__).parents[2] / "webui" / "Main.py"


class _StoppedUpload(Exception):
    pass


class _FakeStreamlit:
    def __init__(self):
        self.session_state = {}
        self.errors = []

    def error(self, message):
        self.errors.append(message)

    def stop(self):
        raise _StoppedUpload()


def _upload(name: str, content: bytes) -> io.BytesIO:
    uploaded = io.BytesIO(content)
    uploaded.name = name
    return uploaded


def _image_bytes() -> bytes:
    output = io.BytesIO()
    Image.new("RGB", (2, 2), "red").save(output, format="PNG")
    return output.getvalue()


def _run_webui_upload_block(files, temp_dir):
    """Execute the actual generation handler's local-material branch headlessly."""
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
        and node.test.id == "uploaded_files"
    )
    helpers = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_build_uploaded_file_path", "_save_uploaded_local_materials"}
    ]
    body = ast.fix_missing_locations(
        ast.Module(body=[*helpers, *upload_branch.body], type_ignores=[])
    )
    st = _FakeStreamlit()
    params = VideoParams(video_subject="Local material test", video_source="local")
    namespace = {
        "os": os,
        "uuid4": uuid4,
        "logger": logger,
        "utils": utils,
        "material_upload_service": material_upload_service,
        "MaterialInfo": MaterialInfo,
        "LOCAL_MATERIAL_EXTENSIONS": {".mp4", ".png"},
        "uploaded_files": files,
        "params": params,
        "st": st,
        "task_id": "task-1",
        "_remove_active_generation_task": lambda task_id: None,
        "tr": lambda value: value,
    }
    with patch.object(utils, "storage_dir", return_value=temp_dir):
        try:
            exec(compile(body, str(WEBUI_MAIN), "exec"), namespace)
        except _StoppedUpload:
            pass
    return params, st


def test_webui_rejects_invalid_image_before_starting_task():
    with tempfile.TemporaryDirectory() as temp_dir:
        params, st = _run_webui_upload_block(
            [_upload("fake.png", b"not an image")], temp_dir
        )

        assert st.errors
        assert not params.video_materials
        assert list(Path(temp_dir).iterdir()) == []


def test_webui_rolls_back_earlier_files_when_later_upload_is_invalid():
    with tempfile.TemporaryDirectory() as temp_dir:
        params, st = _run_webui_upload_block(
            [_upload("valid.png", _image_bytes()), _upload("invalid.png", b"bad")],
            temp_dir,
        )

        assert st.errors
        assert not params.video_materials
        assert list(Path(temp_dir).iterdir()) == []


def test_webui_enforces_image_size_limit():
    with tempfile.TemporaryDirectory() as temp_dir:
        with patch.object(
            material_upload_service, "MAX_IMAGE_MATERIAL_UPLOAD_BYTES", 4
        ):
            params, st = _run_webui_upload_block(
                [_upload("too-large.png", _image_bytes())], temp_dir
            )

        assert st.errors
        assert not params.video_materials
        assert list(Path(temp_dir).iterdir()) == []


def test_webui_persists_valid_image_and_session_materials():
    image_data = _image_bytes()
    with tempfile.TemporaryDirectory() as temp_dir:
        params, st = _run_webui_upload_block(
            [_upload("valid.png", image_data)], temp_dir
        )

        assert st.errors == []
        assert len(params.video_materials) == 1
        saved_path = Path(params.video_materials[0].url)
        assert saved_path.parent == Path(temp_dir)
        assert saved_path.read_bytes() == image_data
        assert st.session_state["local_video_materials"][0]["url"] == str(saved_path)
