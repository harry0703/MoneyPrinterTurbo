"""验证儿童受众声明的配置、任务快照和真实 HTTP 表单编码，不连接外部平台。"""

from concurrent.futures import Future
from email.parser import BytesParser
from email.policy import default
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.config import config
from app.models.schema import VideoParams
from app.services import task
from app.services.state import MemoryState
from app.services.upload_post import UploadPostService


@pytest.fixture
def upload_config():
    """测试只使用虚构凭据，不能读取用户真实发布目标或发起真实上传。"""
    values = {
        "upload_post_enabled": True,
        "upload_post_api_key": "local-test-key",
        "upload_post_username": "local-test-user",
        "upload_post_platforms": ["youtube"],
    }
    with patch.object(config, "app", values):
        yield values


@pytest.mark.parametrize("configured", [False, True])
@pytest.mark.parametrize(
    "extra",
    [None, {}, {"selfDeclaredMadeForKids": False}, {"selfDeclaredMadeForKids": True}],
)
def test_audience_payload_and_snapshot_override(
    tmp_path, upload_config, configured, extra
):
    """显式任务快照优先于当前配置；没有元数据时也必须发送声明。"""
    upload_config["upload_post_youtube_made_for_kids"] = configured
    video = tmp_path / "video.mp4"
    video.write_bytes(b"test-media")
    with patch("app.services.upload_post.requests.post") as post:
        post.return_value.json.return_value = {"success": True}
        result = UploadPostService().upload_video(
            str(video), "test", youtube_extra=extra
        )
    assert result["success"] is True
    data = post.call_args.kwargs["data"]
    expected = (extra or {}).get("selfDeclaredMadeForKids", configured)
    assert [v for k, v in data if k == "selfDeclaredMadeForKids"] == [
        str(expected).lower()
    ]


@pytest.mark.parametrize("invalid", ["false", "true", "", 0, 1, None, [], {}])
def test_invalid_audience_never_uploads(tmp_path, upload_config, invalid):
    """非法配置不能被隐式转换成受众声明，也不能继续上传。"""
    upload_config["upload_post_youtube_made_for_kids"] = invalid
    video = tmp_path / "video.mp4"
    video.touch()
    with patch("app.services.upload_post.requests.post") as post:
        result = UploadPostService().upload_video(str(video), "test")
    assert result["success"] is False
    assert "boolean" in result["error"]
    post.assert_not_called()


def test_other_platforms_ignore_youtube_audience(tmp_path, upload_config):
    """非 YouTube 发布不读取或校验该设置，错误的受众配置也不能影响它们。"""
    upload_config["upload_post_youtube_made_for_kids"] = "invalid"
    video = tmp_path / "video.mp4"
    video.touch()
    with patch("app.services.upload_post.requests.post") as post:
        post.return_value.json.return_value = {"success": True}
        result = UploadPostService().upload_video(
            str(video),
            "test",
            platforms=["tiktok", "instagram"],
            youtube_extra={"selfDeclaredMadeForKids": "invalid"},
        )
    assert result["success"] is True
    assert "selfDeclaredMadeForKids" not in dict(post.call_args.kwargs["data"])


@pytest.mark.parametrize("selected", [False, True])
def test_queued_audience_survives_config_change(upload_config, selected):
    """延迟执行真实工作函数，验证队列等待期间配置变化不会串到已提交任务。"""
    upload_config["upload_post_youtube_made_for_kids"] = selected
    state = MemoryState()
    state.update_task("audience-snapshot", state=task.const.TASK_STATE_COMPLETE)
    future = Future()
    with (
        patch.object(task.sm, "state", state),
        patch.object(task, "_cross_post_slots", MagicMock()),
        patch.object(
            task._cross_post_executor, "submit", return_value=future
        ) as submit,
        patch.object(task.llm, "generate_social_metadata", return_value={}),
        patch.object(
            task.upload_post, "cross_post_video", return_value={"success": True}
        ) as upload,
    ):
        assert (
            task._schedule_cross_post(
                "audience-snapshot",
                ["one.mp4", "two.mp4"],
                VideoParams(video_subject="test"),
                "test",
                ["youtube"],
                "private",
                UploadPostService().youtube_made_for_kids,
            )
            is None
        )
        upload_config["upload_post_youtube_made_for_kids"] = not selected
        fn, *args = submit.call_args.args
        fn(*args)
        future.set_result(None)
    assert upload.call_count == 2
    assert all(
        c.kwargs["youtube_extra"]["selfDeclaredMadeForKids"] is selected
        for c in upload.call_args_list
    )


@pytest.mark.parametrize("selected", [None, False, True])
def test_real_http_multipart_audience(tmp_path, upload_config, selected):
    """通过本机真实 HTTP 接收 multipart 请求，验证旧配置及 true/false 编码。"""
    received = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            body = self.rfile.read(int(self.headers["Content-Length"]))
            message = BytesParser(policy=default).parsebytes(
                f"Content-Type: {self.headers['Content-Type']}\r\n\r\n".encode() + body
            )
            received.append(
                {
                    part.get_param(
                        "name", header="content-disposition"
                    ): part.get_payload(decode=True)
                    for part in message.iter_parts()
                }
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"success": true, "request_id": "local-only"}')

        def log_message(self, *_args):
            # 本机接收器不打印请求头，测试输出无需包含认证信息。
            pass

    if selected is not None:
        upload_config["upload_post_youtube_made_for_kids"] = selected
    video = tmp_path / "video.mp4"
    video.write_bytes(b"multipart-test-media")
    server = ThreadingHTTPServer(("127.0.0.1", 0), Receiver)
    worker = Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        # 只访问环回地址，绕过开发机代理，避免把测试请求交给外部代理服务。
        with (
            requests.Session() as session,
            patch.object(
                UploadPostService, "API_BASE", f"http://127.0.0.1:{server.server_port}"
            ),
        ):
            session.trust_env = False
            with patch(
                "app.services.upload_post.requests.post", side_effect=session.post
            ):
                result = UploadPostService().upload_video(str(video), "test")
        assert result["success"] is True
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=5)
    assert received[0]["selfDeclaredMadeForKids"] == (b"true" if selected else b"false")
    assert received[0]["video"] == b"multipart-test-media"
