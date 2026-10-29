"""零依赖 Web 看板：标准库 http.server 起 REST API + 托管单文件前端。

API：
  GET  /                    -> dashboard.html
  GET  /api/summary         -> 服务健康 + 告警统计 + 规则数
  GET  /api/services        -> 实时探测所有服务
  GET  /api/alerts          -> 最近告警 (来自 AlertStore JSONL)
  POST /api/deploy-plan     -> {changes:[...]} 推导部署计划
  POST /api/probe-alert     -> 跑一次探测并对异常告警
"""

from __future__ import annotations

import json
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ..alert.notify import AlertDispatcher
from ..config import load_config, load_rules
from ..core.alert_store import AlertStore
from ..core.models import Alert
from ..detect.health_probe import probe_service
from ..deploy.deployer import build_plan

WEB_DIR = Path(__file__).resolve().parent


class _State:
    """一次 serve 进程内共享的配置与存储。"""

    def __init__(self, config_path: str | None):
        self.cfg = load_config(config_path)
        self.rules = load_rules()
        self.store = AlertStore(self.cfg.state_dir)
        self._lock = threading.Lock()

    def services_snapshot(self) -> list[dict]:
        results = []
        for spec in self.cfg.services:
            res = probe_service(spec)
            results.append(
                {
                    "name": res.service,
                    "kind": spec.kind,
                    "target": spec.target,
                    "healthy": res.healthy,
                    "detail": res.detail,
                    "latency_ms": round(res.latency_ms or 0),
                }
            )
        return results

    def summary(self) -> dict:
        services = self.services_snapshot()
        return {
            "services_total": len(services),
            "services_down": sum(1 for s in services if not s["healthy"]),
            "rules_count": len(self.rules),
            "channels": [c.kind for c in self.cfg.channels],
            "alerts_by_severity": self.store.counts_by_severity(),
            "services": services,
        }

    def probe_and_alert(self) -> dict:
        with self._lock:
            dispatcher = AlertDispatcher(self.cfg.channels, store=self.store)
            fired = 0
            for res in [probe_service(s) for s in self.cfg.services]:
                if not res.healthy:
                    fired += dispatcher.dispatch(
                        [
                            Alert(
                                rule_id="health_probe_failed",
                                severity="critical",
                                service=res.service,
                                message=f"健康探测失败: {res.detail}",
                            )
                        ]
                    )
            return {"down_alerts_sent": fired}


def _build_handler(state: _State):
    class Handler(BaseHTTPRequestHandler):
        def _send_json(self, obj, status=200):
            body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)

        def _send_html(self, text: str):
            body = text.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802
            path = urllib.parse.urlparse(self.path).path
            if path in ("/", "/index.html", "/dashboard"):
                self._send_html((WEB_DIR / "dashboard.html").read_text(encoding="utf-8"))
            elif path == "/api/summary":
                self._send_json(state.summary())
            elif path == "/api/services":
                self._send_json(state.services_snapshot())
            elif path == "/api/alerts":
                self._send_json(state.store.recent(limit=100))
            else:
                self._send_json({"error": "not found"}, status=404)

        def do_POST(self):  # noqa: N802
            path = urllib.parse.urlparse(self.path).path
            length = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(length) if length else b"{}"
            try:
                payload = json.loads(raw.decode("utf-8") or "{}")
            except json.JSONDecodeError:
                return self._send_json({"error": "bad json"}, status=400)

            if path == "/api/deploy-plan":
                changes = payload.get("changes", [])
                plan = build_plan(changes)
                self._send_json(
                    {
                        "actions": [
                            {"kind": a.kind, "description": a.description, "commands": a.commands}
                            for a in plan.actions
                        ]
                    }
                )
            elif path == "/api/probe-alert":
                self._send_json(state.probe_and_alert())
            else:
                self._send_json({"error": "not found"}, status=404)

        def log_message(self, fmt, *args):  # 降噪
            pass

    return Handler


def serve(host: str = "127.0.0.1", port: int = 8890, config_path: str | None = None) -> None:
    state = _State(config_path)
    handler = _build_handler(state)
    httpd = ThreadingHTTPServer((host, port), handler)
    url = f"http://{host}:{port}"
    print(f"AIOps 看板已启动: {url}")
    print("按 Ctrl-C 停止。")
    # 预置几条演示告警，保证第一次打开看板就有内容
    if not state.store.recent(limit=1):
        for a in [
            Alert("app_exception", "critical", "django", "[应用异常/崩溃关键字] Traceback ..."),
            Alert("resource_risk", "warning", "mysql", "[内存/磁盘资源风险] Slow query 3100ms"),
        ]:
            state.store.append(a)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止。")
        httpd.server_close()
