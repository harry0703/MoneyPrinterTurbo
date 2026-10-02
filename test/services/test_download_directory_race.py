from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
from unittest.mock import MagicMock, patch
from app.services import material

def test_parallel_first_downloads_share_new_directory(tmp_path):
    destination = tmp_path / "cache"
    barrier = threading.Barrier(2)
    real_makedirs = material.os.makedirs
    def makedirs(name, **kwargs):
        if str(name) == str(destination):
            barrier.wait(timeout=3)
        return real_makedirs(name, **kwargs)
    response = MagicMock()
    response.__enter__.return_value = response
    response.headers = {}
    response.iter_content.side_effect = lambda **kwargs: iter([b"video fixture"])
    def decode(name):
        assert Path(name).read_bytes() == b"video fixture"
        return MagicMock(duration=3.0, fps=30)
    with (patch.object(material.os, "makedirs", side_effect=makedirs),
          patch.object(material.requests, "get", return_value=response),
          patch.object(material, "VideoFileClip", side_effect=decode)):
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda n: material.save_video(f"https://example.test/{n}.mp4", str(destination)), [1, 2]))
    assert len(set(results)) == 2
    assert all(Path(path).read_bytes() == b"video fixture" for path in results)
    assert len(list(destination.iterdir())) == 2
