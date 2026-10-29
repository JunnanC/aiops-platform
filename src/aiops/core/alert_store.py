"""告警持久化存储：以 JSONL 追加写入，供看板读取最近告警。

与 console/file(人类可读)/dingtalk 通道解耦——这里是给"程序"读的结构化留档。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from .models import Alert


class AlertStore:
    def __init__(self, state_dir: Path, filename: str = "alerts.jsonl"):
        self.path = Path(state_dir) / filename
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def append(self, alert: Alert) -> None:
        record = {
            "rule_id": alert.rule_id,
            "severity": alert.severity,
            "service": alert.service,
            "message": alert.message,
            "count": alert.count,
            "created_at": alert.created_at.isoformat(),
            "fingerprint": alert.fingerprint,
        }
        with self.path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    def recent(self, limit: int = 50) -> list[dict]:
        if not self.path.exists():
            return []
        lines = self.path.read_text(encoding="utf-8", errors="replace").splitlines()
        items: list[dict] = []
        for line in lines[-limit:]:
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return list(reversed(items))  # 最新在前

    def counts_by_severity(self) -> dict[str, int]:
        agg: dict[str, int] = {}
        for a in self.recent(limit=1000):
            agg[a["severity"]] = agg.get(a["severity"], 0) + 1
        return agg
