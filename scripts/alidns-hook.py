#!/usr/bin/env python3
"""alidns-hook.py — certbot DNS-01 自动续期钩子（阿里云 DNS）。

用途：给 Let's Encrypt 签发/续期 HTTPS 证书时，certbot 通过 --dns-hook 调用本脚本，
自动在阿里云解析里添加 / 删除 TXT 验证记录，实现全自动续期，无需人工。

certbot 集成方式（env 方式配置）：
    certbot certonly --manual \
        --preferred-challenges dns \
        --manual-auth-hook  "python3 alidns-hook.py present" \
        --manual-cleanup-hook "python3 alidns-hook.py cleanup"

依赖环境变量：
    ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET
    ALIYUN_DOMAIN            主域，例如 edutech-lab.top
certbot 注入：
    CERTBOT_DOMAIN           需验证的域名
    CERTBOT_VALIDATION       TXT 记录值

纯标准库实现（阿里云 RPC 风格签名 = HMAC-SHA1）。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import sys
import time
import urllib.parse
import urllib.request
import uuid
import json


API_ENDPOINT = "https://alidns.aliyuncs.com/"
API_VERSION = "2015-08-01"


def _percent_encode(s: str) -> str:
    """RFC3986 编码，适配阿里云签名规则。"""
    return (
        urllib.parse.quote(str(s), safe="")
        .replace("+", "%20")
        .replace("*", "%2A")
        .replace("%7E", "~")
    )


def _rpc_request(action: str, extra_params: dict[str, str]) -> dict:
    ak = os.environ.get("ALIYUN_ACCESS_KEY_ID")
    sk = os.environ.get("ALIYUN_ACCESS_KEY_SECRET")
    if not ak or not sk:
        raise RuntimeError(
            "缺少 ALIYUN_ACCESS_KEY_ID / ALIYUN_ACCESS_KEY_SECRET 环境变量"
        )

    params: dict[str, str] = {
        "Action": action,
        "Format": "JSON",
        "Version": API_VERSION,
        "AccessKeyId": ak,
        "SignatureMethod": "HMAC-SHA1",
        "SignatureVersion": "1.0",
        "SignatureNonce": uuid.uuid4().hex,
        "Timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    params.update(extra_params)

    canon_qs = "&".join(
        f"{_percent_encode(k)}={_percent_encode(params[k])}" for k in sorted(params)
    )
    string_to_sign = f"GET&{_percent_encode('/')}&{_percent_encode(canon_qs)}"
    signature = base64.b64encode(
        hmac.new((sk + "&").encode(), string_to_sign.encode(), hashlib.sha1).digest()
    ).decode()
    params["Signature"] = signature

    url = API_ENDPOINT + "?" + urllib.parse.urlencode(params)
    with urllib.request.urlopen(url, timeout=15) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _split_domain(full_domain: str, root: str) -> tuple[str, str]:
    """把 sub.teacher.edutech-lab.top 拆成 (RR='sub.teacher', Domain='edutech-lab.top')。"""
    if full_domain.endswith(root):
        rr = full_domain[: -len(root)].strip(".")
        return (rr or "@"), root
    return full_domain, root


def present() -> int:
    domain = os.environ.get("CERTBOT_DOMAIN", "")
    value = os.environ.get("CERTBOT_VALIDATION", "")
    root = os.environ.get("ALIYUN_DOMAIN", domain)
    if not domain:
        print("未检测到 CERTBOT_DOMAIN", file=sys.stderr)
        return 1
    rr, main = _split_domain(domain, root)
    print(f"[present] 添加 TXT 记录: {rr}.{main} -> {value}")
    res = _rpc_request(
        "AddDomainRecord",
        {"DomainName": main, "RR": rr, "Type": "TXT", "Value": value, "TTL": "600"},
    )
    print(f"[present] 响应: {res}")
    return 0


def cleanup() -> int:
    domain = os.environ.get("CERTBOT_DOMAIN", "")
    root = os.environ.get("ALIYUN_DOMAIN", domain)
    rr, main = _split_domain(domain, root)
    print(f"[cleanup] 删除 {rr}.{main} 的 TXT 记录")
    try:
        lst = _rpc_request(
            "DescribeDomainRecords",
            {"DomainName": main, "RRKeyWord": rr, "Type": "TXT"},
        )
        for rec in lst.get("DomainRecords", {}).get("Record", []):
            _rpc_request("DeleteDomainRecord", {"RecordId": rec["RecordId"]})
            print(f"[cleanup] 已删除 RecordId={rec['RecordId']}")
    except Exception as exc:  # noqa: BLE001
        print(f"[cleanup] 清理失败(可忽略): {exc}", file=sys.stderr)
    return 0


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "present"
    if not os.environ.get("ALIYUN_ACCESS_KEY_ID"):
        print("演示/未配置模式：跳过真实 API 调用。", file=sys.stderr)
        print("需要设置 ALIYUN_ACCESS_KEY_ID/SECRET 与 ALIYUN_DOMAIN。", file=sys.stderr)
        return 0
    return present() if mode == "present" else cleanup()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
