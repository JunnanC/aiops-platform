"""告警指纹、冷却状态与钉钉加签算法测试。"""

import base64
import hashlib
import hmac
import unittest
import urllib.parse

from aiops.alert.notify import DingTalkNotifier
from aiops.core.models import Alert
from aiops.core.state import AlertState


class FingerprintTest(unittest.TestCase):
    def test_fingerprint_stable_and_dedup(self):
        a1 = Alert("r1", "critical", "django", "boom")
        a2 = Alert("r1", "critical", "django", "boom")
        a3 = Alert("r1", "critical", "celery", "boom")
        self.assertEqual(a1.fingerprint, a2.fingerprint)
        self.assertNotEqual(a1.fingerprint, a3.fingerprint)


class DingTalkSignTest(unittest.TestCase):
    def test_sign_algorithm_matches_spec(self):
        # 用固定 timestamp+secret 验证加签实现符合钉钉官方规范
        secret = "SECtest123"
        timestamp = "1700000000000"
        string_to_sign = f"{timestamp}\n{secret}"
        expected = base64.b64encode(
            hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()
        ).decode()
        url = DingTalkNotifier("https://oapi.dingtalk.com/robot/send?access_token=x", secret)._signed_url(timestamp)
        self.assertIn(f"sign={urllib.parse.quote_plus(expected)}", url)
        self.assertIn(f"timestamp={timestamp}", url)

    def test_no_secret_returns_raw_webhook(self):
        n = DingTalkNotifier("https://example.com/hook", secret=None)
        self.assertEqual(n._signed_url(), "https://example.com/hook")


class CooldownTest(unittest.TestCase):
    def test_cooldown_blocks_repeat(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            state = AlertState(Path(d), cooldown_seconds=3600)
            fp = "abc123"
            self.assertTrue(state.should_send(fp))
            state.mark_sent(fp)
            self.assertFalse(state.should_send(fp))

    def test_zero_cooldown_allows_repeat(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as d:
            state = AlertState(Path(d), cooldown_seconds=0)
            state.mark_sent("x")
            self.assertTrue(state.should_send("x"))


if __name__ == "__main__":
    unittest.main()
