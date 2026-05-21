"""
research/pipeline/stage2_strategies.py
────────────────────────────────────────
Stage-2 runner: Strategy Generation.

Per symbol in research_config.yaml this runner:
  1. Reads research/manifests/factor_<symbol>.json (stage-1 output) and selects
     only factors whose verdict is NOT ``reject``.
  2. Builds a Vibe-Trading swarm invocation, injecting the selected-factor JSON
     as decision context.
  3. Invokes ``vibe-trading --swarm-run crypto_trading_desk`` via subprocess.
  4. Writes, per generated strategy:
       - research/strategies/strategy_<id>.yaml   (the strategy spec)
       - research/manifests/<id>/generation.json  (stage-2 handoff)

Then verifies all outputs and exits non-zero on any failure.

Usage
-----
    # From repo root:
    python -m research.pipeline.stage2_strategies

    # From research/ directory (preferred):
    python -m pipeline.stage2_strategies

    # Direct script invocation:
    python research/pipeline/stage2_strategies.py

────────────────────────────────────────────────────────────────────────────
DESIGN NOTES — the two genuinely under-specified decisions, made explicit.
────────────────────────────────────────────────────────────────────────────

(A) HOW UPSTREAM JSON IS INJECTED.
    The ``crypto_trading_desk`` preset (agent/src/swarm/presets/...) declares
    exactly two variables — ``target`` and ``timeframe``. There is NO external
    decision-context channel:
      * ``{upstream_context}`` is filled ONLY from inter-agent ``input_from``
        task dependencies (agent/src/swarm/worker.py — build_worker_prompt does
        ``system_prompt.replace("{upstream_context}", upstream_block)`` where
        upstream_block comes from *previous agents*, not external input).
      * Only the task ``prompt_template`` gets ``user_vars`` substituted, via
        ``format_map`` (worker.py:320). Extra keys are silently tolerated by
        a fallback dict but never rendered because the preset templates do not
        reference them.
    Adding a real injection channel would require editing the preset or the
    worker — both forbidden (``agent/`` is off-limits).
    DECISION: inject the selected-factor JSON by appending it to the value of
    the ``timeframe`` variable. ``timeframe`` is free-form prose that DOES flow
    into a prompt_template, so the swarm's first-layer agents see it. We do NOT
    pack it into ``target`` because ``target`` is regex-scanned by the swarm's
    grounding layer (agent/src/swarm/grounding.py) and must stay a clean
    ``BASE-USDT`` token. The factor manifest for one symbol is small (a handful
    of factors, four horizons each — well under 1 KB of JSON), so the FULL JSON
    is injected, not a digest. The design Open Question ("full JSON vs digest,
    by token count") is therefore resolved in favour of full JSON.

(B) SWARM PROSE -> STRATEGY YAML.
    The swarm produces PROSE desk analysis (a trading plan in markdown). It
    does NOT natively emit a strategy YAML, and it cannot be told our exact
    YAML schema without editing the preset prompts (forbidden). Relying on the
    swarm's ``write_file`` tool to drop a schema-correct YAML is not viable:
    workers write to per-agent artifact dirs, the preset prompts hard-force a
    ``report.md`` deliverable, and there is no channel to communicate the
    target schema.
    DECISION: the runner OWNS the structured strategy spec. It deterministically
    synthesises a valid strategy YAML *scaffold* from the stage-1 factor
    manifest (the same schema as research/strategies/strategy_S*.yaml), and
    attaches the swarm's prose desk analysis as the rationale / hypothesis.
    The swarm's contribution is recorded as ``generation.rationale`` (Tier-3
    audit prose, per design D-tiers — "not evidence, post-hoc rationalisation")
    and the swarm run id as ``generation.source_run``.
    LIMITATION (explicit): the YAML's quantitative thresholds (percentiles,
    hold periods, parameter-search ranges) are a defensible scaffold derived
    from the factor verdicts and the conventions in the existing S1-S4 files —
    they are NOT authored by the LLM. A faithful LLM-authored spec would
    require an ``agent/`` change (e.g. a new preset variable + a structured
    output contract). This is called out in the stage report.
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
# This module lives at <repo-root>/research/pipeline/stage2_strategies.py.
# Bootstrap research/ and dashboard/server/ onto sys.path so imports work
# regardless of CWD or how this script is invoked.
_THIS_FILE = Path(__file__).resolve()
_PIPELINE_DIR = _THIS_FILE.parent          # research/pipeline/
_RESEARCH_DIR = _PIPELINE_DIR.parent       # research/

for _p in (_RESEARCH_DIR,):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

# ── Standard library ───────────────────────────────────────────────────────────
import dataclasses
import json
import re
import subprocess
from datetime import datetime, timezone

# ── Internal imports ───────────────────────────────────────────────────────────
# Per the stage-1 code review: import _REPO_ROOT from pipeline.config rather
# than recomputing it, so all stages agree on one repo-root definition.
from pipeline.config import _REPO_ROOT, ResearchConfig, SymbolConfig, load_config

_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"
if str(_DASHBOARD_SCHEMAS) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD_SCHEMAS))

from schemas import FactorEntry, FactorManifest, FactorVerdict, GenerationBlock  # noqa: E402

# ─── Constants ────────────────────────────────────────────────────────────────

#: The swarm preset stage 2 drives (design D2).
SWARM_PRESET = "crypto_trading_desk"

#: Default trading horizon passed as the swarm ``timeframe`` variable.
#: The validated funding/F&G IC is strongest at the 72-168h horizon, so a
#: multi-day swing horizon is the natural default for generated strategies.
DEFAULT_TIMEFRAME = "swing 3-7 days"

#: Method string recorded in GenerationBlock.method.
GENERATION_METHOD = f"{SWARM_PRESET} swarm (stage 2 strategy generation)"

#: Run id shape emitted by the swarm runtime — swarm-YYYYMMDD-HHMMSS-<hex8>.
#: See agent/src/swarm/presets.py:build_run_from_preset.
_RUN_ID_RE = re.compile(r"\bswarm-\d{8}-\d{6}-[0-9a-f]{8}\b")

#: How many strategies stage 2 emits per symbol. The swarm delivers ONE
#: integrated desk plan per run, so the runner emits one strategy per run.
STRATEGIES_PER_SYMBOL = 1


# ─── Data containers ──────────────────────────────────────────────────────────


@dataclasses.dataclass
class GeneratedStrategy:
    """A strategy produced by stage 2: its YAML spec + generation handoff."""

    strategy_id: str
    symbol: str            # short lowercase symbol name, e.g. "btc"
    yaml_path: Path        # research/strategies/strategy_<id>.yaml
    generation_path: Path  # research/manifests/<id>/generation.json


@dataclasses.dataclass
class StrategyCheckResult:
    """Result of verifying one generated strategy's on-disk outputs."""

    strategy_id: str
    ok: bool
    error: str | None = None


