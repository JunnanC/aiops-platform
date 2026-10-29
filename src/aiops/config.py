"""配置加载：主配置 (platform.toml) + 告警规则 (rules.toml)，均用标准库 tomllib 解析。"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .core.models import ServiceSpec

DEFAULT_ROOT = Path(__file__).resolve().parents[2]  # .../aiops-platform


@dataclass
class AlertChannel:
    kind: str                 # console | file | dingtalk
    path: str | None = None   # file 通道落盘路径
    webhook_env: str | None = None  # dingtalk webhook 所在环境变量名
    secret_env: str | None = None   # dingtalk 加签密钥所在环境变量名


@dataclass
class PlatformConfig:
    root: Path
    state_dir: Path
    log_source: str
    services: list[ServiceSpec]
    channels: list[AlertChannel]
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def rules_path(self) -> Path:
        return self.root / "config" / "rules.toml"


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _parse_channels(raw_channels: list[dict[str, Any]]) -> list[AlertChannel]:
    channels: list[AlertChannel] = []
    for ch in raw_channels:
        channels.append(
            AlertChannel(
                kind=ch.get("kind", "console"),
                path=ch.get("path"),
                webhook_env=ch.get("webhook_env"),
                secret_env=ch.get("secret_env"),
            )
        )
    return channels or [AlertChannel(kind="console")]


def load_config(config_path: str | os.PathLike[str] | None = None) -> PlatformConfig:
    cfg_path = Path(config_path) if config_path else DEFAULT_ROOT / "config" / "platform.toml"
    root = cfg_path.resolve().parents[1]
    data = _load_toml(cfg_path)

    services = [
        ServiceSpec(
            name=s["name"],
            kind=s.get("kind", "http"),
            target=s["target"],
            timeout=float(s.get("timeout", 3.0)),
            expected_status=int(s.get("expected_status", 200)),
        )
        for s in data.get("services", [])
    ]

    channels = _parse_channels(data.get("alerting", {}).get("channels", []))

    return PlatformConfig(
        root=root,
        state_dir=root / data.get("runtime", {}).get("state_dir", "state"),
        log_source=data.get("ingest", {}).get("log_source", "state/containers.log"),
        services=services,
        channels=channels,
        raw=data,
    )


def load_rules(path: str | os.PathLike[str] | None = None) -> list[dict[str, Any]]:
    rules_path = Path(path) if path else DEFAULT_ROOT / "config" / "rules.toml"
    data = _load_toml(rules_path)
    return data.get("rules", [])
