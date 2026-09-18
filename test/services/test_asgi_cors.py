import unittest
from unittest.mock import Mock, patch

from fastapi import FastAPI, File, UploadFile
from fastapi.testclient import TestClient

from app import asgi


class TestASGICORS(unittest.TestCase):
    """验证浏览器跨域默认值和显式兼容配置，避免重新引入开放 CORS。"""

    @staticmethod
    def _create_client(allowed_origins: list[str]) -> TestClient:
        """构造只包含探针路由的应用，隔离业务任务和外部 API 调用。"""

        application = FastAPI()

        @application.get("/probe")
        def probe():
            return {"status": "ok"}

        asgi.configure_browser_access(application, allowed_origins)
        return TestClient(application)

    def test_origin_parser_trims_values_and_ignores_empty_items(self):
        """环境变量中的空格和尾随逗号不应破坏合法来源匹配。"""

        origins = asgi.parse_cors_allowed_origins(
            " https://a.example,https://b.example, ,"
        )

        self.assertEqual(
            origins,
            ["https://a.example", "https://b.example"],
        )
        self.assertEqual(asgi.parse_cors_allowed_origins(""), [])
        self.assertEqual(asgi.parse_cors_allowed_origins(None), [])

    def test_origin_parser_normalizes_every_item_to_origin_header_shape(self):
        """配置项必须折叠成 Origin 请求头的规范形式，否则白名单静默失效。"""

        origins = asgi.parse_cors_allowed_origins(
            "https://frontend.example/,"
            "HTTPS://Admin.Example,"
            "https://frontend.example/,"
            "localhost:3000,"
            "ftp://files.example,"
            "*"
        )

        # 尾斜杠、大小写差异和重复项都归一到同一个来源；缺少 scheme 的主机名、
        # 非 http/https 的 scheme 都不可能出现在 Origin 头里，因此被丢弃。
        self.assertEqual(
            origins,
            ["https://frontend.example", "https://admin.example", "*"],
        )

    def test_malformed_entry_is_dropped_without_losing_valid_origins(self):
        """畸形条目只能丢弃自身并留下告警，不得中断整份配置的解析。"""

        with patch.object(asgi, "logger") as mocked_logger:
            origins = asgi.parse_cors_allowed_origins(
                "https://valid.example,"
                "https://[::1,"
                "https://frontend.example:bad,"
                "https://frontend.example:99999,"
                "https://second.example"
            )

        # 畸形 IPv6 字面量和非法端口都不可能出现在 Origin 头里。它们的解析异常
        # 必须在这里收敛：本函数由模块导入期调用，异常冒出去等于整条 API 起不来。
        self.assertEqual(
            origins,
            ["https://valid.example", "https://second.example"],
        )
        self.assertEqual(mocked_logger.warning.call_count, 3)

    def test_explicit_default_port_is_folded_into_the_origin(self):
        """显式写出默认端口的写法必须折叠成浏览器实际发送的 Origin。"""

        origins = asgi.parse_cors_allowed_origins(
            "https://secure.example:443,"
            "http://plain.example:80,"
            "https://padded.example:0443,"
            "https://custom.example:8443,"
            "https://[::1]:3000"
        )

        # :443 / :0443 / :80 都等于协议的默认端口，浏览器序列化 Origin 时会省略；
        # 非默认端口必须保留，IPv6 字面量则要连方括号一起保留。
        self.assertEqual(
            origins,
            [
                "https://secure.example",
                "http://plain.example",
                "https://padded.example",
                "https://custom.example:8443",
                "https://[::1]:3000",
            ],
        )

    def test_address_bar_style_origin_admits_the_trusted_frontend(self):
        """从地址栏复制的带尾斜杠写法必须与规范写法得到同一个前端访问结果。"""

        trusted_origin = "https://frontend.example"
        client = self._create_client(
            asgi.parse_cors_allowed_origins("https://frontend.example/")
        )

        response = client.get("/probe", headers={"Origin": trusted_origin})
        preflight = client.options(
            "/probe",
            headers={
                "Origin": trusted_origin,
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"], trusted_origin
        )
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(
            preflight.headers["access-control-allow-origin"], trusted_origin
        )

    def test_default_port_configuration_admits_the_trusted_frontend(self):
        """配置里写了默认端口时，浏览器不带端口的 Origin 仍必须被放行。"""

        trusted_origin = "https://frontend.example"
        client = self._create_client(
            asgi.parse_cors_allowed_origins("https://frontend.example:443")
        )

        response = client.get("/probe", headers={"Origin": trusted_origin})
        preflight = client.options(
            "/probe",
            headers={
                "Origin": trusted_origin,
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.headers["access-control-allow-origin"], trusted_origin
        )
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(
            preflight.headers["access-control-allow-origin"], trusted_origin
        )

    def test_empty_configuration_keeps_browser_same_origin_policy(self):
        """未配置白名单时，第三方网页不能读取响应或通过预检。"""

        client = self._create_client([])
        origin = "https://evil.attacker.example"

        response = client.get("/probe", headers={"Origin": origin})
        preflight = client.options(
            "/probe",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.status_code, 403)
        self.assertNotIn("access-control-allow-origin", response.headers)
        self.assertNotIn("access-control-allow-credentials", response.headers)
        self.assertEqual(preflight.status_code, 403)
        self.assertNotIn("access-control-allow-origin", preflight.headers)

    def test_same_origin_and_server_clients_remain_compatible(self):
        """同源浏览器和不发送 Origin 的服务端客户端必须继续正常访问。"""

        client = self._create_client([])

        same_origin = client.get(
            "/probe",
            headers={"Origin": "http://testserver"},
        )
        server_client = client.get("/probe")

        self.assertEqual(same_origin.status_code, 200)
        self.assertEqual(server_client.status_code, 200)

    def test_explicit_origin_allows_only_the_trusted_frontend(self):
        """独立网页前端显式配置后可以访问，其他来源仍必须被拒绝。"""

        trusted_origin = "https://frontend.example"
        untrusted_origin = "https://evil.attacker.example"
        client = self._create_client([trusted_origin])

        trusted = client.get("/probe", headers={"Origin": trusted_origin})
        untrusted = client.get("/probe", headers={"Origin": untrusted_origin})
        trusted_preflight = client.options(
            "/probe",
            headers={
                "Origin": trusted_origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        untrusted_preflight = client.options(
            "/probe",
            headers={
                "Origin": untrusted_origin,
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(trusted.headers["access-control-allow-origin"], trusted_origin)
        self.assertEqual(trusted.headers["access-control-allow-credentials"], "true")
        self.assertNotIn("access-control-allow-origin", untrusted.headers)
        self.assertEqual(trusted_preflight.status_code, 200)
        self.assertEqual(untrusted_preflight.status_code, 400)

    def test_trusted_origin_can_request_private_network_access(self):
        """精确白名单应支持远程网页访问本机或局域网 API 的额外预检。"""

        trusted_origin = "https://frontend.example"
        client = self._create_client([trusted_origin])

        preflight = client.options(
            "/probe",
            headers={
                "Origin": trusted_origin,
                "Access-Control-Request-Method": "GET",
                "Access-Control-Request-Private-Network": "true",
            },
        )

        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(
            preflight.headers["access-control-allow-private-network"],
            "true",
        )

    def test_explicit_wildcard_does_not_enable_credentials(self):
        """显式通配符保留兼容能力，但不得再次形成反射 Origin 的组合。"""

        client = self._create_client(["*"])
        origin = "https://frontend.example"

        response = client.get("/probe", headers={"Origin": origin})
        preflight = client.options(
            "/probe",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "GET",
            },
        )

        self.assertEqual(response.headers["access-control-allow-origin"], "*")
        self.assertNotIn("access-control-allow-credentials", response.headers)
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(preflight.headers["access-control-allow-origin"], "*")
        self.assertNotIn("access-control-allow-credentials", preflight.headers)

    def test_untrusted_multipart_request_is_rejected_before_side_effect(self):
        """无需预检的 multipart 请求也必须在进入上传处理函数前返回 403。"""

        application = FastAPI()
        save_upload = Mock(return_value="stored.mp3")

        @application.post("/upload")
        def upload(file: UploadFile = File(...)):
            return {"file": save_upload(file.filename)}

        asgi.configure_browser_access(application, [])
        client = TestClient(application)

        response = client.post(
            "/upload",
            headers={"Origin": "https://evil.attacker.example"},
            files={
                "file": (
                    "attack.mp3",
                    b"attacker-controlled",
                    "audio/mpeg",
                )
            },
        )

        self.assertEqual(response.status_code, 403)
        save_upload.assert_not_called()


if __name__ == "__main__":
    unittest.main()
