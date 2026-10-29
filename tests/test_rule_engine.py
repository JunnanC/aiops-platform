"""规则引擎单元测试：keyword / regex / threshold。"""

from __future__ import annotations

import unittest

from aiops.core.models import LogEvent
from aiops.detect.rule_engine import RuleEngine
from datetime import datetime, timezone


def ev(service, level, message):
    return LogEvent(datetime.now(timezone.utc), service, level, message)


class RuleEngineTest(unittest.TestCase):
    def test_keyword_hit(self):
        engine = RuleEngine(
            [{"id": "exc", "type": "keyword", "service": "*", "keywords": ["Traceback"], "severity": "critical"}]
        )
        alerts = engine.evaluate(ev("django", "error", "Traceback ..."))
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0].rule_id, "exc")
        self.assertEqual(alerts[0].severity, "critical")

    def test_keyword_miss(self):
        engine = RuleEngine([{"id": "exc", "type": "keyword", "keywords": ["Traceback"]}])
        self.assertEqual(engine.evaluate(ev("django", "info", "all good")), [])

    def test_regex_slow_query(self):
        engine = RuleEngine(
            [{"id": "slow", "type": "regex", "service": "mysql", "pattern": r"took\s+\d{4,}ms"}]
        )
        self.assertEqual(len(engine.evaluate(ev("mysql", "warning", "query took 3100ms"))), 1)
        self.assertEqual(engine.evaluate(ev("mysql", "info", "query took 90ms")), [])

    def test_service_glob_filter(self):
        engine = RuleEngine([{"id": "exc", "type": "keyword", "service": "django", "keywords": ["boom"]}])
        self.assertEqual(engine.evaluate(ev("celery", "error", "boom")), [])
        self.assertEqual(len(engine.evaluate(ev("django", "error", "boom"))), 1)

    def test_threshold_needs_burst(self):
        rule = [{"id": "burst", "type": "threshold", "keywords": ["error"], "window_seconds": 60, "count": 3}]
        engine = RuleEngine(rule)
        # 前两次不触发
        self.assertEqual(engine.evaluate(ev("a", "error", "error x")), [])
        self.assertEqual(engine.evaluate(ev("a", "error", "error x")), [])
        # 第三次累计达标 -> 触发
        fired = engine.evaluate(ev("a", "error", "error x"))
        self.assertEqual(len(fired), 1)
        self.assertGreaterEqual(fired[0].count, 3)

    def test_threshold_reset_after_fire(self):
        rule = [{"id": "burst", "type": "threshold", "keywords": ["e"], "window_seconds": 60, "count": 2}]
        engine = RuleEngine(rule)
        engine.evaluate(ev("a", "error", "e"))
        self.assertEqual(len(engine.evaluate(ev("a", "error", "e"))), 1)
        # 触发后窗口清空，单独一条不应再次触发
        self.assertEqual(engine.evaluate(ev("a", "error", "e")), [])


if __name__ == "__main__":
    unittest.main()
