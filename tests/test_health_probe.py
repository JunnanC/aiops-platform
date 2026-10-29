"""健康探针测试：使用进程内 socket / http.server，全程离线。"""

import http.server
import socket
import socketserver
import threading
import unittest

from aiops.core.models import ServiceSpec
from aiops.detect.health_probe import probe_service


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")

    def log_message(self, *args):  # 静默
        pass


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class HealthProbeTest(unittest.TestCase):
    def test_tcp_open_port_healthy(self):
        port = _free_port()
        srv = socketserver.TCPServer(("127.0.0.1", port), _Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            res = probe_service(ServiceSpec("t", "tcp", f"127.0.0.1:{port}", timeout=2.0))
            self.assertTrue(res.healthy)
        finally:
            srv.shutdown()
            srv.server_close()

    def test_tcp_closed_port_unhealthy(self):
        port = _free_port()  # 未监听
        res = probe_service(ServiceSpec("t", "tcp", f"127.0.0.1:{port}", timeout=1.0))
        self.assertFalse(res.healthy)

    def test_http_200_healthy(self):
        port = _free_port()
        httpd = http.server.HTTPServer(("127.0.0.1", port), _Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            res = probe_service(ServiceSpec("h", "http", f"http://127.0.0.1:{port}/health", timeout=2.0))
            self.assertTrue(res.healthy)
            self.assertIn("200", res.detail)
        finally:
            httpd.shutdown()
            httpd.server_close()

    def test_command_probe(self):
        res = probe_service(ServiceSpec("c", "command", "true", timeout=2.0))
        self.assertTrue(res.healthy)
        res2 = probe_service(ServiceSpec("c", "command", "false", timeout=2.0))
        self.assertFalse(res2.healthy)


if __name__ == "__main__":
    unittest.main()
