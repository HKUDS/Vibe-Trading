"""
research/pipeline/stage0_discovery.py
───────────────────────────────────────
Stage-0 runner: Factor Discovery.

For each symbol in research_config.yaml, invokes the ``crypto_factor_lab``
swarm to propose FactorCandidate entries, validates them against SOURCE_REGISTRY
and TRANSFORM_REGISTRY, and writes research/manifests/candidates_<sym>.json.

Stage-1 (factor_extended) consumes these manifests as its candidate list. If
stage 0 fails for a symbol, it writes a ``candidates_<sym>.failed.json`` marker
and prints a bold-red warning so the pipeline can fall back to LEGACY_FACTORS
(handled by Task 5 / stage 1).

Usage
-----
    # From repo root:
    python -m research.pipeline.stage0_discovery

    # From research/ directory (preferred):
    python -m pipeline.stage0_discovery

    # Direct script invocation:
    python research/pipeline/stage0_discovery.py

    # Force re-run (ignore cache):
    python -m pipeline.stage0_discovery --force

Design note
-----------
Same thin-orchestration pattern as stage1_factors.py:
  - pure-logic helpers at module level (testable, no I/O dependencies)
  - subprocess swarm call isolated in run_swarm()
  - _process_symbol() handles one symbol end-to-end with retry
  - main() drives the loop then verify_outputs() + sys.exit()
"""

from __future__ import annotations

import sys
from pathlib import Path

# ── Path bootstrap ─────────────────────────────────────────────────────────────
# This module lives at <repo-root>/research/pipeline/stage0_discovery.py.
# Bootstrap research/ and dashboard/server/ onto sys.path so imports work
# regardless of CWD or how this script is invoked.
_THIS_FILE = Path(__file__).resolve()
_PIPELINE_DIR = _THIS_FILE.parent          # research/pipeline/
_RESEARCH_DIR = _PIPELINE_DIR.parent       # research/
_REPO_ROOT = _RESEARCH_DIR.parent          # repo root
_DASHBOARD_SCHEMAS = _REPO_ROOT / "dashboard" / "server"

for _p in (_RESEARCH_DIR, _DASHBOARD_SCHEMAS):
    _ps = str(_p)
    if _ps not in sys.path:
        sys.path.insert(0, _ps)

# ── Standard library ───────────────────────────────────────────────────────────
import argparse
import dataclasses
import json
import os
import re
import subprocess
from datetime import datetime, timezone

# ── Internal imports ───────────────────────────────────────────────────────────
from pipeline.config import _REPO_ROOT as _CFG_REPO_ROOT, ResearchConfig, load_config
from lib.sources import SOURCE_REGISTRY, TRANSFORM_REGISTRY
from schemas import CandidatesManifest, FactorCandidate

# ─── Constants ────────────────────────────────────────────────────────────────

#: Swarm preset name for factor discovery.
SWARM_PRESET = "crypto_factor_lab"

#: Default timeout for a swarm subprocess (seconds). Longer than stage 2
#: because the factor lab may run more parallel workers.
SWARM_TIMEOUT_S = 1200

#: ANSI codes for red warning lines.
_RED = "\033[91m"
_RESET = "\033[0m"

