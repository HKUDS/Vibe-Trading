#!/usr/bin/env python3
"""Call the Iwencai announcement search API and pass through the raw body."""

import argparse
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from pathlib import Path


SKILL_ID = "announcement-search"
SKILL_VERSION = "1.0.0"
DEFAULT_BASE_URL = "https://openapi.iwencai.com"
DEFAULT_ENDPOINT = "/v1/comprehensive/search"
DEFAULT_TIMEOUT = 30
DEFAULT_SIZE = 10

MISSING_KEY_NOTICE = """首次使用 - 获取 API Key
所有技能都需要 IWENCAI_API_KEY 环境变量才能使用。 如果用户尚未配置，按以下步骤引导：

步骤 1：获取 API Key
在浏览器内打同花顺i问财SkillHub页面：https://www.iwencai.com/skillhub

步骤 2：登录

步骤 3：点击具体的Skill，打开弹窗查看详情，在安装方式-Agent用户-找到您的IWENCAI_API_KEY这一段，复制

步骤 4：配置环境变量
获取到 API Key 后，直接复制指引文字发送给AI助手，或手动设置环境变量："""


def parse_args():
    parser = argparse.ArgumentParser(
        description="Search financial announcements through the Iwencai OpenAPI gateway.",
    )
    parser.add_argument("query", help="Natural-language announcement search query.")
    parser.add_argument("--size", type=int, default=DEFAULT_SIZE, help="Requested result count.")
    parser.add_argument("--base-url", default=os.getenv("IWENCAI_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--endpoint", default=os.getenv("IWENCAI_ENDPOINT", DEFAULT_ENDPOINT))
    parser.add_argument("--timeout", type=int, default=int(os.getenv("IWENCAI_TIMEOUT", DEFAULT_TIMEOUT)))
    parser.add_argument("--output", help="Write the raw response body unchanged to this file.")
    return parser.parse_args()


def build_headers(api_key, call_type="normal"):
    return {
        "Content-Type": "application/json",
        "Authorization": "Bearer " + api_key,
        "X-Claw-Call-Type": call_type,
        "X-Claw-Skill-Id": SKILL_ID,
        "X-Claw-Skill-Version": SKILL_VERSION,
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": secrets.token_hex(32),
    }


def build_body(query, size):
    return {
        "query": query,
        "channels": ["announcement"],
        "app_id": "AIME_SKILL",
        "size": size,
    }


def call_api(args, api_key):
    url = args.base_url.rstrip("/") + "/" + args.endpoint.lstrip("/")
    body = json.dumps(build_body(args.query, args.size), ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers=build_headers(api_key),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=args.timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def emit_raw_body(raw_body, output_path=None):
    if output_path:
        Path(output_path).write_bytes(raw_body)
        return
    sys.stdout.buffer.write(raw_body)
    if raw_body and not raw_body.endswith(b"\n"):
        sys.stdout.buffer.write(b"\n")


def main():
    args = parse_args()
    api_key = os.getenv("IWENCAI_API_KEY")
    if not api_key:
        print("IWENCAI_API_KEY is not set.", file=sys.stderr)
        print(MISSING_KEY_NOTICE, file=sys.stderr)
        return 2

    try:
        status_code, raw_body = call_api(args, api_key)
    except urllib.error.URLError as exc:
        print("Network error: " + str(exc), file=sys.stderr)
        return 1
    except TimeoutError as exc:
        print("Timeout: " + str(exc), file=sys.stderr)
        return 1

    emit_raw_body(raw_body, args.output)
    if status_code in (401, 403):
        print(MISSING_KEY_NOTICE, file=sys.stderr)
    return 0 if 200 <= status_code < 300 else 1


if __name__ == "__main__":
    raise SystemExit(main())
