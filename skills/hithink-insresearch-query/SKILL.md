---
name: hithink-insresearch-query
description: 查询研报评级、业绩预测、ESG、信用评级、主体评级、基金评级、券商金股等机构观点数据，支持自然语言问句输入，返回相关机构研究数据结果。当用户询问研报评级、业绩预测、ESG评级、信用评级、主体评级、基金评级、券商金股等机构研究数据查询问题时，必须使用此技能。
license: Complete terms in LICENSE.txt
---

# 问财机构研究与评级 使用指南

## 版本

`1.0.0`（与 `X-Claw-Skill-Version` 保持一致）

## 技能概述

本技能提供机构研究与评级查询能力，支持：
- **研报评级**：券商研报、投资评级等
- **业绩预测**：盈利预测、业绩展望等
- **ESG 评级**：环境、社会、治理评分
- **信用评级**：企业信用评级
- **主体评级**：发行人评级
- **基金评级**：基金评级、星级评定
- **券商金股**：券商推荐金股
- 支持自然语言问句输入，返回相关机构研究数据结果

数据来源：**同花顺问财**（https://www.iwencai.com/unifiedwap/chat）

## 使用前

> 首次使用 - 获取 API Key
> 所有技能都需要 IWENCAI_API_KEY 环境变量才能使用。 如果用户尚未配置，按以下步骤引导：
>
> 步骤 1：获取 API Key
> 在浏览器内打开同花顺i问财SkillHub页面：https://www.iwencai.com/skillhub
>
> 步骤 2：登录
>
> 步骤 3：点击具体的Skill，打开弹窗查看详情，在安装方式-Agent用户-找到您的IWENCAI_API_KEY这一段，复制
>
> 步骤 4：配置环境变量
> 获取到 API Key 后，直接复制指引文字发送给AI助手，或手动设置环境变量：

### 跨平台环境变量设置

**macOS / Linux (bash / zsh):**
```bash
export IWENCAI_API_KEY="your-api-key"
```

**Windows (PowerShell):**
```powershell
$env:IWENCAI_API_KEY="your-api-key"
```

**Windows (CMD):**
```cmd
set IWENCAI_API_KEY=your-api-key
```

## 核心处理流程

### 步骤 1: 接收用户 Query

接收用户的自然语言查询请求，分析用户意图，识别机构研究数据相关查询类型：
- 研报评级/业绩预测查询
- ESG/信用评级查询
- 基金评级/券商金股查询

### 步骤 2: Query 改写

将用户问句适当改写为标准的金融查询问句，保持原意不变：

**改写规则：**
- 保留用户核心意图（如：研报评级、业绩预测、ESG评级等）
- 将口语化表达转为标准金融术语
- 适当简化过于复杂的复合条件
- 改写后需保持原意不变

**常用查询改写示例：**
| 用户原始问句 | 改写后查询 |
|-------------|-----------|
| 同花顺研报评级怎么样 | 同花顺研报评级 |
| 今年业绩预测如何 | 业绩预测 |
| 有哪些券商金股 | 券商金股 |
| ESG评级高的公司 | ESG评级高的股票 |

### 步骤 3: API 调用

调用问财 OpenAPI 网关获取数据，使用 `scripts/cli.py` CLI 或直接在 skill 逻辑中构造 HTTP 请求。所有发往网关的请求必须严格携带以下 Header：

| Header | 取值说明 |
|--------|----------|
| `Authorization` | `Bearer <API Key>`，API Key 仅从环境变量 `IWENCAI_API_KEY` 读取 |
| `Content-Type` | `application/json` |
| `X-Claw-Call-Type` | `normal`（正常请求）或 `retry`（失败后的重试） |
| `X-Claw-Skill-Id` | `hithink-insresearch-query`（与 skill name 一致） |
| `X-Claw-Skill-Version` | `1.0.0`（与本文档版本一致） |
| `X-Claw-Plugin-Id` | `none` |
| `X-Claw-Plugin-Version` | `none` |
| `X-Claw-Trace-Id` | 每次请求必须新生成的 **64 字符**全局唯一追踪 ID（推荐 `secrets.token_hex(32)`） |

**请求体示例：**
```json
{
  "query": "改写后的查询语句",
  "page": "1",
  "limit": "10",
  "is_cache": "1",
  "expand_index": "true"
}
```

