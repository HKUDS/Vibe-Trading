# News Search API

## Overview

Search Chinese finance-focused news through the Iwencai OpenAPI gateway. The client always searches the `news` channel.

## Endpoint

| Field | Value |
| --- | --- |
| Base URL | `https://openapi.iwencai.com` |
| Path | `/v1/comprehensive/search` |
| Method | `POST` |
| Auth | `Authorization: Bearer <IWENCAI_API_KEY>` |

## Request Body

| Name | Type | Required | Description |
| --- | --- | --- | --- |
| `query` | string | yes | User query |
| `channels` | list | yes | Fixed value: `["news"]` |
| `app_id` | string | yes | Fixed value: `AIME_SKILL` |
| `size` | integer | yes | Requested result count; default `10` |

Example:

```json
{
  "query": "贵州茅台今日新闻",
  "channels": ["news"],
  "app_id": "AIME_SKILL",
  "size": 10
}
```

## Response

The gateway raw response is expected to have `status_code` equal to `0` when successful, with news records under `data`.

Known news fields include:

| Name | Type | Description |
| --- | --- | --- |
| `title` | string | News title |
| `summary` | string | News summary |
| `url` | string | News URL |
| `publish_time` | number | News publish time |

Important: bundled code must return the original gateway response body unchanged. The agent may inspect and summarize fields after the raw body is returned.
