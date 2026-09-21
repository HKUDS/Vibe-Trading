"""Read-only Asistente Casa investor-policy bridge for the Vibe agent."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.agent.tools import BaseTool
from src.config.accessor import get_env_value

_TIMEOUT_SECONDS = 10.0
_EXPECTED_SCHEMA = "asistente-casa.investor-policy.v1"


class AsistenteCasaInvestorPolicyTool(BaseTool):
    """Return the active strategic allocation policy maintained by Asistente Casa."""

    name = "asistente_casa_investor_policy"
    description = (
        "Read the user's active investor allocation policy from Asistente Casa, the "
        "canonical source of portfolio policy. Use this tool whenever the user asks "
        "about investor profile, allocation targets, minimum/maximum ranges, sector/"
        "country/currency/asset-class limits, concentration limits, or whether the "
        "current portfolio is outside its strategic policy. Never infer policy limits "
        "from observed holdings. Returns the versioned policy contract including "
        "base_profile_id, tactical_profile_id and target/min/max rows. This tool is "
        "strictly read-only and never places orders or rebalances the portfolio."
    )
    parameters = {"type": "object", "properties": {}, "required": []}
    repeatable = True
    is_readonly = True

    @staticmethod
    def _settings() -> tuple[str, str]:
        base_url = str(get_env_value("ASISTENTE_CASA_BASE_URL") or "").strip().rstrip("/")
        api_key = str(get_env_value("ASISTENTE_CASA_API_KEY") or "").strip()
        if not base_url:
            raise RuntimeError("ASISTENTE_CASA_BASE_URL is not configured")
        if not api_key:
            raise RuntimeError("ASISTENTE_CASA_API_KEY is not configured")
        return base_url, api_key

    @classmethod
    def _fetch_policy(cls) -> dict[str, Any]:
        base_url, api_key = cls._settings()
        request = Request(
            f"{base_url}/inversiones/vibe/investor-policy",
            headers={"Accept": "application/json", "X-Vibe-API-Key": api_key},
            method="GET",
        )
        try:
            with urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
                raw = response.read().decode("utf-8")
        except HTTPError as exc:
            raise RuntimeError(f"Asistente Casa investor policy returned HTTP {exc.code}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise RuntimeError(f"Asistente Casa investor policy is unavailable: {exc}") from exc

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError("Asistente Casa investor policy returned invalid JSON") from exc

        if not isinstance(payload, dict):
            raise RuntimeError("Asistente Casa investor policy must be a JSON object")
        if payload.get("schema") != _EXPECTED_SCHEMA:
            raise RuntimeError(
                f"unexpected investor policy schema: {payload.get('schema')!r}; "
                f"expected {_EXPECTED_SCHEMA!r}"
            )
        if payload.get("base_profile_id") is None:
            raise RuntimeError("Asistente Casa investor policy has no active base profile")
        targets = payload.get("targets")
        if not isinstance(targets, list) or not targets:
            raise RuntimeError("Asistente Casa investor policy targets are missing")

        required = {"dimension", "item_key", "target_pct", "min_pct", "max_pct"}
        for index, row in enumerate(targets):
            if not isinstance(row, dict):
                raise RuntimeError(f"investor policy target {index} must be an object")
            missing = sorted(required - set(row))
            if missing:
                raise RuntimeError(
                    f"investor policy target {index} missing fields: {', '.join(missing)}"
                )
        return payload

    def execute(self, **_: Any) -> str:
        policy = self._fetch_policy()
        return json.dumps(
            {
                "status": "ok",
                "source": "asistente-casa",
                "policy": policy,
            },
            ensure_ascii=False,
        )