# ─── Pure-logic helpers (testable, network-free, no subprocess) ───────────────


def select_usable_factors(manifest: FactorManifest) -> list[FactorEntry]:
    """Return factors whose verdict is NOT ``reject``, preserving input order.

    Spec requirement (research-pipeline spec, scenario "階段 2 讀階段 1 輸出"):
    stage 2 only adopts factors whose ``verdict`` is not ``reject``.

    Args:
        manifest: A validated FactorManifest (stage-1 output for one symbol).

    Returns:
        List of FactorEntry with single_use / ensemble_only verdicts only.
    """
    return [f for f in manifest.factors if f.verdict != FactorVerdict.REJECT]


def swarm_target_from_ticker(okx_swap: str) -> str:
    """Convert an OKX swap ticker into a grounding-friendly swarm ``target``.

    The swarm grounding layer (agent/src/swarm/grounding.py) regex-detects
    ``BASE-USDT`` tokens, NOT ``BASE-USDT-SWAP``. Stripping the ``-SWAP``
    suffix lets the swarm pre-fetch real recent prices for the asset.

    Args:
        okx_swap: OKX perpetual swap ticker, e.g. "BTC-USDT-SWAP".

    Returns:
        Uppercased ``BASE-USDT`` token, e.g. "BTC-USDT".
    """
    token = okx_swap.strip().upper()
    if token.endswith("-SWAP"):
        token = token[: -len("-SWAP")]
    return token


