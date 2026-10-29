"""领域数据模型 (dataclass)，贯穿采集—检测—告警—部署四层。"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class LogEvent:
    """一条被采集并结构化的容器/应用日志。"""

    timestamp: datetime
    service: str
    level: str
    message: str
    raw: Optional[dict[str, Any]] = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LogEvent":
        ts = data.get("ts") or data.get("time") or data.get("@timestamp")
        if isinstance(ts, (int, float)):
            when = datetime.fromtimestamp(ts, tz=timezone.utc)
        elif isinstance(ts, str):
            try:
                when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                when = utcnow()
        else:
            when = utcnow()
        return cls(
            timestamp=when,
            service=str(data.get("service") or data.get("container") or "unknown"),
            level=str(data.get("level") or data.get("log") or "").upper(),
            message=str(data.get("message") or data.get("log") or data.get("msg") or ""),
            raw=data,
        )


@dataclass
class Alert:
    """一条待发送的告警。fingerprint 用于去重与冷却 (cooldown)。"""

    rule_id: str
    severity: str            # info | warning | critical
    service: str
    message: str
    created_at: datetime = field(default_factory=utcnow)
    count: int = 1

    @property
    def fingerprint(self) -> str:
        key = f"{self.rule_id}|{self.service}|{self.message}"
        return hashlib.sha1(key.encode("utf-8")).hexdigest()[:16]


@dataclass
class ServiceSpec:
    """被健康探测的目标服务定义。"""

    name: str
    kind: str                # http | tcp | command
    target: str              # URL / "host:port" / shell 命令
    timeout: float = 3.0
    expected_status: int = 200


@dataclass
class ProbeResult:
    service: str
    healthy: bool
    detail: str
    latency_ms: Optional[float] = None
    checked_at: datetime = field(default_factory=utcnow)


@dataclass
class DeployAction:
    """一个部署动作：可执行的命令序列 + 人类可读说明。"""

    kind: str                # sync | restart | rebuild | recreate | build
    description: str
    commands: list[str] = field(default_factory=list)


@dataclass
class DeployPlan:
    """根据变更文件路径推导出的发布计划。"""

    actions: list[DeployAction] = field(default_factory=list)
    changed_paths: list[str] = field(default_factory=list)
    dry_run: bool = True

    @property
    def is_empty(self) -> bool:
        return not self.actions
