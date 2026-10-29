"""自动部署层：按变更文件类型推导最小影响面的发布动作。

策略对齐 agent2 的真实机制（bind-mount 后端 + 多阶段前端）：
  - 后端 *.py 变   -> rsync 同步 + docker compose restart django celery（不重建镜像）
  - 依赖锁变        -> docker compose build <svc> + up -d --force-recreate
  - 前端源码变      -> docker compose build nginx + up -d --force-recreate nginx
  - compose/infra 变 -> docker compose up -d --force-recreate（配置生效）
  - .env 变         -> 重启依赖该配置的服务
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..core.models import DeployAction, DeployPlan

# 触发「最小面热更新」而非重建的文件模式
BACKEND_SUFFIX = (".py",)
DEP_LOCK_NAMES = ("uv.lock", "requirements.txt", "poetry.lock", "package-lock.json")
FRONTEND_DIR = ("frontend/", "web/")
FRONTEND_SUFFIX = (".ts", ".tsx", ".jsx", ".vue")
FRONTEND_CONFIG_NAMES = ("vite.config",)
INFRA_MARKERS = (
    "docker-compose",
    "nginx.conf",
    "nginx.prod.conf",
    "kong.yml",
    "Dockerfile",
    "compose.yaml",
    "compose.yml",
)
ENV_NAMES = (".env",)


def classify_changes(paths: list[str]) -> dict[str, list[str]]:
    """把变更文件按部署影响面归类。"""
    buckets: dict[str, list[str]] = {
        "backend": [],
        "deps": [],
        "frontend": [],
        "infra": [],
        "env": [],
        "other": [],
    }
    for p in paths:
        name = Path(p).name
        if name in ENV_NAMES:
            buckets["env"].append(p)
        elif name in DEP_LOCK_NAMES:
            buckets["deps"].append(p)
        elif any(p.endswith(s) for s in BACKEND_SUFFIX):
            buckets["backend"].append(p)
        elif (
            any(d in p for d in FRONTEND_DIR)
            or any(p.endswith(s) for s in FRONTEND_SUFFIX)
            or any(c in p for c in FRONTEND_CONFIG_NAMES)
        ):
            buckets["frontend"].append(p)
        elif any(m in p for m in INFRA_MARKERS):
            buckets["infra"].append(p)
        else:
            buckets["other"].append(p)
    return buckets


def build_plan(
    paths: list[str],
    *,
    backend_services: tuple[str, ...] = ("django", "celery"),
    sync_src: str = ".",
    sync_dst: str = "/opt/agent2/",
    dry_run: bool = True,
) -> DeployPlan:
    """由变更文件列表生成 DeployPlan（默认 dry-run，只产出命令不执行）。"""
    buckets = classify_changes(paths)
    actions: list[DeployAction] = []

    if buckets["backend"]:
        actions.append(
            DeployAction(
                kind="sync",
                description=f"同步 {len(buckets['backend'])} 个后端源码变更 (rsync, 排除 .git/.env/node_modules)",
                commands=[
                    f"rsync -rltz --stats --exclude .git --exclude .env "
                    f"--exclude node_modules {sync_src}/ {sync_dst}",
                ],
            )
        )
        actions.append(
            DeployAction(
                kind="restart",
                description="后端为 bind-mount，仅重启容器即可热更新，无需重建镜像",
                commands=[f"docker compose restart {' '.join(backend_services)}"],
            )
        )

    if buckets["deps"]:
        targets = " ".join(backend_services)
        actions.append(
            DeployAction(
                kind="rebuild",
                description=f"检测到依赖锁变更 ({', '.join(Path(p).name for p in buckets['deps'])})，重建并强制替换镜像",
                commands=[
                    f"docker compose build {targets}",
                    f"docker compose up -d --force-recreate {targets}",
                ],
            )
        )

    if buckets["frontend"]:
        actions.append(
            DeployAction(
                kind="build",
                description="前端为多阶段镜像 (node build 烤进 nginx)，须重建 nginx",
                commands=[
                    "docker compose build nginx",
                    "docker compose up -d --force-recreate nginx",
                ],
            )
        )

    if buckets["infra"]:
        actions.append(
            DeployAction(
                kind="recreate",
                description="compose/网关/nginx 等基础设施配置变更，force-recreate 生效",
                commands=[
                    "docker compose up -d --force-recreate "
                    "nginx workspace-gateway kong"
                ],
            )
        )

    if buckets["env"]:
        actions.append(
            DeployAction(
                kind="restart",
                description=f".env 变更，重启依赖运行时配置的服务",
                commands=[f"docker compose restart {' '.join(backend_services)}"],
            )
        )

    return DeployPlan(actions=actions, changed_paths=paths, dry_run=dry_run)


def run_plan(plan: DeployPlan, *, verbose: bool = True) -> list[tuple[str, int]]:
    """执行部署计划。dry-run 只打印；否则用 subprocess 顺序执行，返回 (命令, 退出码)。"""
    results: list[tuple[str, int]] = []
    for action in plan.actions:
        if verbose:
            print(f"\n▶ {action.kind}: {action.description}")
        for cmd in action.commands:
            if verbose:
                print(f"  $ {cmd}")
            if plan.dry_run:
                results.append((cmd, 0))
                continue
            rc = subprocess.call(cmd, shell=True)
            results.append((cmd, rc))
            if rc != 0:
                if verbose:
                    print(f"  ✗ 命令失败 rc={rc}，中止后续动作")
                return results
    return results