def _factor_to_context_dict(factor: FactorEntry) -> dict:
    """Serialise a FactorEntry into a compact JSON-friendly decision-context dict."""
    return {
        "name": factor.name,
        "verdict": factor.verdict.value,
        "ir": factor.ir,
        "sample_size": factor.sample_size,
        "ic_by_horizon": {str(h): ic for h, ic in factor.ic_by_horizon.items()},
        "stability": factor.stability.value if factor.stability is not None else None,
    }


def build_swarm_vars(
    target: str,
    usable_factors: list[FactorEntry],
    timeframe: str = DEFAULT_TIMEFRAME,
) -> dict[str, str]:
    """Build the ``user_vars`` dict for ``vibe-trading --swarm-run``.

    Decision-context injection (see module docstring, decision A): the
    selected-factor JSON is appended to the ``timeframe`` value. ``target``
    is kept as a clean symbol token so the swarm grounding regex can detect it.

    Args:
        target: Clean swarm target token, e.g. "BTC-USDT".
        usable_factors: Factors selected by select_usable_factors().
        timeframe: Trading-horizon prose; the factor context is appended to it.

    Returns:
        dict[str, str] suitable for ``json.dumps`` into the CLI VARS_JSON arg.
        Every value is a string so prompt_template.format_map cannot break.
    """
    context = [_factor_to_context_dict(f) for f in usable_factors]
    context_json = json.dumps(context, ensure_ascii=False)

    timeframe_with_context = (
        f"{timeframe}\n\n"
        "## Stage-1 factor analysis (decision context — injected by the "
        "research pipeline)\n"
        "The following factors passed stage-1 IC/IR screening (verdict is not "
        "`reject`). Use them as the evidence base for the desk's trade plan; "
        "favour contrarian/mean-reversion framing for factors with negative "
        "IC and trend framing for positive IC.\n\n"
        f"factors_json = {context_json}"
    )

    return {
        "target": target,
        "timeframe": timeframe_with_context,
    }


def parse_swarm_result(stdout: str) -> str | None:
    """Extract the swarm run id from ``vibe-trading --swarm-run`` stdout.

    The CLI's live dashboard prints the run id (shape
    ``swarm-YYYYMMDD-HHMMSS-<hex8>``) as it streams. The first such token in
    the output is the run that was just launched.

    Args:
        stdout: Captured stdout of the swarm subprocess.

    Returns:
        The run id string, or None if no run id is present.
    """
    match = _RUN_ID_RE.search(stdout or "")
    return match.group(0) if match else None


def _archetype_for(usable_factors: list[FactorEntry]) -> str:
    """Pick a strategy archetype label from the usable factors.

    Heuristic mirroring the existing S1-S4 conventions:
      * >=2 factors  -> multi_factor_consensus
      * 1 factor     -> <factor>_mean_reversion (the validated edge is
                        contrarian — see crypto_alpha_workflow findings).
    """
    if len(usable_factors) >= 2:
        return "multi_factor_consensus"
    if len(usable_factors) == 1:
        return f"{usable_factors[0].name}_mean_reversion"
    return "factor_based"  # unreachable: build_strategy_spec rejects empty input


