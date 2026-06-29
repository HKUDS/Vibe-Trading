"""invinoveritas ``/review`` advisory provider.

:class:`InvinoveritasAdvisory` calls the public invinoveritas ``/review``
endpoint — the verification layer for autonomous agents — to obtain an
*independent*, capital-scale-aware pre-trade verdict on a proposed order, and
returns it as an observational :class:`~src.live.advisory.AdvisoryResult`.

Two properties make this more than a second rule engine:

* **Independent.** The verdict comes from a party that is *not* the agent
  placing the order, so "is this wise?" is not graded by the same optimist that
  produced the order. ``/review`` with ``artifact_type="trade"`` triggers the
  capital-scale-aware risk-manager review (account equity, exposure, drawdown,
  position count).
* **Recomputable.** With ``sign=True`` (the default), ``/review`` returns a
  portable signed proof that any third party can verify against invinoveritas's
  published key via ``/verify-proof``, *without trusting this runtime*. The
  proof and its ``verify_url`` are carried in
  :attr:`AdvisoryResult.detail` so the gate's audit record
  (``gate_decision["advisory"]``) stays independently checkable after the fact.

Consistent with the advisory contract, every failure path **fails open**: a
missing credit/payment, a timeout, a network error, a non-2xx response, or an
unparseable body all resolve to :attr:`Verdict.REVIEW_UNAVAILABLE`, so an
advisory outage never blocks order execution.

Example::

    from src.live.advisory import register_advisory_provider
    from src.live.advisory.invinoveritas import InvinoveritasAdvisory

    register_advisory_provider(InvinoveritasAdvisory(api_key="ivk_..."))
"""

from __future__ import annotations

import logging
import os
from typing import Any

import httpx

from src.live.advisory import (
    AdvisoryContext,
    AdvisoryResult,
    PreTradeAdvisoryInterface,
    Verdict,
)

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://api.babyblueviper.com"
DEFAULT_TIMEOUT_S = 8.0

# Map the /review verdict vocabulary onto the local advisory Verdict enum.
# /review can return "revise" (a soft "tighten this before shipping"); it is a
# concern, not a hard reject, so it maps to APPROVE_WITH_CONCERNS.
_VERDICT_MAP: dict[str, Verdict] = {
    "approve": Verdict.APPROVE,
    "approve_with_concerns": Verdict.APPROVE_WITH_CONCERNS,
    "revise": Verdict.APPROVE_WITH_CONCERNS,
    "reject": Verdict.REJECT,
}


