"""配置加载 + 日志解析测试。"""

import unittest
from pathlib import Path

from aiops.config import load_config, load_rules
from aiops.ingest.log_tailer import parse_line


ROOT = Path(__file__).resolve().parents[1]


class ConfigTest(unittest.TestCase):
    def test_load_platform_config(self):
        cfg = load_config(ROOT / "config" / "platform.toml")
        self.assertTrue(cfg.services, "至少应配置一个被监控服务")
        self.assertTrue(cfg.channels, "至少应有一个告警通道")
        names = {s.name for s in cfg.services}
        self.assertIn("django", names)

    def test_load_rules(self):
        rules = load_rules(ROOT / "config" / "rules.toml")
        ids = {r["id"] for r in rules}
        self.assertIn("app_exception", ids)
        self.assertIn("error_burst", ids)


class ParseLineTest(unittest.TestCase):
    def test_parse_json_line(self):
        ev = parse_line('{"ts":"2026-01-01T00:00:00Z","service":"mysql","level":"warn","message":"slow"}')
        self.assertEqual(ev.service, "mysql")
        self.assertEqual(ev.level, "WARN")
        self.assertEqual(ev.message, "slow")

    def test_parse_plain_text_line(self):
        ev = parse_line("just a raw log line")
        self.assertEqual(ev.service, "unknown")
        self.assertIn("raw log line", ev.message)


if __name__ == "__main__":
    unittest.main()
