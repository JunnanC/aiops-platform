"""日志采集层：跟随 (tail -f 语义) fluent-bit 落盘的 json_lines 日志，结构化为 LogEvent。

fluent-bit 的 `file` output 以 `Format json_lines` 写出后，本模块逐行 json 解析，
兼容纯文本行 (整行降级为 message)。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

from ..core.models import LogEvent


def parse_line(line: str) -> LogEvent:
    line = line.rstrip("\n")
    if not line.strip():
        raise ValueError("empty line")
    try:
        data = json.loads(line)
        if isinstance(data, dict):
            return LogEvent.from_dict(data)
    except json.JSONDecodeError:
        pass
    # 纯文本行降级
    return LogEvent(
        timestamp=datetime.now(timezone.utc),
        service="unknown",
        level="",
        message=line,
        raw={"line": line},
    )


class LogTailer:
    """类似 `tail -f`：记住读到的字节偏移，只吐出新增行。"""

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def read_once(self) -> Iterator[LogEvent]:
        """读取当前文件全部内容 (演示 / 定时批处理模式)。"""
        if not self.path.exists():
            return
        text = self.path.read_text(encoding="utf-8", errors="replace")
        for line in text.splitlines():
            try:
                yield parse_line(line)
            except ValueError:
                continue

    def follow(self) -> Iterator[LogEvent]:
        """阻塞跟随新增行 (常驻采集模式，Ctrl-C 退出)。"""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        with self.path.open("r", encoding="utf-8", errors="replace") as fh:
            fh.seek(0, os.SEEK_END)
            while True:
                line = fh.readline()
                if not line:
                    # 无新数据时短暂让出 CPU
                    time.sleep(0.5)
                    continue
                try:
                    yield parse_line(line)
                except ValueError:
                    continue
