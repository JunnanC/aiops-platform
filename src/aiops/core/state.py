"""告警去重 / 冷却状态：按 fingerprint 记录最近发送时间，落盘为 JSON，进程重启后仍生效。"""

from __future__ import annotations

import json
import time
from pathlib import Path


class AlertState:
    def __init__(self, state_dir: Path, cooldown_seconds: int = 300):
        self.cooldown = cooldown_seconds
        self._path = Path(state_dir) / "alert_state.json"
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._last_sent: dict[str, float] = {}
        self._load()

    def _load(self) -> None:
        if self._path.exists():
            try:
                self._last_sent = json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._last_sent = {}

    def _save(self) -> None:
        self._path.write_text(
            json.dumps(self._last_sent, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def should_send(self, fingerprint: str) -> bool:
        last = self._last_sent.get(fingerprint)
        if last is None:
            return True
        return (time.time() - last) >= self.cooldown

    def mark_sent(self, fingerprint: str) -> None:
        self._last_sent[fingerprint] = time.time()
        # 清理 24h 未再触发的条目，避免无限增长
        cutoff = time.time() - 86400
        self._last_sent = {k: v for k, v in self._last_sent.items() if v >= cutoff}
        self._save()
