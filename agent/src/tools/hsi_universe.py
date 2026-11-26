"""Current HSI constituents for a deliberately survivorship-biased benchmark."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import io
import logging
import re

import pandas as pd
import requests


LOG = logging.getLogger(__name__)
WIKIPEDIA_URL = "https://en.wikipedia.org/wiki/Hang_Seng_Index"
# Dated 95-member audit reference retained on 2026-11-04 from the review below.
# It is never a benchmark fallback, PIT history or indefinitely current list.
REFERENCE_SNAPSHOT_DATE = "2026-11-04"
# Official reference: the review announced on 2026-08-21, effective 2026-09-07.
# This frozen set is an audit reference, not an indefinitely current index list.
REFERENCE_EFFECTIVE_DATE = "2026-09-07"
PUBLISHED_CONSTITUENT_COUNT = 95  # Appendix 1 of the dated official review below.
REFERENCE_SOURCE_URL = "https://www.hsi.com.hk/static/uploads/contents/en/news/pressRelease/20260821T174500.pdf"
REFERENCE_CODES = """
0001.HK 0002.HK 0003.HK 0005.HK 0006.HK 0012.HK 0016.HK 0027.HK 0066.HK
0101.HK 0175.HK 0241.HK 0267.HK 0285.HK 0288.HK 0291.HK 0300.HK 0316.HK
0322.HK 0386.HK 0388.HK 0669.HK 0688.HK 0700.HK 0728.HK 0762.HK 0823.HK
0836.HK 0857.HK 0868.HK 0883.HK 0939.HK 0941.HK 0960.HK 0968.HK 0981.HK
0992.HK 1024.HK 1038.HK 1044.HK 1088.HK 1093.HK 1099.HK 1109.HK 1113.HK
1177.HK 1209.HK 1211.HK 1299.HK 1347.HK 1378.HK 1398.HK 1519.HK 1801.HK
1810.HK 1876.HK 1928.HK 1929.HK 1997.HK 2015.HK 2020.HK 2057.HK 2269.HK
2313.HK 2318.HK 2319.HK 2331.HK 2338.HK 2359.HK 2382.HK 2388.HK 2600.HK
2618.HK 2628.HK 2688.HK 2899.HK 3690.HK 3692.HK 3750.HK 3968.HK 3988.HK
3993.HK 6160.HK 6181.HK 6618.HK 6690.HK 6862.HK 9618.HK 9633.HK 9888.HK
9901.HK 9961.HK 9988.HK 9992.HK 9999.HK
""".split()


def normalize_hk_symbol(code: str) -> str:
    """Normalize HK aliases within the HSI adapter; leave shared loaders unchanged."""
    digits = str(code).strip().upper().removeprefix("HK.").removesuffix(".HK")
    if not digits.isascii() or not digits.isdigit() or not 0 < int(digits) < 100000:
        raise ValueError("Invalid Hong Kong equity symbol")
    return f"{int(digits):04d}.HK"


def _with_reference_metadata(codes: list[str], metadata: dict) -> dict:
    """Disclose set differences against the dated reference without changing codes."""
    observed, reference = set(codes), set(REFERENCE_CODES)
    missing = sorted(reference - observed)
    unexpected = sorted(observed - reference)
    matches = not missing and not unexpected
    if not matches:
        LOG.warning(
            "HSI roster differs from frozen %s reference: %d missing, %d unexpected; "
            "review both sources before treating either as current",
            REFERENCE_SNAPSHOT_DATE,
            len(missing),
            len(unexpected),
        )
    return {
        **metadata,
        "constituent_observed_count": len(observed),
        "constituent_reference_source": REFERENCE_SOURCE_URL,
        "constituent_reference_effective_date": REFERENCE_EFFECTIVE_DATE,
        "constituent_reference_snapshot_date": REFERENCE_SNAPSHOT_DATE,
        "constituent_reference_frozen": True,
        "constituent_reference_count": len(reference),
        "constituent_reference_overlap_count": len(observed & reference),
        "constituent_reference_missing_symbols": missing,
        "constituent_reference_unexpected_symbols": unexpected,
        "constituent_reference_matches": matches,
        "constituent_reference_note": (
            "Dated set comparison only; the frozen reference can become stale after "
            "index reviews. A mismatch requires review and does not establish which "
            "source is current. Returned source codes are unchanged; neither set "
            "provides historical point-in-time membership."
        ),
        "degraded": bool(metadata.get("degraded")) or not matches,
    }


def parse_constituents(html: str) -> tuple[list[str], dict[str, str]]:
    """Parse Wikipedia tickers and optional sector/industry/sub-index labels."""
    for table in pd.read_html(io.StringIO(html)):
        columns = {str(column).strip().lower(): column for column in table.columns}
        ticker = next(
            (columns[key] for key in ("ticker", "stock code", "symbol") if key in columns),
            None,
        )
        if ticker is None:
            continue
        sector = next(
            (columns[key] for key in ("sector", "industry", "sub-index") if key in columns),
            None,
        )
        codes, sectors = [], {}
        for _, row in table.iterrows():
            match = re.fullmatch(r"(?:SEHK\s*:\s*)?(\d{1,5})(?:\.HK)?", str(row[ticker]).strip(), re.I)
            if not match:
                continue
            code = normalize_hk_symbol(match.group(1))
            if code not in codes:
                codes.append(code)
            if sector is not None and pd.notna(row[sector]) and str(row[sector]).strip():
                sectors[code] = str(row[sector]).strip()
        if codes:
            return codes, sectors
    raise ValueError("No HSI constituent table found")


class HSIConstituentError(ValueError):
    """A stable, sanitized benchmark roster failure safe to expose to users."""

    def __init__(self, reason: str, detail: str = "", *, metadata: dict | None = None) -> None:
        self.reason = reason
        self.metadata = metadata or {}
        super().__init__(f"HSI constituent load failed: {reason}" + (f" ({detail})" if detail else ""))


def inspect_constituents() -> tuple[list[str], dict[str, str], dict]:
    """Inspect one revision-dated source without declaring benchmark eligibility.

    Codes are never padded, replaced or combined with the reference. Production
    benchmarks use fetch_benchmark_constituents to enforce both count and set.
    """
    fetched_at = datetime.now(timezone.utc).isoformat()
    try:
        response = requests.get(
            WIKIPEDIA_URL,
            headers={"User-Agent": "Vibe-Trading/0.1 (research bench; https://github.com/HKUDS/Vibe-Trading)"},
            timeout=20,
        )
        response.raise_for_status()
    except Exception as exc:  # noqa: BLE001 — untrusted transport boundary
        if isinstance(exc, requests.Timeout):
            reason = "request timed out"
        elif isinstance(exc, requests.HTTPError):
            reason = "HTTP request failed"
        elif isinstance(exc, requests.ConnectionError):
            reason = "connection failed"
        elif isinstance(exc, requests.RequestException):
            reason = "request failed"
        elif isinstance(exc, ValueError):
            reason = "invalid constituent data"
        else:
            reason = "constituent source failed"
        raise HSIConstituentError(reason) from None
    try:
        tables = pd.read_html(io.StringIO(response.text))
        candidates = []
        for table in tables:
            columns = {str(column).strip().lower(): column for column in table.columns}
            ticker = next(
                (columns[key] for key in ("ticker", "stock code", "symbol") if key in columns),
                None,
            )
            if ticker is not None:
                candidates.append((table, ticker))
        if len(candidates) != 1:
            raise HSIConstituentError("invalid constituent data", "parse_error")
        table, ticker = candidates[0]
        raw_codes = []
        for value in table[ticker]:
            match = re.fullmatch(r"(?:SEHK\s*:\s*)?(\d{1,5})(?:\.HK)?", str(value).strip(), re.I)
            if not match:
                raise HSIConstituentError("invalid constituent data", "invalid_symbols")
            code = normalize_hk_symbol(match.group(1))
            if not re.fullmatch(r"[0-9]{4}\.HK", code):
                raise HSIConstituentError("invalid constituent data", "invalid_symbols")
            raw_codes.append(code)
        if len(set(raw_codes)) != len(raw_codes):
            raise HSIConstituentError("invalid constituent data", "duplicate_symbols")
        codes, sectors = parse_constituents(response.text)
        modified = re.search(r'"dateModified"\s*:\s*"([^"]+)"', response.text)
        revision = re.search(r'"wgRevisionId"\s*:\s*(\d+)', response.text)
        if modified is None or revision is None:
            raise HSIConstituentError("invalid constituent data", "missing_provenance")
        timestamp = datetime.fromisoformat(modified.group(1).replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            raise HSIConstituentError("invalid constituent data", "missing_provenance")
    except HSIConstituentError:
        raise
    except Exception as exc:  # noqa: BLE001 — untrusted parser boundary
        reason = "invalid constituent data" if isinstance(exc, ValueError) else "constituent source failed"
        raise HSIConstituentError(reason) from None
    return (
        codes,
        sectors,
        _with_reference_metadata(
            codes,
            {
                "constituent_source": WIKIPEDIA_URL,
                "constituent_source_date": timestamp.date().isoformat(),
                "constituent_source_timestamp": timestamp.isoformat(),
                "constituent_sha256": hashlib.sha256(response.text.encode("utf-8")).hexdigest(),
                "constituent_source_date_kind": "wikipedia_revision_date",
                "constituent_revision_id": revision.group(1),
                "constituent_retrieved_at": fetched_at,
                "constituent_count_validation": "distinct canonical symbols; eligibility checked separately",
                "degraded": False,
                "constituent_note": "Current Wikipedia roster; revision time is not a membership effective date. The published reference is dated and must be reviewed after index reviews; neither is historical membership.",
            },
        ),
    )


def fetch_benchmark_constituents() -> tuple[list[str], dict[str, str], dict]:
    """Require the dated reference's count AND exact members before price access.

    Same-count membership differences are blocked even if Wikipedia is newer:
    review/update the reference using official effective-date evidence first.
    Neither a frozen roster nor cached prices substitute for a rejected source.
    """
    codes, sectors, metadata = inspect_constituents()
    eligible = len(codes) == PUBLISHED_CONSTITUENT_COUNT and metadata["constituent_reference_matches"]
    metadata = metadata | {"benchmark_membership_policy": "strict_dated_reference_v4", "benchmark_eligible": eligible}
    if len(codes) != PUBLISHED_CONSTITUENT_COUNT:
        raise HSIConstituentError(
            "invalid constituent data",
            f"count_mismatch: observed={len(codes)}, published_reference={PUBLISHED_CONSTITUENT_COUNT}, effective={REFERENCE_EFFECTIVE_DATE}",
            metadata=metadata,
        )
    if not eligible:
        raise HSIConstituentError(
            "invalid constituent data",
            "membership_mismatch: equal counts do not establish equal members; review official changes before updating the dated reference",
            metadata=metadata,
        )
    return codes, sectors, metadata


def cache_identity(roster: tuple[list[str], dict[str, str], dict]) -> str:
    """Key HK price caches by freshly validated source and dated reference."""
    import json

    codes, _, metadata = roster
    payload = {
        "symbols": sorted(codes),
        "revision": metadata.get("constituent_revision_id"),
        "source_sha256": metadata.get("constituent_sha256"),
        "reference": sorted(REFERENCE_CODES),
        "reference_effective": REFERENCE_EFFECTIVE_DATE,
        "policy": 4,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:24]