class InvinoveritasAdvisory(PreTradeAdvisoryInterface):
    """Pre-trade advisory provider backed by invinoveritas ``/review``.

    Args:
        api_key: Optional bearer token for a funded invinoveritas account. When
            omitted, the call falls back to the ``INVINOVERITAS_API_KEY``
            environment variable. ``/review`` is a paid endpoint; without usable
            credit the call resolves to :attr:`Verdict.REVIEW_UNAVAILABLE`
            (fail-open) rather than raising.
        base_url: API base URL (defaults to the public deployment, or the
            ``INVINOVERITAS_BASE_URL`` environment variable).
        timeout_s: Per-request timeout in seconds. On timeout the provider fails
            open to :attr:`Verdict.REVIEW_UNAVAILABLE`.
        sign: Request a portable signed proof on each verdict (default
            ``True``). The proof is stored in :attr:`AdvisoryResult.detail`.
        client: Optional pre-constructed :class:`httpx.Client` (primarily for
            tests / connection reuse). When omitted, a client is created per
            call and closed afterwards.
        provider_id: Identifier stamped onto every result.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        sign: bool = True,
        client: httpx.Client | None = None,
        provider_id: str = "invinoveritas",
    ) -> None:
        self._api_key = api_key or os.getenv("INVINOVERITAS_API_KEY")
        self._base_url = (base_url or os.getenv("INVINOVERITAS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        self._timeout_s = timeout_s
        self._sign = sign
        self._client = client
        self._provider_id = provider_id

    @property
    def provider_id(self) -> str:
        """Unique identifier for this advisory provider."""
        return self._provider_id

    def review(self, context: AdvisoryContext) -> AdvisoryResult:
        """Obtain an independent ``/review`` verdict for *context*.

        Args:
            context: Normalized pre-trade context.

        Returns:
            An :class:`AdvisoryResult`. Any failure (no credit, timeout, network
            error, non-2xx response, or unparseable body) resolves to
            :attr:`Verdict.REVIEW_UNAVAILABLE` so the order is never blocked.
        """
        payload = {
            "artifact": self._build_artifact(context),
            "artifact_type": "trade",
            "context": self._build_context(context)[:4000],
            "concerns": (
                "capital-scale soundness, over-concentration, drawdown sensitivity, position sizing"
            ),
            "sign": self._sign,
        }
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        try:
            response = self._post(payload, headers)
        except httpx.TimeoutException:
            return self._unavailable("/review timed out")
        except httpx.HTTPError as exc:
            return self._unavailable(f"/review request error: {type(exc).__name__}")

        if response.status_code == 402:
            # Payment required: no usable credit/payment. Observational → fail open.
            return self._unavailable("/review requires payment (configure a funded api_key)")
        if response.status_code != 200:
            return self._unavailable(f"/review returned HTTP {response.status_code}")

        try:
            body = response.json()
        except ValueError:
            return self._unavailable("/review returned an unparseable body")

        return self._to_result(body)

    # -- internals -----------------------------------------------------------

    def _post(self, payload: dict[str, Any], headers: dict[str, str]) -> httpx.Response:
        """POST *payload* to ``/review``, reusing an injected client if present."""
        url = f"{self._base_url}/review"
        if self._client is not None:
            return self._client.post(url, json=payload, headers=headers, timeout=self._timeout_s)
        with httpx.Client(timeout=self._timeout_s) as client:
            return client.post(url, json=payload, headers=headers)

    def _to_result(self, body: dict[str, Any]) -> AdvisoryResult:
        """Translate a ``/review`` response body into an :class:`AdvisoryResult`."""
        raw_verdict = str(body.get("verdict") or "").lower()
        verdict = _VERDICT_MAP.get(raw_verdict)
        if verdict is None:
            # Unknown/absent verdict — do not guess; surface as unavailable.
            return self._unavailable(f"/review returned an unrecognized verdict: {raw_verdict!r}")

        issues = body.get("issues") or []
        concerns = tuple(
            f"[{(issue.get('severity') or '?')}] {issue.get('title') or issue.get('detail') or ''}".strip()
            for issue in issues
            if isinstance(issue, dict)
        )
        proof = body.get("proof") or {}
        detail: dict[str, Any] = {
            "review_verdict": raw_verdict,
            "issues": issues,
        }
        if proof:
            detail["proof"] = proof
            verify_url = proof.get("verify_url")
            if verify_url:
                detail["verify_url"] = verify_url

        confidence = body.get("confidence")
        return AdvisoryResult(
            verdict=verdict,
            confidence=float(confidence) if isinstance(confidence, (int, float)) else None,
            summary=str(body.get("summary") or ""),
            concerns=concerns,
            provider=self._provider_id,
            detail=detail,
        )

    def _unavailable(self, summary: str) -> AdvisoryResult:
        """Build a fail-open :attr:`Verdict.REVIEW_UNAVAILABLE` result."""
        logger.warning("invinoveritas advisory unavailable: %s", summary)
        return AdvisoryResult(
            verdict=Verdict.REVIEW_UNAVAILABLE,
            summary=summary,
            provider=self._provider_id,
        )

    @staticmethod
    def _build_artifact(context: AdvisoryContext) -> str:
        """Render the proposed order as the artifact under review."""
        return (
            f"Proposed order: {context.side.upper()} {context.symbol} "
            f"for ${context.notional_usd:,.2f} notional."
        )

    @staticmethod
    def _build_context(context: AdvisoryContext) -> str:
        """Render the account state that makes the verdict capital-scale-aware."""
        return (
            f"Account equity ${context.account_equity:,.2f}; "
            f"committed funding ${context.funding_usd:,.2f}; "
            f"funding utilization {context.utilization_ratio:.0%}; "
            f"{context.open_position_count} open position(s); "
            f"total open exposure ${context.total_exposure_usd:,.2f}. "
            "Is this specific order sound right now given the account state and scale?"
        )
