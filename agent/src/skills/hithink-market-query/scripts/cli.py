#!/usr/bin/env python3
"""
问财行情数据 - 行情数据查询 CLI

严格遵循 Iwencai (问财) OpenAPI 网关规范：
- 每次请求携带 8 个 X-Claw-* Header
- X-Claw-Trace-Id 为每次新生成的 64 字符十六进制唯一 ID
- Authorization Bearer 仅从环境变量 IWENCAI_API_KEY 读取
- 优先使用 POST
- 使用 Python3 标准库，跨平台兼容

注意：默认返回 10 条数据，可通过 --page 和 --limit 参数翻页获取更多数据
"""

import argparse
import json
import os
import secrets
import sys
import urllib.error
import urllib.request
from typing import Optional, Union


SKILL_NAME = "hithink-market-query"
SKILL_VERSION = "1.0.0"
DEFAULT_API_URL = "https://openapi.iwencai.com/v1/query2data"
DEFAULT_PAGE = "1"
DEFAULT_LIMIT = "10"
DEFAULT_TIMEOUT = 30


class APIError(Exception):
    """API 错误异常类"""
    def __init__(self, message: str, status_code: int = None, response: Union[str, dict, None] = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response = response


def generate_trace_id() -> str:
    """生成 64 字符十六进制全局唯一追踪 ID。"""
    return secrets.token_hex(32)


def get_api_key(cli_api_key: Optional[str]) -> str:
    """获取 API 密钥：优先 CLI 参数，其次环境变量。"""
    key = cli_api_key or os.environ.get("IWENCAI_API_KEY", "")
    if not key:
        raise APIError(
            "API 密钥未设置。请通过 --api-key 参数或环境变量 IWENCAI_API_KEY 指定。\n"
            "首次使用获取指引：打开 https://www.iwencai.com/skillhub → 登录 → 点击 Skill → "
            "安装方式-Agent用户-复制您的 IWENCAI_API_KEY。"
        )
    return key


def build_headers(api_key: str, trace_id: str, call_type: str = "normal") -> dict:
    """构造符合问财网关规范的请求头。"""
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "X-Claw-Call-Type": call_type,
        "X-Claw-Skill-Id": SKILL_NAME,
        "X-Claw-Skill-Version": SKILL_VERSION,
        "X-Claw-Plugin-Id": "none",
        "X-Claw-Plugin-Version": "none",
        "X-Claw-Trace-Id": trace_id,
    }


