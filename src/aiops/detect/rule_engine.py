"""检测层：关键字 / 正则 / 阈值滑动窗口的异常规则引擎。"""

from __future__ import annotations

import fnmatch
import re
import time
from collections import deque
from typing import Any

from ..core.models import Alert, LogEvent


def _service_matches(pattern: str, service: str) -> bool:
    return pattern == "*" or fnmatch.fnmatch(service, pattern)


class RuleEngine:
    """把 rules.toml 的规则套用到每条日志事件上。

    规则类型：
      keyword   —— message 命中任一关键字即告警
      regex     —— message 匹配正则即告警
      threshold —— 命中触发条件后，在 window_seconds 内累计达 count 次才告警 (去抖动)
    """

    def __init__(self, rules: list[dict[str, Any]]):
        self.rules = rules
        # threshold 规则的滑动窗口计数：rule_id -> deque[timestamp]
        self._windows: dict[str, deque[float]] = {}

    def evaluate(self, event: LogEvent) -> list[Alert]:
        alerts: list[Alert] = []
        for rule in self.rules:
            if not _service_matches(rule.get("service", "*"), event.service):
                continue
            alert = self._apply_rule(rule, event)
            if alert is not None:
                alerts.append(alert)
        return alerts

    def _matches_trigger(self, rule: dict[str, Any], event: LogEvent) -> bool:
        rtype = rule.get("type", "keyword")
        msg = event.message or ""
        if rtype == "keyword":
            keywords = rule.get("keywords", [])
            hit = any(k and k in msg for k in keywords)
            levels = rule.get("levels", [])
            if levels and event.level in levels:
                hit = True
            return hit
        if rtype == "regex":
            pattern = rule.get("pattern")
            return bool(pattern) and re.search(pattern, msg) is not None
        if rtype == "threshold":
            # threshold 用 keywords 或 regex 作为触发条件
            kw_hit = any(k and k in msg for k in rule.get("keywords", []))
            rx = rule.get("pattern")
            rx_hit = bool(rx) and re.search(rx, msg) is not None
            return kw_hit or rx_hit
        return False

    def _apply_rule(self, rule: dict[str, Any], event: LogEvent) -> Alert | None:
        if not self._matches_trigger(rule, event):
            return None

        rtype = rule.get("type", "keyword")
        rid = rule.get("id", "unnamed")

        if rtype == "threshold":
            window = float(rule.get("window_seconds", 60))
            need = int(rule.get("count", 5))
            dq = self._windows.setdefault(rid, deque())
            now = time.monotonic()
            dq.append(now)
            # 丢弃窗口外的时间戳
            while dq and now - dq[0] > window:
                dq.popleft()
            if len(dq) < need:
                return None
            fired_count = len(dq)
            dq.clear()  # 触发后清空，避免风暴
        else:
            fired_count = 1

        reason = rule.get("reason", rtype)
        return Alert(
            rule_id=rid,
            severity=rule.get("severity", "warning"),
            service=event.service,
            message=f"[{reason}] {event.message[:200]}",
            count=fired_count,
        )