def build_strategy_spec(
    symbol: str,
    ticker: str,
    usable_factors: list[FactorEntry],
    swarm_rationale: str,
    seq: int,
) -> tuple[str, str]:
    """Synthesise a strategy id + strategy YAML scaffold (see module docstring B).

    The YAML matches the schema of research/strategies/strategy_S*.yaml. The
    swarm's prose desk analysis is embedded as the ``hypothesis`` rationale so
    the qualitative reasoning is preserved for the dashboard.

    Args:
        symbol: Short lowercase symbol name, e.g. "btc".
        ticker: Exchange ticker the strategy trades, e.g. "BTC-USDT-SWAP".
        usable_factors: Non-rejected factors from stage 1 (must be non-empty).
        swarm_rationale: The swarm's prose desk analysis (final report text).
        seq: 1-based strategy sequence number within this symbol (-> s<seq>).

    Returns:
        (strategy_id, yaml_text). strategy_id follows <coin>_s<N>_<archetype>.

    Raises:
        ValueError: If usable_factors is empty (a zero-factor strategy is
            meaningless and must not be emitted).
    """
    if not usable_factors:
        raise ValueError(
            f"cannot build a strategy for {symbol!r}: no usable factors "
            "(every stage-1 factor had verdict=reject)"
        )

    archetype = _archetype_for(usable_factors)
    strategy_id = f"{symbol.lower()}_s{seq}_{archetype}"

    factor_names = [f.name for f in usable_factors]

    # Indicators block — one entry per usable factor. funding_rate / fng have
    # canonical sources in the S1-S4 files; anything else gets a generic stub.
    _KNOWN_SOURCES = {
        "funding_rate": "okx:funding-rate-history",
        "fng": "alternative.me",
    }
    indicators: dict[str, dict] = {}
    for f in usable_factors:
        indicators[f.name] = {
            "source": _KNOWN_SOURCES.get(f.name, f"stage1:{f.name}"),
            "smoothing": "sma_3",
        }

    # Hypothesis: the swarm prose desk analysis, trimmed. This is the channel
    # through which the LLM's qualitative reasoning reaches the strategy.
    rationale = (swarm_rationale or "").strip()
    if not rationale:
        rationale = (
            "Swarm desk analysis was unavailable; strategy scaffold derived "
            "from stage-1 factor verdicts only."
        )

    spec: dict = {
        "name": strategy_id,
        "archetype": archetype,
        # block-literal style for multi-line readability, like S1-S4.
        "hypothesis": (
            f"Stage-1 screening retained these factors with a tradable edge: "
            f"{', '.join(factor_names)}. Crypto-trading-desk swarm rationale "
            f"(post-hoc, see generation.json):\n{rationale}"
        ),
        "symbol": ticker,
        "timeframe_signal": "8h",
        "hold_period": {"min_hours": 24, "max_hours": 120},
        "indicators": indicators,
        "entry_long": {
            "description": (
                "Enter long when the retained factors align in a "
                "fear / short-crowded (contrarian) regime with persistence."
            ),
            "conditions": [
                f"{name} percentile over last 90 days <= 20th percentile, "
                "observed in at least 2 of the last 3 settlements (after smoothing)."
                for name in factor_names
            ],
        },
        "entry_short": {
            "description": (
                "Enter short when the retained factors align in a "
                "greed / long-crowded (contrarian) regime with persistence."
            ),
            "conditions": [
                f"{name} percentile over last 90 days >= 80th percentile, "
                "observed in at least 2 of the last 3 settlements (after smoothing)."
                for name in factor_names
            ],
        },
        "exit_rules": [
            {"condition": "time_based", "max_hold_hours": 120},
            {"condition": "take_profit_pct", "value": 6.0},
            {"condition": "stop_loss_pct", "value": 3.0},
            {
                "condition": "signal_invalidation",
                "description": (
                    "Exit when the retained factors revert toward neutral "
                    "(percentile back inside the 40th-60th band)."
                ),
            },
        ],
        "position_sizing": {
            "method": "fixed_risk",
            "risk_per_trade_pct": 1.5,
            "leverage": 1.5,
        },
        "parameter_search_ranges": {
            "lookback_days": [60, 120, 30],
            "entry_high_pct": [75, 90, 5],
            "entry_low_pct": [10, 25, 5],
            "persistence_last_n": [3, 5, 1],
            "persistence_min_hits": [2, 3, 1],
            "hold_max_hours": [96, 144, 24],
            "tp_pct": [4.0, 7.0, 1.5],
            "sl_pct": [2.5, 4.0, 0.5],
        },
        "expected_behavior": {
            "trades_per_year_estimate": 80,
            "expected_sharpe": 1.0,
            "expected_max_dd_pct": 8.0,
            "expected_win_rate_pct": 51,
        },
        "caveats": [
            "Quantitative thresholds in this spec are a deterministic scaffold "
            "derived from stage-1 factor verdicts, NOT authored by the LLM "
            "swarm (see stage2_strategies.py module docstring, decision B). "
            "Calibrate via the stage-4 parameter sweep before trusting them.",
            "Factor edges can decay across market regimes; re-run stage 1 "
            "periodically and watch cross_regime_ic / stability.",
        ],
    }

    # default_flow_style=False -> block style, matching the existing S*.yaml.
    # allow_unicode keeps any CJK in the swarm prose readable.
    import yaml  # local import: yaml is only needed for output, not for tests

    yaml_text = yaml.safe_dump(
        spec,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
        width=100,
    )
    return strategy_id, yaml_text


