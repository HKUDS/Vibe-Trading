---
name: news-search
description: 财经领域为主的资讯搜索引擎，囊获了各类型媒体：官媒、主流财经媒体、垂直行业网站、知名上市公司/非上市公司官网等，可以帮助你了解最新财经事件、政策动态、行业革新、企业业务进展等等。
---

# News Search

Finance-focused Chinese news search through the Iwencai OpenAPI gateway. Use this skill to turn a user's news question into one or more concise search queries, call the news search API, inspect the raw returned data, and answer with the data source stated as 同花顺问财.

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
2. Understand the user's need and create one concise query for each distinct topic, company, policy, industry, or time window. Do not reveal chain-of-thought; only use the resulting query or query list.
3. Call `scripts/news_search.py` once per query. The script sends POST requests and prints the gateway response body unchanged.
4. Inspect the raw response returned by the gateway. If the retrieved data is insufficient, run another focused query or use other available tools/skills when appropriate.
5. Answer the user from the raw data and state `数据来源：同花顺问财`. Prefer newer news when the user asks for latest, today, recent, or current developments.

## CLI

Single query:

```bash
python scripts/news_search.py "贵州茅台今日新闻" --size 10
```

Windows:

```powershell
py -3 scripts\news_search.py "贵州茅台今日新闻" --size 10
```

Save the raw response body unchanged:

```bash
python scripts/news_search.py "人工智能产业政策 最新消息" --size 5 --output raw-news-response.json
```

Options:

- `query`: required natural-language news search query.
- `--size`: result count requested from the API; default `10`.
- `--base-url`: optional override, default `https://openapi.iwencai.com`.
- `--endpoint`: optional override, default `/v1/comprehensive/search`.
- `--timeout`: HTTP timeout in seconds, default `30`.
- `--output`: write the raw response body unchanged to a file instead of stdout.

## Gateway Contract

The script always sends:

- Method: `POST`
- Endpoint: `/v1/comprehensive/search`
- Body: `{"query": <query>, "channels": ["news"], "app_id": "AIME_SKILL", "size": <size>}`
- Auth: `Authorization: Bearer <IWENCAI_API_KEY>` from environment only
- Claw headers:
  - `X-Claw-Call-Type: normal`
  - `X-Claw-Skill-Id: news-search`
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
  -H "X-Claw-Skill-Id: news-search" \
  -H "X-Claw-Skill-Version: 1.0.0" \
  -H "X-Claw-Plugin-Id: none" \
  -H "X-Claw-Plugin-Version: none" \
  -H "X-Claw-Trace-Id: ${TRACE_ID}" \
  -d '{"query":"贵州茅台今日新闻","channels":["news"],"app_id":"AIME_SKILL","size":10}'
```

PowerShell:

```powershell
$traceId = py -3 -c "import secrets; print(secrets.token_hex(32))"
curl.exe -X POST "https://openapi.iwencai.com/v1/comprehensive/search" `
  -H "Content-Type: application/json" `
  -H "Authorization: Bearer $env:IWENCAI_API_KEY" `
  -H "X-Claw-Call-Type: normal" `
  -H "X-Claw-Skill-Id: news-search" `
  -H "X-Claw-Skill-Version: 1.0.0" `
  -H "X-Claw-Plugin-Id: none" `
  -H "X-Claw-Plugin-Version: none" `
  -H "X-Claw-Trace-Id: $traceId" `
  -d '{\"query\":\"贵州茅台今日新闻\",\"channels\":[\"news\"],\"app_id\":\"AIME_SKILL\",\"size\":10}'
```

## References

- API details: `references/api.md`
- Gateway CLI: `scripts/news_search.py`
