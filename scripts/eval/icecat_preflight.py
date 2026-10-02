# -*- coding: utf-8 -*-
"""验证 Open Icecat JSON API 的账号、token 与最小商品读取能力。

真实凭据只从进程环境或项目根目录的 .env 读取。脚本不会打印 token，也不会
把 API 响应写入磁盘。通过后再执行批量索引和商品下载，避免带着错误配置跑长任务。

用法：
    uv run python scripts/eval/icecat_preflight.py
    uv run python scripts/eval/icecat_preflight.py --icecat-id 93840431
"""
from __future__ import annotations

import argparse
import os
import json
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ICECAT_API_URL = "https://live.icecat.biz/api"


def _read_local_env() -> dict[str, str]:
    """读取简单 KEY=VALUE 配置；不执行插值，也不覆盖进程环境。"""
    values: dict[str, str] = {}
    env_path = PROJECT_ROOT / ".env"
    if not env_path.exists():
        return values
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name, value = name.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[name] = value
    return values


def _load_config(icecat_id_override: str | None) -> dict[str, str]:
    local_env = _read_local_env()

    def setting(name: str, default: str = "") -> str:
        return os.getenv(name, local_env.get(name, default)).strip()

    username = setting("ICECAT_USERNAME")
    api_token = setting("ICECAT_API_TOKEN")
    content_token = setting("ICECAT_CONTENT_TOKEN")
    icecat_id = (
        (icecat_id_override or "").strip()
        or setting("ICECAT_TEST_PRODUCT_ID", "93840431")
    )

    missing = [
        name
        for name, value in (
            ("ICECAT_USERNAME", username),
            ("ICECAT_API_TOKEN", api_token),
            ("ICECAT_TEST_PRODUCT_ID", icecat_id),
        )
        if not value
    ]
    if missing:
        raise ValueError(
            "缺少配置："
            + ", ".join(missing)
            + "。请只在项目根目录 .env 或当前进程环境中设置。"
        )
    return {
        "username": username,
        "api_token": api_token,
        "content_token": content_token,
        "icecat_id": icecat_id,
    }


def _extract_error(payload: dict[str, Any]) -> str | None:
    data = payload.get("data")
    if isinstance(data, dict):
        content_error = data.get("ContentErrors")
        if content_error:
            return str(content_error)
    message = payload.get("msg")
    if message and str(message).upper() != "OK":
        return str(message)
    return None


def _run(icecat_id_override: str | None) -> int:
    try:
        config = _load_config(icecat_id_override)
    except ValueError as exc:
        print(f"配置检查失败：{exc}", file=sys.stderr)
        return 2

    headers = {"api-token": config["api_token"], "Accept": "application/json"}
    if config["content_token"]:
        headers["content-token"] = config["content_token"]
    params = {
        "lang": "EN",
        "shopname": config["username"],
        "icecat_id": config["icecat_id"],
        "content": "essentialinfo,title,featuregroups",
    }

    request = Request(f"{ICECAT_API_URL}?{urlencode(params)}", headers=headers, method="GET")
    try:
        with urlopen(request, timeout=30) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        print(f"Icecat HTTP 检查失败：HTTP {exc.code}", file=sys.stderr)
        try:
            error_payload = json.loads(exc.read().decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            error_payload = None
        if isinstance(error_payload, dict):
            error_message = _extract_error(error_payload)
            if error_message:
                print(f"Icecat 返回：{error_message}", file=sys.stderr)
        return 3
    except (URLError, TimeoutError, OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        print(f"Icecat 请求或 JSON 解析失败：{type(exc).__name__}: {exc}", file=sys.stderr)
        return 3

    if not isinstance(payload, dict):
        print("Icecat 返回格式异常：顶层不是 JSON 对象", file=sys.stderr)
        return 4
    if error := _extract_error(payload):
        print(f"Icecat 业务检查失败：{error}", file=sys.stderr)
        print("若提示商品无权限，请在 .env 中换一个 Open Icecat 商品 ID 后重试。")
        return 4

    data = payload.get("data")
    general = data.get("GeneralInfo", {}) if isinstance(data, dict) else {}
    returned_id = general.get("IcecatId") or general.get("IcecatID") or config["icecat_id"]
    title = general.get("Title") or general.get("ProductName") or "（标题字段未返回）"
    brand = general.get("Brand") or "（品牌字段未返回）"

    print("Open Icecat 连通性检查通过")
    print(f"  Icecat ID: {returned_id}")
    print(f"  品牌: {brand}")
    print(f"  标题: {title}")
    print("  凭据: 已验证，未打印、未落盘")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="验证 Open Icecat JSON API 连通性")
    parser.add_argument("--icecat-id", help="覆盖 ICECAT_TEST_PRODUCT_ID")
    args = parser.parse_args()
    raise SystemExit(_run(args.icecat_id))


if __name__ == "__main__":
    main()
