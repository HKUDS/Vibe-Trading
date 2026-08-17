---
name: announcement-search
description: 支持A股、港股、基金、ETF等金融标的公告的查询，同时公告类型包括不限于定期财务报告、分红派息、回购增持、资产重组等等。
---

# Announcement Search

Financial announcement search through the Iwencai OpenAPI gateway. Use this skill to turn a user's announcement question into one or more concise search queries, call the announcement search API, inspect the raw returned data, and answer with the data source stated as 同花顺问财.

## 使用前

> 首次使用 - 获取 API Key  
> 所有技能都需要 IWENCAI_API_KEY 环境变量才能使用。 如果用户尚未配置，按以下步骤引导：  
>  
> 步骤 1：获取 API Key  
> 在浏览器内打同花顺i问财SkillHub页面：https://www.iwencai.com/skillhub  
>  
> 步骤 2：登录  
>  
> 步骤 3：点击具体的Skill，打开弹窗查看详情，在安装方式-Agent用户-找到您的IWENCAI_API_KEY这一段，复制  
>  
> 步骤 4：配置环境变量  
> 获取到 API Key 后，直接复制指引文字发送给AI助手，或手动设置环境变量：

Environment variable examples:

```powershell
$env:IWENCAI_API_KEY="your_api_key_here"
```

```cmd
set IWENCAI_API_KEY=your_api_key_here
```

```bash
export IWENCAI_API_KEY="your_api_key_here"
```

## 版本

- Skill version: `1.0.0`
- `X-Claw-Skill-Version`: `1.0.0`

## Workflow

1. Check that `IWENCAI_API_KEY` is available. If it is missing or authentication fails, explicitly show the fixed notice in `## 使用前`.
2. Understand the user's need and create one concise Chinese or user-language query for each distinct target or announcement type. Do not reveal chain-of-thought; only use the resulting query or query list.
3. Call `scripts/announcement_search.py` once per query. The script sends POST requests and prints the gateway response body unchanged.
4. Inspect the raw response returned by the gateway. If one query is insufficient, run another focused query or use other available tools/skills when appropriate.
5. Answer the user from the raw data and state `数据来源：同花顺问财`. Prefer newer announcements when the user asks for latest or recent information.

## CLI

Single query:

```bash
python scripts/announcement_search.py "贵州茅台 分红公告" --size 10
```

Windows:

```powershell
py -3 scripts\announcement_search.py "贵州茅台 分红公告" --size 10
```

Save the raw response body unchanged:

```bash
python scripts/announcement_search.py "上市公司业绩预告" --size 5 --output raw-response.json
```

Options:

- `query`: required natural-language search query.
- `--size`: result count requested from the API; default `10`.
- `--base-url`: optional override, default `https://openapi.iwencai.com`.
- `--endpoint`: optional override, default `/v1/comprehensive/search`.
- `--timeout`: HTTP timeout in seconds, default `30`.
- `--output`: write the raw response body unchanged to a file instead of stdout.

## Gateway Contract

The script always sends:

- Method: `POST`
- Endpoint: `/v1/comprehensive/search`
- Body: `{"query": <query>, "channels": ["announcement"], "app_id": "AIME_SKILL", "size": <size>}`
- Auth: `Authorization: Bearer <IWENCAI_API_KEY>` from environment only
- Claw headers:
  - `X-Claw-Call-Type: normal`
  - `X-Claw-Skill-Id: announcement-search`
  - `X-Claw-Skill-Version: 1.0.0`
  - `X-Claw-Plugin-Id: none`
  - `X-Claw-Plugin-Version: none`
  - `X-Claw-Trace-Id: <fresh 64-character hex string per request>`

The Python client must transparently pass through the gateway response body. Do not add, delete, map, filter, format, or wrap API response fields in the script. Any interpretation happens after the raw body is returned to the agent.

## Redacted Curl

Unix-like shells:

```bash
TRACE_ID="$(python3 -c 'import secrets; print(secrets.token_hex(32))')"
curl -X POST "https://openapi.iwencai.com/v1/comprehensive/search" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer ${IWENCAI_API_KEY}" \
  -H "X-Claw-Call-Type: normal" \
  -H "X-Claw-Skill-Id: announcement-search" \
  -H "X-Claw-Skill-Version: 1.0.0" \
  -H "X-Claw-Plugin-Id: none" \
  -H "X-Claw-Plugin-Version: none" \
  -H "X-Claw-Trace-Id: ${TRACE_ID}" \
  -d '{"query":"贵州茅台 分红公告","channels":["announcement"],"app_id":"AIME_SKILL","size":10}'
```

PowerShell:

```powershell
$traceId = py -3 -c "import secrets; print(secrets.token_hex(32))"
curl.exe -X POST "https://openapi.iwencai.com/v1/comprehensive/search" `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer $env:IWENCAI_API_KEY" `
  -H "X-Claw-Call-Type: normal" `
  -H "X-Claw-Skill-Id: announcement-search" `
  -H "X-Claw-Skill-Version: 1.0.0" `
  -H "X-Claw-Plugin-Id: none" `
  -H "X-Claw-Plugin-Version: none" `
  -H "X-Claw-Trace-Id: $traceId" `
  -d '{\"query\":\"贵州茅台 分红公告\",\"channels\":[\"announcement\"],\"app_id\":\"AIME_SKILL\",\"size\":10}'
```

## References

- API details: `references/api.md`
- Gateway CLI: `scripts/announcement_search.py`
