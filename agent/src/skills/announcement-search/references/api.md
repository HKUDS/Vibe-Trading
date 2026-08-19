# Announcement Search API

## Overview

Search Chinese financial announcements through the Iwencai OpenAPI gateway. The client always searches the `announcement` channel.

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
| `channels` | list | yes | Fixed value: `["announcement"]` |
| `app_id` | string | yes | Fixed value: `AIME_SKILL` |
| `size` | integer | yes | Requested result count; default `10` |

Example:

```json
{
  "query": "latest Nvidia earnings news",
  "channels": ["announcement"],
  "app_id": "AIME_SKILL",
  "size": 10
}
```

## Response

The gateway raw response is expected to have `status_code` equal to `0` when successful, with announcement records under `data`.

Known announcement fields include:

| Name | Type | Description |
| --- | --- | --- |
| `title` | string | Announcement title |
| `summary` | string | Announcement summary |
| `url` | string | Announcement URL |
| `publish_time` | number | Announcement publish time |

Important: bundled code must return the original gateway response body unchanged. The agent may inspect and summarize fields after the raw body is returned.