**Python 调用示例（含 Claw Headers）：**
```python
import os
import json
import secrets
import urllib.request

url = "https://openapi.iwencai.com/v1/query2data"
api_key = os.environ["IWENCAI_API_KEY"]
trace_id = secrets.token_hex(32)  # 64 字符唯一 ID

payload = {
    "query": "同花顺研报评级",
    "page": "1",
    "limit": "10",
    "is_cache": "1",
    "expand_index": "true"
}

headers = {
    "Authorization": f"Bearer {api_key}",
    "Content-Type": "application/json",
    "X-Claw-Call-Type": "normal",
    "X-Claw-Skill-Id": "hithink-insresearch-query",
    "X-Claw-Skill-Version": "1.0.0",
    "X-Claw-Plugin-Id": "none",
    "X-Claw-Plugin-Version": "none",
    "X-Claw-Trace-Id": trace_id,
}

data = json.dumps(payload).encode("utf-8")
request = urllib.request.Request(url, data=data, headers=headers, method="POST")
response = urllib.request.urlopen(request, timeout=30)
result = json.loads(response.read().decode("utf-8"))

# 解析返回数据
datas = result.get("datas", [])           # 当前页数据列表
code_count = result.get("code_count", 0)  # 符合条件的总记录数
chunks_info = result.get("chunks_info", {})  # 查询字句信息

# 分页提示：如果 code_count > len(datas)，通过增加 page 参数翻页
```

**注意：** 默认返回 10 条数据，但符合条件的总数可能更多，需关注 `code_count` 字段并通过分页获取全部数据。

### 步骤 4: 空数据处理

如果 `datas` 为空或无数据，适当放宽或简化查询条件后重新请求（**最多尝试 2 次**）：

- **首次重试**：去掉过于苛刻的条件，保留核心查询条件
- **二次重试**：进一步放宽条件或使用更通用的表述

每次重试都算作一次改写，最终返回时需说明最终使用的查询问句。

### 步骤 5: 数据解析

解析返回的 `datas` 数组，提取相关指标：

```python
for item in datas:
    code = item.get("股票代码")       # 如 "300033.SZ"
    name = item.get("股票简称")       # 如 "同花顺"
    # 其他字段根据查询类型而定，如评级类型、评级机构、评级日期等
```

### 步骤 6: 数据扩展决策

skill 需要自行决策当前数据是否足够回答用户问题：
- 如果数据完整：直接返回格式化后的结果且保证表格数据正确解析为表格展示
- 如果需要更多背景信息：可以调用其他金融工具或者搜索工具获取相关资讯

### 步骤 7: 回答用户

组织语言回答用户问题，确保：
- 结果清晰易懂
- 如果改写了问句，需特别说明最终使用的查询问句
- **必须强调数据来源于同花顺问财**

## 请求参数

| 参数名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| query | STRING | 是 | 用户问句 |
| page | STRING | 否 | 分页参数，默认值：1 |
| limit | STRING | 否 | 分页参数，默认值：10 |
| is_cache | STRING | 否 | 缓存参数，默认值：1 |
| expand_index | STRING | 否 | 是否展开指数，默认值：true |

## 响应参数

| 参数名 | 类型 | 说明 |
|--------|------|------|
| datas | ARRAY | 金融数据列表，对象数组，每个对象包含股票代码、股票简称、评级类型、评级机构等字段 |
| code_count | INT | 符合查询条件的总记录数量（注意：可能大于当前返回的 datas 条数） |
| chunks_info | OBJECT | 用户问句查询返回的字句信息，包含查询条件的解析结果 |

**响应示例：**
```json
{
  "datas": [
    {"股票代码": "300033.SZ", "股票简称": "同花顺", "评级类型": "买入", "评级机构": "某券商研究所"}
  ],
  "code_count": 125,
  "chunks_info": {
    "query": "同花顺研报评级",
    "parsed_conditions": ["同花顺", "研报评级"]
  }
}
```

**重要提示：**
- `datas` 默认只返回 10 条数据（可通过 `limit` 参数调整）
- `code_count` 表示符合条件的总记录数，可能远大于 `datas` 的长度
- 当 `code_count > len(datas)` 时，需要通过 `page` 参数翻页获取更多数据
- 返回的表格数据需要解析 `datas` 数组中的对象字段

## CLI 使用方式

本 skill 提供跨平台 CLI 脚本 `scripts/cli.py`，基于 Python 3 标准库实现，无第三方依赖。

