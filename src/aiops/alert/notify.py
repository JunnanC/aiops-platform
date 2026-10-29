"""告警通知层：console / file / dingtalk 多通道。

钉钉自定义机器人采用「加签」安全设置：
  sign = urlencode(base64(HMAC_SHA256(secret, f"{timestamp}\\n{secret}")))
最终 webhook 拼接 timestamp 与 sign 两个 query 参数。
无凭证时自动降级为 console，保证 demo 永远跑得通。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.parse
import urllib.request
from datetime import timezone
from pathlib import Path

from ..config import AlertChannel
from ..core.models import Alert


def _render(alert: Alert) -> str:
    ts = alert.created_at.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    return f"[{alert.severity.upper()}] {ts} service={alert.service} rule={alert.rule_id} x{alert.count}\n  {alert.message}"


class ConsoleNotifier:
    kind = "console"

    def send(self, alert: Alert) -> bool:
        print(_render(alert))
        return True


class FileNotifier:
    kind = "file"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def send(self, alert: Alert) -> bool:
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(_render(alert) + "\n")
        return True


class DingTalkNotifier:
    kind = "dingtalk"

    def __init__(self, webhook: str, secret: str | None = None, timeout: float = 5.0):
        self.webhook = webhook
        self.secret = secret
        self.timeout = timeout

    def _signed_url(self, timestamp: str | None = None) -> str:
        if not self.secret:
            return self.webhook
        if timestamp is None:
            timestamp = str(round(time.time() * 1000))
        string_to_sign = f"{timestamp}\n{self.secret}"
        hmac_code = hmac.new(
            self.secret.encode("utf-8"), string_to_sign.encode("utf-8"), digestmod=hashlib.sha256
        ).digest()
        sign = urllib.parse.quote_plus(base64.b64encode(hmac_code))
        sep = "&" if "?" in self.webhook else "?"
        return f"{self.webhook}{sep}timestamp={timestamp}&sign={sign}"

    def send(self, alert: Alert) -> bool:
        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": f"AIOps {alert.severity} 告警",
                "text": (
                    f"### [{alert.severity.upper()}] {alert.rule_id}\n\n"
                    f"- **服务**: {alert.service}\n"
                    f"- **次数**: {alert.count}\n"
                    f"- **详情**: {alert.message}\n"
                ),
            },
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            self._signed_url(), data=data, headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8")
                return json.loads(body).get("errcode", 0) == 0
        except Exception as exc:
            print(f"[dingtalk] 发送失败: {exc}", flush=True)
            return False


def _build_notifier(channel: AlertChannel):
    if channel.kind == "dingtalk":
        webhook = os.environ.get(channel.webhook_env or "DINGTALK_WEBHOOK", "")
        if not webhook:
            # 无凭证 -> 降级 console，demo 不中断
            return ConsoleNotifier()
        secret = os.environ.get(channel.secret_env or "DINGTALK_SECRET", "") or None
        return DingTalkNotifier(webhook=webhook, secret=secret)
    if channel.kind == "file" and channel.path:
        return FileNotifier(channel.path)
    return ConsoleNotifier()


class AlertDispatcher:
    """统一分发：过滤冷却 -> 逐个通道发送 -> 可选结构化留档。"""

    def __init__(self, channels: list[AlertChannel], state=None, store=None):
        self.notifiers = [_build_notifier(ch) for ch in channels]
        self.state = state
        self.store = store

    def dispatch(self, alerts: list[Alert]) -> int:
        sent = 0
        for alert in alerts:
            if self.state is not None and not self.state.should_send(alert.fingerprint):
                continue
            # 逐个通道都发送，不能用 any() 短路，否则靠后的 file/dingtalk 通道会被跳过
            results = [bool(n.send(alert)) for n in self.notifiers]
            if any(results):
                if self.store is not None:
                    self.store.append(alert)
                if self.state is not None:
                    self.state.mark_sent(alert.fingerprint)
                sent += 1
        return sent
