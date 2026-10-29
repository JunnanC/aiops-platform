# 轻量级 AIOps 自动化运维平台（自研 · Python）

面向多服务、多门户实验平台的运维场景，用代码替代手工部署与被动排障，覆盖
**日志采集 → 异常检测 → 分级告警 → 自动部署 → 证书续期** 一条闭环链路。

设计约束：**零第三方运行时依赖**，全部基于 Python 标准库
（`argparse / urllib / socket / tomllib / hashlib / hmac / subprocess`），
因此在任意装了 Python 3.11+ 的机器上 `git clone` 后即可直接运行与演示。

---

## 快速开始

```bash
# 1) 查看配置概览
PYTHONPATH=src python -m aiops.cli status

# 1.5) 启动 Web 运维看板，然后浏览器打开 http://127.0.0.1:8890
PYTHONPATH=src python -m aiops.cli serve

# 2) 端到端演示（无需真实服务器/凭证，自动降级到 console 告警）
PYTHONPATH=src python -m aiops.cli demo

# 3) 实时采集日志并按规则告警
echo '{"ts":"2026-01-01T00:00:00Z","service":"django","level":"error","message":"Traceback ..."}' \
     >> state/containers.log
PYTHONPATH=src python -m aiops.cli ingest --file state/containers.log

# 4) 健康探测所有服务（异常时加 --alert 推送告警）
PYTHONPATH=src python -m aiops.cli probe --alert

# 5) 按变更文件推导部署计划（默认 dry-run，加 --apply 才真正执行）
PYTHONPATH=src python -m aiops.cli deploy --changes backend/a.py frontend/x/App.tsx uv.lock

# 6) 跑测试
PYTHONPATH=src python -m unittest discover -s tests -v
```

也可以 `pip install -e .` 后直接用 `aiops <子命令>`。

## 用 Docker 起完整栈

```bash
cp .env.example .env      # 填入 DINGTALK_WEBHOOK/SECRET，留空则降级 console
docker compose up -d      # nginx(被测) + fluent-bit(采集) + aiops(分析/告警)
```

---

## 目录结构

```
config/
  platform.toml        # 主配置：被监控服务清单 / 告警通道 / 部署参数
  rules.toml           # 检测规则：keyword / regex / threshold
  fluent-bit.conf      # 采集管线：tail docker 日志 -> json_lines 落盘
  parsers.conf         # fluent-bit 解析器
src/aiops/
  cli.py               # argparse 入口：status/ingest/probe/deploy/demo
  config.py            # tomllib 加载配置与规则
  core/models.py       # 数据模型：LogEvent/Alert/ServiceSpec/DeployPlan
  core/state.py        # 告警去重与冷却窗口（落盘 JSON）
  ingest/log_tailer.py # tail -f 语义采集 + 逐行结构化
  detect/rule_engine.py# 关键字/正则/滑动窗口阈值 规则引擎
  detect/health_probe.py # http/tcp/command 三类健康探针
  alert/notify.py      # console/file/dingtalk 多通道 + 加签
  deploy/deployer.py   # 变更分类 -> 最小影响面发布计划
scripts/alidns-hook.py # certbot DNS-01 阿里云自动续期钩子
tests/                 # 25 项 unittest，全程离线
.github/workflows/ci.yml # ruff + unittest + demo 冒烟
```

---

## 简历四条 ↔ 代码对应（面试自查）

1. **平台架构 / 可插拔模块 + Web 看板** → `cli.py` 用 argparse 编排各层；`config.py`+`rules.toml` 实现
   配置与规则外置；`core/models.py` 是跨层统一数据契约；`web/server.py` 用标准库 `http.server` 起
   REST API（`/api/summary`、`/api/alerts`、`/api/deploy-plan`、`/api/probe-alert`），`web/dashboard.html`
   是零依赖单文件前端看板（服务红绿灯、告警流、部署计划生成器，5 秒自动刷新）。
2. **可观测性与智能告警引擎** → `ingest/log_tailer.py`（跟随采集）+ `detect/rule_engine.py`
   （关键字/正则/阈值去抖动）+ `detect/health_probe.py`（多服务探活）+ `alert/notify.py`
   （钉钉加签、分级、`core/state.py` 冷却抑制风暴）。
3. **自动部署与 CI/CD** → `deploy/deployer.py` 按变更类型推导「后端只 restart、依赖锁才 rebuild、
   前端 build nginx、infra force-recreate」的最小面策略；`.github/workflows/ci.yml` 编排
   lint+test+冒烟，用预构建环境跳过 apt 加速。
4. **证书自动续期 + 资源调优** → `scripts/alidns-hook.py` 实现阿里云 RPC(HMAC-SHA1) 签名，
   certbot 通过钩子自动加/删 TXT 记录完成 DNS-01 签发续期。

## 面试话术要点（把它讲成"开发"而非"操作"）

- 强调**抽象分层**：采集/检测/决策/执行四层用统一数据模型串起来，新增一种告警或规则只改配置不改代码。
- 强调**算法细节**：阈值规则用单调时间戳滑窗 + 触发即清空做风暴抑制；告警用 SHA1 指纹 + 冷却窗口去重。
- 强调**可测性设计**：钉钉加签、部署计划、规则引擎都是纯函数/可注入，测试全程离线（`_signed_url(ts)` 注入固定时间戳）。
- 强调**工程落地**：部署策略对齐真实 bind-mount 后端——改 `.py` 只 `restart`、改依赖锁才重建镜像，把「运维」写成「按变更语义路由的代码」。
- 诚实边界：这是**轻量级自用平台/工具链**（CLI + 后台常驻），不是带 Web 控制台的企业级系统。

## 许可

MIT