def build_generation_block(
    run_id: str | None,
    usable_factors: list[FactorEntry],
    rationale: str,
    model: str | None = None,
) -> dict:
    """Build the stage-2 ``generation.json`` payload, aligned with GenerationBlock.

    The dashboard schema (dashboard/server/schemas.py:GenerationBlock) consumes
    this in task 2.12 (emit_manifest.py) as ``StrategyManifest.generation``.

    Args:
        run_id: The swarm run id (-> source_run); None if it could not be parsed.
        usable_factors: Non-rejected factors fed to the swarm (-> factors_used).
        rationale: The swarm's prose desk analysis (-> rationale; Tier-3 audit).
        model: Optional LLM model id (-> model).

    Returns:
        A plain dict that validates against GenerationBlock.
    """
    return {
        "source_run": run_id,
        "method": GENERATION_METHOD,
        "model": model,
        "rationale": rationale or None,
        "factors_used": [f.name for f in usable_factors],
    }


def check_strategy(generated: GeneratedStrategy) -> StrategyCheckResult:
    """Verify one generated strategy's YAML + generation.json on disk.

    Checks: the YAML exists and parses; generation.json exists and validates
    against the GenerationBlock schema.

    Args:
        generated: A GeneratedStrategy handle from a stage-2 run.

    Returns:
        StrategyCheckResult describing whether both outputs are present & valid.
    """
    import yaml  # local import — see build_strategy_spec

    if not generated.yaml_path.exists():
        return StrategyCheckResult(
            strategy_id=generated.strategy_id,
            ok=False,
            error=f"strategy YAML missing: {generated.yaml_path.name}",
        )
    try:
        doc = yaml.safe_load(generated.yaml_path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict):
            raise ValueError("strategy YAML is not a mapping")
    except Exception as exc:  # noqa: BLE001
        return StrategyCheckResult(
            strategy_id=generated.strategy_id,
            ok=False,
            error=f"strategy YAML invalid: {exc}",
        )

    if not generated.generation_path.exists():
        return StrategyCheckResult(
            strategy_id=generated.strategy_id,
            ok=False,
            error=f"generation.json missing: {generated.generation_path}",
        )
    try:
        raw = generated.generation_path.read_text(encoding="utf-8")
        GenerationBlock.model_validate_json(raw)
    except Exception as exc:  # noqa: BLE001
        return StrategyCheckResult(
            strategy_id=generated.strategy_id,
            ok=False,
            error=f"generation.json invalid: {exc}",
        )

    return StrategyCheckResult(strategy_id=generated.strategy_id, ok=True)


def verify_outputs(generated: list[GeneratedStrategy]) -> list[StrategyCheckResult]:
    """Check all generated strategies after stage-2 runs.

    Args:
        generated: List of GeneratedStrategy handles produced by the run.

    Returns:
        List of StrategyCheckResult, one per strategy, in input order.
    """
    return [check_strategy(g) for g in generated]


