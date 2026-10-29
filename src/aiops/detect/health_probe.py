"""健康探测层：支持 http / tcp / command 三类探针，纯标准库实现。"""

from __future__ import annotations

import socket
import subprocess
import time
import urllib.error
import urllib.request

from ..core.models import ProbeResult, ServiceSpec


def _probe_http(spec: ServiceSpec) -> ProbeResult:
    start = time.monotonic()
    req = urllib.request.Request(spec.target, method="GET", headers={"User-Agent": "aiops-probe/0.1"})
    try:
        with urllib.request.urlopen(req, timeout=spec.timeout) as resp:
            status = resp.getcode()
        latency = (time.monotonic() - start) * 1000
        healthy = status == spec.expected_status
        detail = f"HTTP {status} ({latency:.0f}ms)"
        return ProbeResult(spec.name, healthy, detail, latency)
    except urllib.error.HTTPError as exc:
        latency = (time.monotonic() - start) * 1000
        return ProbeResult(spec.name, False, f"HTTP {exc.code}", latency)
    except Exception as exc:  # URLError / timeout / 连接拒绝
        latency = (time.monotonic() - start) * 1000
        return ProbeResult(spec.name, False, f"连接失败: {exc}", latency)


def _probe_tcp(spec: ServiceSpec) -> ProbeResult:
    host, _, port = spec.target.partition(":")
    start = time.monotonic()
    try:
        with socket.create_connection((host, int(port)), timeout=spec.timeout):
            latency = (time.monotonic() - start) * 1000
            return ProbeResult(spec.name, True, f"TCP 可达 ({latency:.0f}ms)", latency)
    except Exception as exc:
        latency = (time.monotonic() - start) * 1000
        return ProbeResult(spec.name, False, f"TCP 失败: {exc}", latency)


def _probe_command(spec: ServiceSpec) -> ProbeResult:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            spec.target, shell=True, capture_output=True, text=True, timeout=spec.timeout
        )
        latency = (time.monotonic() - start) * 1000
        healthy = proc.returncode == 0
        detail = (proc.stdout or proc.stderr).strip()[:120] or f"exit={proc.returncode}"
        return ProbeResult(spec.name, healthy, detail, latency)
    except Exception as exc:
        latency = (time.monotonic() - start) * 1000
        return ProbeResult(spec.name, False, f"命令执行失败: {exc}", latency)


_DISPATCH = {"http": _probe_http, "tcp": _probe_tcp, "command": _probe_command}


def probe_service(spec: ServiceSpec) -> ProbeResult:
    fn = _DISPATCH.get(spec.kind)
    if fn is None:
        return ProbeResult(spec.name, False, f"未知探针类型: {spec.kind}")
    return fn(spec)