### 命令行参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `--query` | STRING | 是 | 直接传入查询字符串 |
| `--page` | STRING | 否 | 分页参数，值必须为正整数，默认值：1 |
| `--limit` | STRING | 否 | 每页条数，值必须为正整数，默认值：10 |
| `--api-key` | STRING | 否 | API 密钥（默认从环境变量读取）|
| `--call-type` | STRING | 否 | 调用类型：`normal`（正常请求）或 `retry`（重试请求），默认值：normal |
| `--timeout` | INT | 否 | 请求超时时间（秒），默认值：30 |

### 使用示例

```bash
# 查询研报评级
python3 scripts/cli.py --query "同花顺研报评级"

# 查询业绩预测
python3 scripts/cli.py --query "业绩预测"

# 查询券商金股
python3 scripts/cli.py --query "券商金股"

# 翻页查询
python3 scripts/cli.py --query "研报评级" --page 2 --limit 20

# 重试请求（放宽条件后使用 retry 标记）
python3 scripts/cli.py --query "同花顺研报评级" --call-type "retry"

# 指定超时时间（复杂查询可适当增加）
python3 scripts/cli.py --query "同花顺研报评级" --timeout 60
```

### curl 示例（脱敏）

```bash
curl -X POST "https://openapi.iwencai.com/v1/query2data" \
  -H "Authorization: Bearer $IWENCAI_API_KEY" \
  -H "Content-Type: application/json" \
  -H "X-Claw-Call-Type: normal" \
  -H "X-Claw-Skill-Id: hithink-insresearch-query" \
  -H "X-Claw-Skill-Version: 1.0.0" \
  -H "X-Claw-Plugin-Id: none" \
  -H "X-Claw-Plugin-Version: none" \
  -H "X-Claw-Trace-Id: $(openssl rand -hex 32)" \
  -d '{
    "query": "同花顺研报评级",
    "page": "1",
    "limit": "10",
    "is_cache": "1",
    "expand_index": "true"
  }'
```

**Windows (PowerShell) 等价示例：**
```powershell
$bytes = New-Object byte[] 32; [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes); $traceId = -join ($bytes | ForEach-Object { $_.ToString("x2") })
Invoke-RestMethod -Uri "https://openapi.iwencai.com/v1/query2data" -Method POST -Headers @{
  "Authorization" = "Bearer $env:IWENCAI_API_KEY"
  "Content-Type" = "application/json"
  "X-Claw-Call-Type" = "normal"
  "X-Claw-Skill-Id" = "hithink-insresearch-query"
  "X-Claw-Skill-Version" = "1.0.0"
  "X-Claw-Plugin-Id" = "none"
  "X-Claw-Plugin-Version" = "none"
  "X-Claw-Trace-Id" = $traceId
} -Body '{"query":"同花顺研报评级","page":"1","limit":"10","is_cache":"1","expand_index":"true"}'
```

## 数据来源标注

**重要提示**：
- 引用同花顺数据时，必须强调**数据来源于同花顺问财**（https://www.iwencai.com/unifiedwap/chat）
- 如果没有查询到数据，提示用户可以到**同花顺问财 web端**查询（https://www.iwencai.com/unifiedwap/chat）

## 错误处理

- **密钥缺失（环境变量未设置且未传 `--api-key`）**：
  代理必须**口头提示**用户「使用前」中的完整 API Key 获取指引文案，即：
  > 首次使用 - 获取 API Key
  > 所有技能都需要 IWENCAI_API_KEY 环境变量才能使用。 如果用户尚未配置，按以下步骤引导：
  >
  > 步骤 1：获取 API Key
  > 在浏览器内打开同花顺i问财SkillHub页面：https://www.iwencai.com/skillhub
  >
  > 步骤 2：登录
  >
  > 步骤 3：点击具体的Skill，打开弹窗查看详情，在安装方式-Agent用户-找到您的IWENCAI_API_KEY这一段，复制
  >
  > 步骤 4：配置环境变量
  > 获取到 API Key 后，直接复制指引文字发送给AI助手，或手动设置环境变量：

- **无数据返回**：引导用户访问同花顺问财（https://www.iwencai.com/unifiedwap/chat）。

- **最多重试 2 次**逐步放宽条件（重试时 `X-Claw-Call-Type` 改为 `retry`）。

## 代码结构

```
hithink-insresearch-query/
├── SKILL.md              # Skill 配置文件
├── LICENSE.txt           # 许可证文件
└── scripts/
    └── cli.py            # CLI 入口（单一脚本，内含 API 调用和数据处理）
```