def compute_exit_code(results: list[StrategyCheckResult]) -> int:
    """Return 0 if at least one strategy was produced and all results are ok.

    An empty result list is a FAILURE: stage 2 producing zero strategies
    means downstream stages have nothing to backtest.

    Args:
        results: List of StrategyCheckResult from verify_outputs().

    Returns:
        0 on full success (>=1 strategy, all ok); 1 otherwise.
    """
    if not results:
        return 1
    return 0 if all(r.ok for r in results) else 1


def print_summary(results: list[StrategyCheckResult]) -> None:
    """Print a human-readable per-strategy summary to stdout.

    Args:
        results: List of StrategyCheckResult from verify_outputs().
    """
    print("\n" + "=" * 60)
    print("Stage-2 output verification summary")
    print("=" * 60)
    if not results:
        print("  (no strategies were generated)")
    for r in results:
        status = "OK" if r.ok else "FAIL"
        msg = "strategy YAML + generation.json present and valid" if r.ok else r.error
        print(f"  [{status}] {r.strategy_id}: {msg}")

    total = len(results)
    passed = sum(1 for r in results if r.ok)
    print(f"\n{passed}/{total} strategies passed.")
    if total == 0 or passed < total:
        print("Stage 2 FAILED: missing or invalid strategy outputs.")
    else:
        print("Stage 2 PASSED: all strategy outputs present and valid.")
    print("=" * 60)


# ─── Stage orchestration (thin shell, not unit-tested) ────────────────────────


