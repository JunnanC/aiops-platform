"""部署计划推导单元测试：验证不同变更文件映射到正确的最小面动作。"""

import unittest

from aiops.deploy.deployer import build_plan, classify_changes


class DeployerTest(unittest.TestCase):
    def test_backend_only_restarts(self):
        plan = build_plan(["backend/apps/accounts/views.py"])
        kinds = [a.kind for a in plan.actions]
        self.assertEqual(kinds, ["sync", "restart"])
        # 后端 .py 变更绝不应触发镜像重建
        self.assertNotIn("rebuild", kinds)

    def test_dep_lock_triggers_rebuild(self):
        plan = build_plan(["backend/uv.lock"])
        self.assertIn("rebuild", [a.kind for a in plan.actions])

    def test_frontend_triggers_nginx_build(self):
        plan = build_plan(["frontend/apps/student-web/src/App.tsx"])
        nginx_cmds = " ".join(c for a in plan.actions for c in a.commands)
        self.assertIn("docker compose build nginx", nginx_cmds)

    def test_infra_triggers_recreate(self):
        plan = build_plan(["deploy/nginx.conf"])
        self.assertIn("recreate", [a.kind for a in plan.actions])

    def test_mixed_changes(self):
        buckets = classify_changes(
            ["backend/x.py", "backend/uv.lock", "frontend/apps/a/app.ts", "docker-compose.dev.yml", ".env"]
        )
        self.assertIn("backend/x.py", buckets["backend"])
        self.assertIn("backend/uv.lock", buckets["deps"])
        self.assertIn("frontend/apps/a/app.ts", buckets["frontend"])
        self.assertIn("docker-compose.dev.yml", buckets["infra"])
        self.assertIn(".env", buckets["env"])

    def test_plan_is_dry_run_by_default(self):
        plan = build_plan(["backend/x.py"])
        self.assertTrue(plan.dry_run)


if __name__ == "__main__":
    unittest.main()