def query_market(
    query: str,
    page: str,
    limit: str,
    api_key: Optional[str],
    call_type: str = "normal",
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """
    调用行情数据查询接口。

    Args:
        query: 查询字符串
        page: 分页参数
        limit: 每页条数
        api_key: API 密钥
        call_type: 调用类型，normal 或 retry
        timeout: 请求超时时间（秒），默认 30

    Returns:
        包含 datas、code_count、chunks_info、trace_id、claw_headers 等字段的字典

    Raises:
        APIError: API 调用失败时抛出
    """
    api_key = get_api_key(api_key)
    api_url = DEFAULT_API_URL
    trace_id = generate_trace_id()

    payload = {
        "query": query,
        "page": page,
        "limit": limit,
        "is_cache": "1",
        "expand_index": "true",
    }

    headers = build_headers(api_key, trace_id, call_type)
    claw_headers = {k: v for k, v in headers.items() if k.startswith("X-Claw-")}
    request = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
            
            # 对响应内容进行类型判断和处理
            if not response_body.strip():
                # 空响应
                return {"text_response": "", "trace_id": trace_id, "claw_headers": claw_headers}
            
            try:
                # 尝试解析 JSON 响应
                parsed_response = json.loads(response_body)
                # 判断解析后的类型
                if isinstance(parsed_response, dict):
                    parsed_response["trace_id"] = trace_id
                    parsed_response["claw_headers"] = claw_headers
                    return parsed_response
                elif isinstance(parsed_response, list):
                    return {"data": parsed_response, "trace_id": trace_id, "claw_headers": claw_headers}
                else:
                    return {"text_response": str(parsed_response), "trace_id": trace_id, "claw_headers": claw_headers}
            except json.JSONDecodeError:
                # 如果解析失败，说明返回的是文本内容，直接返回文本
                return {"text_response": response_body, "trace_id": trace_id, "claw_headers": claw_headers}

    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else ""
        
        if error_body.strip():
            try:
                # 尝试解析错误响应为 JSON
                error_json = json.loads(error_body)
                raise APIError(
                    f"HTTP 错误 {e.code}: {e.reason}",
                    status_code=e.code,
                    response=error_json,
                )
            except json.JSONDecodeError:
                # 如果解析失败，说明返回的是文本内容，直接返回文本
                raise APIError(
                    f"HTTP 错误 {e.code}: {e.reason}",
                    status_code=e.code,
                    response=error_body,
                )
        else:
            # 空的错误响应
            raise APIError(
                f"HTTP 错误 {e.code}: {e.reason}",
                status_code=e.code,
                response="",
            )
    except urllib.error.URLError as e:
        raise APIError(f"网络错误: {e.reason}")


def parse_args():
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        description="问财行情数据 - 行情数据查询工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=f"""
使用示例:
  python3 scripts/cli.py --query "同花顺最新价格"
  python3 scripts/cli.py --query "主力资金流向"
  python3 scripts/cli.py --query "上证指数行情" --page "2" --limit "20"
  python3 scripts/cli.py --query "MACD金叉" --api-key "your-key"

环境变量:
  IWENCAI_API_KEY    API 密钥（必填，也可通过 --api-key 传入）
        """
    )

    parser.add_argument(
        "--query", "-q",
        type=str,
        required=True,
        help="查询字符串（必填）"
    )

    parser.add_argument(
        "--page",
        type=str,
        default=DEFAULT_PAGE,
        help=f"分页参数，值必须为正整数（默认: {DEFAULT_PAGE}）"
    )

    parser.add_argument(
        "--limit",
        type=str,
        default=DEFAULT_LIMIT,
        help=f"每页条数，值必须为正整数（默认: {DEFAULT_LIMIT}）"
    )

    parser.add_argument(
        "--api-key",
        type=str,
        default=None,
        help="API 密钥（默认从环境变量 IWENCAI_API_KEY 读取）"
    )

    parser.add_argument(
        "--call-type",
        type=str,
        choices=["normal", "retry"],
        default="normal",
        help="调用类型: normal（正常请求）或 retry（重试请求）（默认: normal）"
    )

    parser.add_argument(
        "--timeout",
        type=int,
        default=DEFAULT_TIMEOUT,
        help=f"请求超时时间，单位秒（默认: {DEFAULT_TIMEOUT}）"
    )

    args = parser.parse_args()

    # 校验 page 和 limit 为合法正整数字符串
    try:
        page_val = int(args.page)
        if page_val < 1:
            parser.error(f"--page 必须为正整数，当前值: {args.page}")
    except ValueError:
        parser.error(f"--page 必须为正整数，当前值: {args.page}")

    try:
        limit_val = int(args.limit)
        if limit_val < 1:
            parser.error(f"--limit 必须为正整数，当前值: {args.limit}")
    except ValueError:
        parser.error(f"--limit 必须为正整数，当前值: {args.limit}")

    return args


def main():
    """主函数"""
    args = parse_args()

    try:
        result = query_market(
            query=args.query,
            page=args.page,
            limit=args.limit,
            api_key=args.api_key,
            call_type=args.call_type,
            timeout=args.timeout,
        )

        if isinstance(result, dict) and "text_response" not in result:
            # 检查是否为正常的数据响应（必须包含 datas 字段）
            # 如果不包含 datas，可能是网关层返回的错误（如额度不足、查询次数超限等），
            # 直接透传网关原始响应，不做任何改写
            if "datas" not in result:
                print(json.dumps(result, ensure_ascii=False, indent=2))
                sys.exit(1)

            datas = result["datas"]
            code_count = int(result.get("code_count", 0))
            chunks_info = result.get("chunks_info", {})
            trace_id = result.get("trace_id", "")

            current_page = int(args.page)
            current_limit = int(args.limit)
            has_more = current_page * current_limit < code_count

            output = {
                "success": True,
                "query": args.query,
                "code_count": code_count,
                "returned_count": len(datas),
                "page": args.page,
                "limit": args.limit,
                "has_more": has_more,
                "chunks_info": chunks_info,
                "trace_id": trace_id,
                "datas": datas,
            }

            if has_more:
                output["pagination_tip"] = (
                    f"共查到 {code_count} 条数据，当前返回第 {args.page} 页的 {len(datas)} 条。"
                    f"如需更多数据，请使用 --page 参数翻页。"
                )

            # 空数据提示：当 datas 为空时，提示 agent 可放宽条件重试
            if not datas:
                output["empty_data_tip"] = (
                    "未查询到符合条件的数据。建议放宽或简化查询条件后重试"
                    "（使用 --call-type retry 标记重试请求）。"
                    "如仍无数据，可引导用户访问同花顺问财: https://www.iwencai.com/unifiedwap/chat"
                )

            print(json.dumps(output, ensure_ascii=False, indent=2))
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))

    except APIError as e:
        # 网关/API 返回的错误，尽量透传原始响应，不改写不淹没
        if isinstance(e.response, dict):
            # 网关返回 JSON 错误（如额度不足、次数超限等），直接输出原始 JSON
            gateway_output = dict(e.response)
            if e.status_code is not None:
                gateway_output.setdefault("status_code", e.status_code)
            print(json.dumps(gateway_output, ensure_ascii=False, indent=2))
        elif isinstance(e.response, str) and e.response.strip():
            # 网关返回纯文本错误，直接透传
            print(e.response)
        else:
            # 无响应体（网络错误、空错误等），输出结构化错误
            error_output = {"error": e.message}
            if e.status_code is not None:
                error_output["status_code"] = e.status_code
            print(json.dumps(error_output, ensure_ascii=False, indent=2))
        sys.exit(1)
    except KeyboardInterrupt:
        print("\n操作已取消。", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        error_output = {
            "error": f"发生错误: {str(e)}"
        }
        print(json.dumps(error_output, ensure_ascii=False, indent=2))
        sys.exit(1)


if __name__ == "__main__":
    main()
