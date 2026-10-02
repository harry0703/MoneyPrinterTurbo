from types import SimpleNamespace
from unittest.mock import patch
from app.controllers.v1 import video as controller

def test_bgm_picker_survives_file_removed_during_listing():
    def size(filename):
        if filename == "/bgm/deleted.mp3":
            raise FileNotFoundError(filename)
        return 42
    with (patch.object(controller.bgm_service, "list_bgm_files", return_value=["/bgm/deleted.mp3", "/bgm/music.mp3"]),
          patch.object(controller.os.path, "getsize", side_effect=size)):
        result = controller.get_bgm_list(SimpleNamespace(headers={}))
    assert result["data"]["files"] == [{"name": "music.mp3", "size": 42, "file": "music.mp3"}]