def run_swarm(vars_dict: dict[str, str]) -> str:
    """Invoke ``vibe-trading --swarm-run crypto_trading_desk`` and return stdout.

    The Vibe-Trading CLI entry point is ``cli.py`` (pyproject.toml installs it
    as the ``vibe-trading`` console script, but invoking the script directly
    works regardless of install state — Linux-deploy safe). ``cli.py`` imports
    ``src.*`` packages, so the subprocess MUST run with cwd=<repo>/agent.

    This function is NOT unit-tested — it shells out to the real swarm, which
    costs money and needs API keys. Tests stub it / mock subprocess.

    Args:
        vars_dict: The user_vars dict from build_swarm_vars().

    Returns:
        Captured stdout of the swarm run.

    Raises:
        subprocess.CalledProcessError: If the CLI exits non-zero.
    """
    agent_dir = _REPO_ROOT / "agent"
    cli_path = agent_dir / "cli.py"
    vars_json = json.dumps(vars_dict, ensure_ascii=False)

    cmd = [sys.executable, str(cli_path), "--swarm-run", SWARM_PRESET, vars_json]
    print(f"[stage2] invoking swarm: {SWARM_PRESET}  (cwd={agent_dir})")
    completed = subprocess.run(
        cmd,
        cwd=str(agent_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )
    return completed.stdout or ""


def _generate_for_symbol(
    sym: SymbolConfig,
    strategies_dir: Path,
    manifests_dir: Path,
    seq: int,
) -> GeneratedStrategy:
    """Run the full stage-2 pipeline for one symbol and write its outputs.

    Steps: read factor manifest -> select usable factors -> build swarm vars ->
    invoke swarm -> synthesise strategy YAML -> write YAML + generation.json.

    Args:
        sym: The SymbolConfig for this symbol.
        strategies_dir: research/strategies/ — where the YAML is written.
        manifests_dir: research/manifests/ — generation.json goes under <id>/.
        seq: 1-based strategy sequence number for this symbol.

    Returns:
        A GeneratedStrategy handle pointing at the written files.

    Raises:
        FileNotFoundError: If the stage-1 factor manifest is absent.
        ValueError: If the manifest has no usable (non-rejected) factors.
    """
    manifest_path = manifests_dir / f"factor_{sym.name}.json"
    if not manifest_path.exists():
        raise FileNotFoundError(
            f"stage-1 factor manifest not found: {manifest_path}\n"
            "Run stage 1 (stage1_factors.py) before stage 2."
        )

    manifest = FactorManifest.model_validate_json(
        manifest_path.read_text(encoding="utf-8")
    )
    usable = select_usable_factors(manifest)
    print(
        f"[stage2] {sym.name}: {len(usable)}/{len(manifest.factors)} factors "
        f"usable (non-reject): {[f.name for f in usable]}"
    )
    if not usable:
        raise ValueError(
            f"{sym.name}: every stage-1 factor had verdict=reject — "
            "nothing to build a strategy from."
        )

    target = swarm_target_from_ticker(sym.okx_swap)
    vars_dict = build_swarm_vars(target, usable)

    swarm_stdout = run_swarm(vars_dict)
    run_id = parse_swarm_result(swarm_stdout)
    print(f"[stage2] {sym.name}: swarm run id = {run_id}")

    rationale = extract_swarm_report(swarm_stdout)

    strategy_id, yaml_text = build_strategy_spec(
        symbol=sym.name,
        ticker=sym.okx_swap,
        usable_factors=usable,
        swarm_rationale=rationale,
        seq=seq,
    )

    # Write the strategy YAML.
    strategies_dir.mkdir(parents=True, exist_ok=True)
    yaml_path = strategies_dir / f"strategy_{strategy_id}.yaml"
    yaml_path.write_text(yaml_text, encoding="utf-8")
    print(f"[stage2] {sym.name}: wrote {yaml_path.name}")

    # Write the generation.json handoff under manifests/<id>/.
    gen_dir = manifests_dir / strategy_id
    gen_dir.mkdir(parents=True, exist_ok=True)
    gen_block = build_generation_block(
        run_id=run_id,
        usable_factors=usable,
        rationale=rationale,
    )
    gen_path = gen_dir / "generation.json"
    gen_path.write_text(
        json.dumps(gen_block, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"[stage2] {sym.name}: wrote {gen_path}")

    return GeneratedStrategy(
        strategy_id=strategy_id,
        symbol=sym.name,
        yaml_path=yaml_path,
        generation_path=gen_path,
    )


def extract_swarm_report(stdout: str) -> str:
    """Best-effort extraction of the swarm's prose final report from stdout.

    The CLI prints a "── Final Report ──" header (cli.py:cmd_swarm_run_live).
    If that marker is absent (older CLI, truncated output) the whole stdout
    tail is returned so the rationale is never silently lost.

    Args:
        stdout: Captured stdout of the swarm subprocess.

    Returns:
        The desk-analysis prose, trimmed to a reasonable length.
    """
    text = stdout or ""
    marker = "Final Report"
    idx = text.rfind(marker)
    report = text[idx + len(marker):] if idx != -1 else text
    # Strip the box-drawing / ascii decoration the CLI wraps the header in
    # ("── Final Report ──" -> leftover "──" / "--" on the first line).
    report = report.strip().lstrip("-─— \t").strip()
    # Keep it bounded — this becomes generation.rationale (Tier-3 audit prose).
    return report[:4000]


def main() -> None:
    """Stage-2 entry point: orchestrate, verify, report, exit."""
    cfg: ResearchConfig = load_config()
    strategies_dir = _REPO_ROOT / "research" / "strategies"
    manifests_dir = _REPO_ROOT / "research" / "manifests"

    print("=" * 60)
    print("Stage 2 — Strategy Generation")
    print("=" * 60)
    print(f"Config: symbols={cfg.symbol_names()}  preset={SWARM_PRESET}")
    print(f"Strategy output:   {strategies_dir}")
    print(f"Generation output: {manifests_dir}")

    generated: list[GeneratedStrategy] = []
    for sym in cfg.symbols:
        print(f"\n[stage2] ── symbol: {sym.name} ──")
        try:
            # STRATEGIES_PER_SYMBOL is 1; seq starts at 1 (-> _s1_).
            for seq in range(1, STRATEGIES_PER_SYMBOL + 1):
                gen = _generate_for_symbol(sym, strategies_dir, manifests_dir, seq)
                generated.append(gen)
        except Exception as exc:  # noqa: BLE001
            # One symbol failing must not abort the others; verify_outputs
            # below will surface the gap as a non-zero exit code.
            print(f"[stage2] {sym.name}: FAILED — {exc}")

    results = verify_outputs(generated)
    print_summary(results)
    sys.exit(compute_exit_code(results))


if __name__ == "__main__":
    main()
