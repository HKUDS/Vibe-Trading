"""Generate the broker capability matrix from the profile registry (#1626).

Render declared capabilities per profile into the marked README and broker guide.
The registry does not attest to successful runtime verification or enumerate
order kinds; the generated text explicitly preserves those limits. A CI drift
guard keeps the published declarations aligned with the registry.

Regenerate after touching connector profiles:

    PYTHONPATH=agent python -m src.trading.capability_matrix
"""

from __future__ import annotations

import re
from itertools import groupby
from pathlib import Path

from src.trading.profiles import BUILTIN_PROFILES

README_PATH = Path(__file__).resolve().parents[3] / "README.md"
GUIDE_PATH = README_PATH.parent / "guides/portfolio-and-brokers.md"
_BEGIN = "<!-- BEGIN GENERATED broker-capability-matrix -->"
_END = "<!-- END GENERATED broker-capability-matrix -->"

_HEADER = """Declared built-in profiles, generated from `agent/src/trading/profiles.py`.
Each row keeps its own environment and permissions; a paper order capability
never grants live trading. These are declarations, not successful runtime or
broker verification. Local plugins and user connection settings are excluded.

The quote column shows the declared transport, not a verified endpoint or
pricing coverage. Order kinds (market, limit, etc.) are not declared in the
registry and are therefore not inferred here. The placement column reports
the declared mandate requirement only; it does not attest to cancellation,
flattening, copy-trading, or other runtime guard coverage. Paper placement can
use a broker sandbox or local simulation. See each profile's notes and the
[broker bring-up checklist](../CONTRIBUTING.md#broker-bring-up-checklist).

| Profile | Connector | Environment | Transport | Mode | Read capabilities | Quote path (declared) | Other capabilities | Placement requirement (declared) |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |"""


def _cell(values: list[str]) -> str:
    return ", ".join(f"`{value}`" for value in sorted(values)) or "none declared"


def render() -> str:
    """Render each built-in profile without merging its permissions with others."""
    lines = [_HEADER]
    for profile in sorted(BUILTIN_PROFILES, key=lambda p: (p.connector, p.id)):
        reads = [cap for cap in profile.capabilities if cap.endswith(".read")]
        other = [cap for cap in profile.capabilities if not cap.endswith(".read")]
        quote = profile.transport if "quotes.read" in profile.capabilities else "none declared"
        if profile.readonly:
            placement = "disabled (read-only)"
        elif "orders.place.requires_mandate" in profile.capabilities:
            placement = "mandate required"
        elif "orders.place" in profile.capabilities:
            placement = "no mandate declared"
        else:
            placement = "no placement declared"
        mode = "read-only" if profile.readonly else "write-enabled"
        lines.append(
            f"| `{profile.id}` | {profile.connector} | {profile.environment} | "
            f"{profile.transport} | {mode} | {_cell(reads)} | {quote} | "
            f"{_cell(other)} | {placement} |"
        )
    return "\n".join(lines) + "\n"


def _broker_rows(supported_label: str) -> list[str]:
    """Return broker permissions for the display language's table."""
    rows = []
    profiles = sorted(BUILTIN_PROFILES, key=lambda p: p.connector)
    for broker, group in groupby(profiles, key=lambda p: p.connector):
        broker_profiles = list(group)
        readonly = any(p.readonly for p in broker_profiles)
        paper = any(
            p.environment == "paper" and not p.readonly and "orders.place" in p.capabilities
            for p in broker_profiles
        )
        live = any(
            p.environment == "live" and not p.readonly and "orders.place.requires_mandate" in p.capabilities
            for p in broker_profiles
        )
        cells = [supported_label if supported else "—" for supported in (readonly, paper, live)]
        rows.append(f"| {broker} | " + " | ".join(cells) + " |")
    return rows


def _broker_overview() -> str:
    lines = [
        "**Read** means a dedicated read-only profile. **Sim** means paper orders through a broker sandbox "
        "or local simulation. **Live** means live orders under a mandate.",
        "",
        "Yes indicates a declared capability. A dash means no matching profile is declared.",
        "",
        "| Broker | Read | Sim | Live |",
        "| --- | :---: | :---: | :---: |",
    ]
    lines.extend(_broker_rows("Yes"))
    return "\n".join(lines)


def render_block(*, detailed: bool = False) -> str:
    if detailed:
        body = render().rstrip()
    else:
        body = (
            "### Broker support at a glance\n\n"
            "<details>\n<summary>Compare read-only, paper and live support by broker</summary>\n\n"
            + _broker_overview()
            + "\n\n</details>\n\n[Full permissions by profile](guides/portfolio-and-brokers.md#full-broker-permissions)"
        )
    return f"{_BEGIN}\n\n{body}\n\n{_END}"


def sync_readme(readme: str, *, detailed: bool = False) -> str:
    block = render_block(detailed=detailed)
    pattern = re.compile(re.escape(_BEGIN) + r".*?" + re.escape(_END), re.DOTALL)
    if readme.count(_BEGIN) != 1 or readme.count(_END) != 1 or not pattern.search(readme):
        raise ValueError(f"README must contain exactly one ordered {_BEGIN} marker block")
    return pattern.sub(lambda _: block, readme)


def sync_translated_overview(text: str) -> str:
    """Refresh the broker rows while preserving the translated four-column header."""
    begin = "<!-- BEGIN GENERATED broker-overview -->"
    end = "<!-- END GENERATED broker-overview -->"
    before, start, rest = text.partition(begin)
    block, stop, after = rest.partition(end)
    header = block.strip().splitlines()[:2]
    if text.count(begin) != 1 or text.count(end) != 1 or not stop:
        raise ValueError("Expected one ordered pair of broker overview markers")
    if len(header) != 2 or header[1] != "| --- | :---: | :---: | :---: |":
        raise ValueError("Expected one marked four-column broker overview")
    return before + start + "\n\n" + "\n".join([*header, *_broker_rows("✓")]) + "\n\n" + stop + after


def main() -> None:
    for path in (README_PATH, GUIDE_PATH):
        text = path.read_text(encoding="utf-8")
        path.write_text(sync_readme(text, detailed=path == GUIDE_PATH), encoding="utf-8")
        print(f"synced {path} ({len(BUILTIN_PROFILES)} profiles)")
    for path in sorted(README_PATH.parent.glob("README_*.md")):
        path.write_text(sync_translated_overview(path.read_text(encoding="utf-8")), encoding="utf-8")
        print(f"synced {path}")


if __name__ == "__main__":
    main()