#: Regex that matches a fenced JSON code block produced by an LLM.
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*\n([\s\S]*?)\n```", re.IGNORECASE)


# ─── Pure-logic helpers (testable, network-free) ──────────────────────────────


@dataclasses.dataclass
class CandidatesCheckResult:
    """Result of checking a single symbol's candidates manifest."""

    symbol: str
    exists: bool
    valid: bool
    n_candidates: int = 0
    from_cache: bool = False
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.exists and self.valid


def parse_candidates_json(stdout: str) -> list[dict]:
    """Extract the first JSON fenced code block that is a JSON array from stdout.

    Scans ALL fenced code blocks (```json or ```) in order and returns the
    content of the first one that parses as a JSON list. This avoids the bug
    where an LLM emits a reasoning JSON object before the actual candidate list.

    Args:
        stdout: Raw string output from the swarm subprocess.

    Returns:
        List of raw dicts (not yet validated against FactorCandidate).

    Raises:
        ValueError: If no fenced block contains a valid JSON array.
    """
    matches = _JSON_FENCE_RE.findall(stdout or "")
    if not matches:
        raise ValueError(
            "No JSON fenced code block found in swarm output. "
            "Expected a ```json ... ``` block containing a list of factor candidates."
        )

    for raw_json in matches:
        text = raw_json.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            return data

    raise ValueError(
        "No valid JSON array found in any fenced code block in stdout. "
        f"Found {len(matches)} block(s) but none parsed as a JSON list."
    )


def filter_invalid_candidates(
    raw_candidates: list[dict],
    available_sources: list[str],
    available_transforms: list[str],
) -> tuple[list[dict], list[str]]:
    """Filter out candidates with unavailable source or unknown transform.

    Args:
        raw_candidates:       List of raw dicts from parse_candidates_json().
        available_sources:    SOURCE_REGISTRY keys with status="available".
        available_transforms: TRANSFORM_REGISTRY keys.

    Returns:
        (valid_candidates, warnings) where ``warnings`` is a list of human-
        readable warning strings, one per filtered-out candidate.
    """
    valid: list[dict] = []
    warnings: list[str] = []

    source_set = set(available_sources)
    transform_set = set(available_transforms)

    for i, cand in enumerate(raw_candidates):
        name = cand.get("name", f"<candidate[{i}]>")
        src = cand.get("data_source", "")
        tfm = cand.get("transform", "")

        if src not in source_set:
            warnings.append(
                f"[stage0] Filtered candidate '{name}': "
                f"data_source='{src}' not in available sources {sorted(source_set)}."
            )
            continue

        if tfm not in transform_set:
            warnings.append(
                f"[stage0] Filtered candidate '{name}': "
                f"transform='{tfm}' not in TRANSFORM_REGISTRY {sorted(transform_set)}."
            )
            continue

        valid.append(cand)

    return valid, warnings


def cache_hit(manifests_dir: Path, sym: str, cache_days: int) -> bool:
    """Return True if a valid cached manifest exists within the TTL window.

    Args:
        manifests_dir: Path to research/manifests/.
        sym:           Short lowercase symbol name (e.g. "eth").
        cache_days:    TTL in days. If 0, cache is disabled and this always
                       returns False.

    Returns:
        True if candidates_<sym>.json exists and its ``generated_at`` timestamp
        is less than ``cache_days`` days old; False otherwise.
    """
    if cache_days == 0:
        return False

    path = manifests_dir / f"candidates_{sym}.json"
    if not path.exists():
        return False

    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        generated_at_str = raw.get("generated_at", "")
        generated_at = datetime.fromisoformat(generated_at_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        age_days = (now - generated_at).total_seconds() / 86400.0
        return age_days < cache_days
    except Exception:  # noqa: BLE001
        return False


def verify_outputs(
    manifests_dir: Path,
    symbols: list[str],
) -> list[CandidatesCheckResult]:
    """Check all expected candidates manifests after stage 0 runs.

    Args:
        manifests_dir: Path to research/manifests/.
        symbols:       Short lowercase symbol names from config.

    Returns:
        One CandidatesCheckResult per symbol, in input order.
    """
    results: list[CandidatesCheckResult] = []
    for sym in symbols:
        path = manifests_dir / f"candidates_{sym}.json"
        if not path.exists():
            results.append(
                CandidatesCheckResult(
                    symbol=sym,
                    exists=False,
                    valid=False,
                    error="file not found",
                )
            )
            continue

        try:
            raw = path.read_text(encoding="utf-8")
            manifest = CandidatesManifest.model_validate_json(raw)
            results.append(
                CandidatesCheckResult(
                    symbol=sym,
                    exists=True,
                    valid=True,
                    n_candidates=len(manifest.candidates),
                )
            )
        except Exception as exc:  # noqa: BLE001
            results.append(
                CandidatesCheckResult(
                    symbol=sym,
                    exists=True,
                    valid=False,
                    error=str(exc),
                )
            )

    return results


def compute_exit_code(results: list[CandidatesCheckResult]) -> int:
    """Return 0 if all ok, 1 if any failed.

    Args:
        results: List from verify_outputs().

    Returns:
        0 on full success; 1 if any result is not ok.
    """
    return 0 if all(r.ok for r in results) else 1


def print_summary(results: list[CandidatesCheckResult]) -> None:
    """Print a human-readable per-symbol summary to stdout.

    Args:
        results: List from verify_outputs().
    """
    print("\n" + "=" * 60)
    print("Stage-0 output verification summary")
    print("=" * 60)
    for r in results:
        status = "OK" if r.ok else "FAIL"
        if r.ok:
            cache_tag = " (from cache)" if r.from_cache else ""
            msg = f"{r.n_candidates} candidates{cache_tag}"
        elif not r.exists:
            msg = f"MISSING — {r.error}"
        else:
            msg = f"INVALID — {r.error}"
        print(f"  [{status}] {r.symbol}: {msg}")

    total = len(results)
    passed = sum(1 for r in results if r.ok)
    print(f"\n{passed}/{total} symbols passed.")
    if passed < total:
        print("Stage 0 FAILED: one or more candidate manifests are missing or invalid.")
    else:
        print("Stage 0 PASSED: all candidate manifests present and valid.")
    print("=" * 60)


# ─── Swarm invocation (thin shell, not unit-tested) ───────────────────────────


def run_swarm(vars_dict: dict, timeout: int = SWARM_TIMEOUT_S) -> str:
    """Invoke ``vibe-trading --swarm-run crypto_factor_lab`` and return stdout.

    The CLI is at ``<repo-root>/agent/cli.py`` and must be run with
    cwd=<repo-root>/agent so its ``src.*`` imports resolve correctly.

    Args:
        vars_dict: User-vars dict to pass as JSON to the CLI.
        timeout:   Subprocess wall-clock timeout in seconds.

    Returns:
        Captured stdout string.

    Raises:
        subprocess.TimeoutExpired: If the swarm does not finish within timeout.
        subprocess.CalledProcessError: If the CLI exits non-zero.
    """
    agent_dir = _CFG_REPO_ROOT / "agent"
    cli_path = agent_dir / "cli.py"
    vars_json = json.dumps(vars_dict, ensure_ascii=False)

    cmd = [sys.executable, str(cli_path), "--swarm-run", SWARM_PRESET, vars_json]
    print(
        f"[stage0] invoking swarm: {SWARM_PRESET}  "
        f"(cwd={agent_dir}, timeout={timeout}s)"
    )
    completed = subprocess.run(
        cmd,
        cwd=str(agent_dir),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=timeout,
    )
    if completed.returncode != 0:
        stderr_snippet = (completed.stderr or "")[:2000]
        print(
            f"[stage0] swarm subprocess exited with code {completed.returncode}.\n"
            f"stderr (first 2000 chars):\n{stderr_snippet}",
            file=sys.stderr,
        )
        raise subprocess.CalledProcessError(
            returncode=completed.returncode,
            cmd=cmd,
            output=completed.stdout,
            stderr=completed.stderr,
        )
    return completed.stdout or ""


# ─── Per-symbol processing ───────────────────────────────────────────────────


def _build_swarm_vars(
    sym_name: str, okx_swap: str, cfg: ResearchConfig
) -> tuple[dict[str, str], list[str], list[str]]:
    """Build the user_vars dict for the crypto_factor_lab swarm.

    Args:
        sym_name: Short lowercase symbol name, e.g. "eth".
        okx_swap: OKX perpetual swap ticker, e.g. "ETH-USDT-SWAP".
        cfg:      Loaded ResearchConfig.

    Returns:
        Tuple of (vars_dict, available_sources, available_transforms) where
        vars_dict is suitable for JSON serialisation into the CLI VARS_JSON arg,
        and the two lists are the same registries advertised to the swarm so
        filter_invalid_candidates uses identical data.
    """
    available_sources = [
        key
        for key, spec in SOURCE_REGISTRY.items()
        if spec.status == "available"
    ]
    available_transforms = list(TRANSFORM_REGISTRY.keys())

    vars_dict = {
        "target_universe": okx_swap,
        "signal_categories": "funding,basis,oi",
        "horizons_h": str(list(cfg.horizons_h)),
        "available_sources": ",".join(available_sources),
        "available_transforms": ",".join(available_transforms),
    }
    return vars_dict, available_sources, available_transforms


def _process_symbol(
    sym_name: str,
    okx_swap: str,
    cfg: ResearchConfig,
    manifests_dir: Path,
) -> CandidatesCheckResult:
    """Run stage-0 discovery for one symbol, with retry and cache check.

    Steps:
      1. cache_hit check — return early if cached.
      2. run_swarm with built vars_dict.
      3. parse_candidates_json — retry once on ValueError with explicit JSON prompt.
      4. filter_invalid_candidates — print warnings for filtered entries.
      5. Pydantic-validate each candidate as FactorCandidate.
      6. Build CandidatesManifest and write candidates_<sym>.json.
      7. On any failure after retry: write candidates_<sym>.failed.json and
         print a bold-red warning.

    Args:
        sym_name:      Short lowercase symbol name.
        okx_swap:      OKX swap ticker.
        cfg:           Loaded ResearchConfig.
        manifests_dir: Path to research/manifests/.

    Returns:
        CandidatesCheckResult for this symbol.
    """
    # ── 1. Cache check ────────────────────────────────────────────────────────
    if cache_hit(manifests_dir, sym_name, cfg.discovery_cache_days):
        print(f"[stage0] {sym_name}: cache hit, skipping swarm")
        path = manifests_dir / f"candidates_{sym_name}.json"
        try:
            raw = path.read_text(encoding="utf-8")
            manifest = CandidatesManifest.model_validate_json(raw)
            return CandidatesCheckResult(
                symbol=sym_name,
                exists=True,
                valid=True,
                n_candidates=len(manifest.candidates),
                from_cache=True,
            )
        except Exception as exc:  # noqa: BLE001
            # Cache file exists but is corrupt — fall through to re-run.
            print(
                f"[stage0] {sym_name}: cached file is corrupt ({exc}), "
                "re-running swarm."
            )

    # ── 2. Build vars and run swarm ───────────────────────────────────────────
    print(f"[stage0] {sym_name}: running swarm...")
    vars_dict, available_sources, available_transforms = _build_swarm_vars(sym_name, okx_swap, cfg)

    try:
        stdout = run_swarm(vars_dict)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        return _write_failed(
            manifests_dir,
            sym_name,
            f"Swarm subprocess failed: {exc}",
        )

    # ── 3. Parse JSON (with one retry on failure) ─────────────────────────────
    raw_candidates: list[dict]
    try:
        raw_candidates = parse_candidates_json(stdout)
    except ValueError as first_exc:
        print(
            f"[stage0] {sym_name}: JSON parse failed ({first_exc}), retrying with "
            "strict JSON prompt..."
        )
        # Append a directive to vars and re-invoke the swarm.
        retry_vars = dict(vars_dict)
        retry_vars["extra_instruction"] = (
            "請嚴格輸出 JSON，不要其他文字"
        )
        try:
            stdout2 = run_swarm(retry_vars)
            raw_candidates = parse_candidates_json(stdout2)
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
            return _write_failed(
                manifests_dir,
                sym_name,
                f"Swarm subprocess failed on retry: {exc}",
            )
        except ValueError as retry_exc:
            return _write_failed(
                manifests_dir,
                sym_name,
                f"JSON parse failed after retry: {retry_exc}",
            )

    # ── 4. Filter invalid candidates ──────────────────────────────────────────
    valid_dicts, filter_warnings = filter_invalid_candidates(
        raw_candidates, available_sources, available_transforms
    )
    for warn in filter_warnings:
        print(warn)

    # ── 5. Pydantic-validate each candidate ───────────────────────────────────
    validated_candidates: list[FactorCandidate] = []
    pydantic_errors: list[str] = []
    for raw_c in valid_dicts:
        try:
            validated_candidates.append(FactorCandidate.model_validate(raw_c))
        except Exception as exc:  # noqa: BLE001
            name = raw_c.get("name", "<unknown>")
            pydantic_errors.append(f"  candidate '{name}': {exc}")

    if pydantic_errors:
        print(
            f"[stage0] {sym_name}: {len(pydantic_errors)} candidate(s) failed "
            "Pydantic validation and were dropped:"
        )
        for err in pydantic_errors:
            print(err)

    if not validated_candidates:
        return _write_failed(
            manifests_dir,
            sym_name,
            "No valid candidates remained after filtering and validation.",
        )

    # ── 6. Write CandidatesManifest ───────────────────────────────────────────
    manifest = CandidatesManifest(
        symbol=sym_name,
        generated_at=datetime.now(timezone.utc),
        source_swarm_run=None,  # run id extraction not required for stage 0
        candidates=validated_candidates,
    )

    out_path = manifests_dir / f"candidates_{sym_name}.json"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        manifest.model_dump_json(indent=2),
        encoding="utf-8",
    )
    print(
        f"[stage0] {sym_name}: wrote {len(validated_candidates)} candidates "
        f"→ {out_path}"
    )

    return CandidatesCheckResult(
        symbol=sym_name,
        exists=True,
        valid=True,
        n_candidates=len(validated_candidates),
    )


def _write_failed(
    manifests_dir: Path,
    sym_name: str,
    error_msg: str,
) -> CandidatesCheckResult:
    """Write a .failed.json marker and print a bold-red warning.

    Args:
        manifests_dir: Path to research/manifests/.
        sym_name:      Short lowercase symbol name.
        error_msg:     Human-readable error summary.

    Returns:
        CandidatesCheckResult with ok=False.
    """
    failed_path = manifests_dir / f"candidates_{sym_name}.failed.json"
    manifests_dir.mkdir(parents=True, exist_ok=True)
    failed_payload = {
        "symbol": sym_name,
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "error": error_msg,
    }
    try:
        failed_path.write_text(
            json.dumps(failed_payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"[stage0] {sym_name}: could not write failed marker: {exc}", file=sys.stderr)

    # Bold-red warning for pipeline visibility.
    print(
        f"{_RED}[WARN] stage0 FAILED for {sym_name} "
        f"— stage1 will use LEGACY_FACTORS{_RESET}"
    )
    return CandidatesCheckResult(
        symbol=sym_name,
        exists=False,
        valid=False,
        error=error_msg,
    )


# ─── Main entry point ─────────────────────────────────────────────────────────


def main() -> None:
    """Stage-0 entry point: discover factor candidates, verify, report, exit."""
    parser = argparse.ArgumentParser(
        description="Stage-0 factor discovery runner."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore cache and re-run swarm for all symbols.",
    )
    args = parser.parse_args()

    # RESEARCH_FORCE_DISCOVERY env var also forces re-run.
    force = args.force or bool(os.environ.get("RESEARCH_FORCE_DISCOVERY", ""))

    cfg: ResearchConfig = load_config()
    manifests_dir = _CFG_REPO_ROOT / "research" / "manifests"

    # Override cache TTL when --force / env var is set.
    effective_cache_days = 0 if force else cfg.discovery_cache_days

    # Build a patched cfg with the effective cache days (we only shadow the field
    # for the process_symbol call — cfg itself is frozen).
    effective_cfg = dataclasses.replace(cfg, discovery_cache_days=effective_cache_days)

    print("=" * 60)
    print("Stage 0 — Factor Discovery")
    print("=" * 60)
    print(
        f"Config: period={cfg.period}d  horizons={list(cfg.horizons_h)}  "
        f"symbols={cfg.symbol_names()}"
    )
    print(
        f"Cache TTL: {effective_cache_days} days "
        f"({'disabled — force mode' if force else 'enabled'})"
    )
    print(f"Output directory: {manifests_dir}")

    results: list[CandidatesCheckResult] = []
    for sym_cfg in cfg.symbols:
        result = _process_symbol(
            sym_name=sym_cfg.name,
            okx_swap=sym_cfg.okx_swap,
            cfg=effective_cfg,
            manifests_dir=manifests_dir,
        )
        results.append(result)

    # Final verification pass (reads manifests from disk to double-check).
    verified = verify_outputs(manifests_dir, cfg.symbol_names())

    # Propagate from_cache flag from processing results to verify results.
    cache_flags = {r.symbol: r.from_cache for r in results}
    for vr in verified:
        vr.from_cache = cache_flags.get(vr.symbol, False)

    print_summary(verified)

    exit_code = compute_exit_code(verified)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
