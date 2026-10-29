"""统一 CLI 入口：status / ingest / probe / deploy / demo 子命令。

运行方式（源码根 src 在 PYTHONPATH 下）：
    python -m aiops.cli <子命令> ...
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from .alert.notify import AlertDispatcher
from .config import load_config, load_rules
from .core.models import LogEvent
from .core.alert_store import AlertStore
from .core.state import AlertState
from .deploy.deployer import build_plan, run_plan
from .detect.health_probe import probe_service
from .detect.rule_engine import RuleEngine
from .ingest.log_tailer import LogTailer, parse_line


def _cmd_status(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    rules = load_rules()
    print(f"配置根目录 : {cfg.root}")
    print(f"日志来源   : {cfg.log_source}")
    print(f"告警通道   : {', '.join(c.kind for c in cfg.channels)}")
    print(f"探针服务   : {len(cfg.services)} 个 -> {[s.name for s in cfg.services]}")
    print(f"告警规则   : {len(rules)} 条 -> {[r.get('id') for r in rules]}")
    return 0


def _cmd_ingest(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    rules = load_rules()
    engine = RuleEngine(rules)
    state = AlertState(cfg.state_dir, cooldown_seconds=args.cooldown)
    store = AlertStore(cfg.state_dir)
    dispatcher = AlertDispatcher(cfg.channels, state=state, store=store)

    log_path = Path(args.file) if args.file else (cfg.root / cfg.log_source)
    tailer = LogTailer(log_path)

    if args.follow:
        print(f"实时跟随 {log_path} (Ctrl-C 退出)...", flush=True)
        stream = tailer.follow()
    else:
        stream = tailer.read_once()

    total, alerted = 0, 0
    for event in stream:
        total += 1
        alerts = engine.evaluate(event)
        if alerts:
            alerted += dispatcher.dispatch(alerts)
        if not args.follow and args.verbose:
            print(f"  {event.service}:{event.level} {event.message[:60]}")
    print(f"\n处理日志 {total} 条，触发并发送告警 {alerted} 条。")
    return 0


def _cmd_probe(args: argparse.Namespace) -> int:
    cfg = load_config(args.config)
    unhealthy = []
    for spec in cfg.services:
        res = probe_service(spec)
        mark = "OK " if res.healthy else "DOWN"
        print(f"[{mark}] {spec.name:<20} {spec.kind:<8} {res.target:<28} {res.detail}")
        if not res.healthy:
            unhealthy.append(res)
    if unhealthy and args.alert:
        from .core.models import Alert

        dispatcher = AlertDispatcher(cfg.channels, store=AlertStore(cfg.state_dir))
        for res in unhealthy:
            dispatcher.dispatch(
                [
                    Alert(
                        rule_id="health_probe_failed",
                        severity="critical",
                        service=res.service,
                        message=f"健康探测失败: {res.detail}",
                    )
                ]
            )
    print(f"\n探测 {len(cfg.services)} 个服务，异常 {len(unhealthy)} 个。")
    return 1 if unhealthy else 0


def _cmd_deploy(args: argparse.Namespace) -> int:
    changes = args.changes or []
    if args.from_git:
        import subprocess

        out = subprocess.run(
            f"git diff --name-only {args.from_git}", shell=True, capture_output=True, text=True
        ).stdout
        changes += [l for l in out.splitlines() if l.strip()]
    if not changes:
        print("没有传入变更文件。用 --changes a.py b.tsx ... 或 --from-git HEAD~1")
        return 2

    plan = build_plan(changes, dry_run=not args.apply)
    if plan.is_empty:
        print("根据变更未推导出任何部署动作（可能都是文档/测试类文件）。")
        return 0
    print(f"{'[LIVE]' if args.apply else '[DRY-RUN]'} 变更 {len(changes)} 个文件，推导 {len(plan.actions)} 个动作：")
    results = run_plan(plan, verbose=True)
    failed = [c for c, rc in results if rc != 0]
    if failed:
        print(f"\n✗ 有 {len(failed)} 条命令失败。")
        return 1
    print("\n✓ 部署计划" + ("已执行。" if args.apply else "（试运行，未真正执行，加 --apply 生效）。"))
    return 0


def _cmd_demo(args: argparse.Namespace) -> int:
    """端到端演示：造几条异常日志 -> 采集 -> 规则检测 -> 告警 (console)。无需外部依赖。"""
    print("== AIOps 端到端演示 ==\n")
    cfg = load_config(args.config)
    rules = load_rules()
    engine = RuleEngine(rules)

    sample_lines = [
        '{"ts":"%s","service":"django","level":"error","message":"Traceback (most recent call last): KeyError \'user_id\'"}'
        % datetime.now(timezone.utc).isoformat(),
        '{"ts":"%s","service":"celery","level":"warning","message":"Worker heartbeat lost"}'
        % datetime.now(timezone.utc).isoformat(),
        '{"ts":"%s","service":"mysql","level":"info","message":"Slow query took 3100ms OOM risk"}'
        % datetime.now(timezone.utc).isoformat(),
        '{"ts":"%s","service":"django","level":"info","message":"health check ok"}'
        % datetime.now(timezone.utc).isoformat(),
    ]
    state = AlertState(cfg.state_dir, cooldown_seconds=0)
    store = AlertStore(cfg.state_dir)
    dispatcher = AlertDispatcher(cfg.channels, state=state, store=store)

    print("-- 模拟采集日志并套用规则 --")
    fired_total = 0
    for line in sample_lines:
        event: LogEvent = parse_line(line)
        alerts = engine.evaluate(event)
        tag = "命中" if alerts else "--  "
        print(f"  [{tag}] {event.service}:{event.level} {event.message[:52]}")
        fired_total += dispatcher.dispatch(alerts)
    print(f"\n规则命中并发送告警 {fired_total} 条。\n")

    print("-- 阈值规则演示 (需 window 内累计) --")
    burst = "".join(
        '{"service":"django","level":"error","message":"Traceback connection reset"}\n' for _ in range(5)
    )
    burst_engine = RuleEngine(load_rules())
    burst_alerts = 0
    for line in burst.splitlines():
        burst_alerts += len(burst_engine.evaluate(parse_line(line)))
    print(f"  连续 5 条 error，累计命中(关键字+阈值)告警 {burst_alerts} 条。\n")

    print("-- 自动部署计划演示 (dry-run) --")
    plan = build_plan(
        ["backend/apps/accounts/views.py", "frontend/apps/student-web/src/App.tsx", "uv.lock"]
    )
    run_plan(plan, verbose=True)

    print("\n== 演示结束 ==")
    return 0


def _cmd_serve(args: argparse.Namespace) -> int:
    from .web.server import serve

    serve(host=args.host, port=args.port, config_path=args.config)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="aiops", description="轻量级 AIOps 自动化运维平台")
    parser.add_argument("--config", help="platform.toml 路径", default=None)
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("status", help="打印当前配置概览").set_defaults(func=_cmd_status)

    p_ing = sub.add_parser("ingest", help="采集日志并套用规则告警")
    p_ing.add_argument("--file", help="指定日志文件 (默认用配置里的 log_source)")
    p_ing.add_argument("--follow", action="store_true", help="实时跟随新增行")
    p_ing.add_argument("--cooldown", type=int, default=300, help="同指纹告警冷却秒数")
    p_ing.add_argument("--verbose", action="store_true")
    p_ing.set_defaults(func=_cmd_ingest)

    p_pr = sub.add_parser("probe", help="健康探测所有配置服务")
    p_pr.add_argument("--alert", action="store_true", help="异常时推送告警")
    p_pr.set_defaults(func=_cmd_probe)

    p_dp = sub.add_parser("deploy", help="按变更文件推导并执行部署计划")
    p_dp.add_argument("--changes", nargs="*", help="变更文件路径列表")
    p_dp.add_argument("--from-git", help="从 git diff <ref> 读取变更 (如 HEAD~1)")
    p_dp.add_argument("--apply", action="store_true", help="真正执行 (默认 dry-run)")
    p_dp.set_defaults(func=_cmd_deploy)

    sub.add_parser("demo", help="端到端演示").set_defaults(func=_cmd_demo)

    p_sv = sub.add_parser("serve", help="启动 Web 运维看板")
    p_sv.add_argument("--host", default="127.0.0.1")
    p_sv.add_argument("--port", type=int, default=8890)
    p_sv.set_defaults(func=_cmd_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
