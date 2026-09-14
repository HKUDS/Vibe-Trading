"""Trust Layer run card generator for backtest runs."""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


SCHEMA_VERSION = "0.1"
# Largest single structured metric the card will carry, counted in BYTES of the
# JSON the card actually writes (indented, sorted, non-ASCII kept literal). The
# card is an at-a-glance artefact read on every run, so a structured metric that
# exceeds this is named under `_OMITTED_KEY` rather than allowed to grow the
# card without bound.
_STRUCTURED_METRIC_MAX_BYTES = 4096
# Reserved: records which structured metrics were dropped. A metric of this name
# is itself omitted-and-named rather than published, so the record can never be
# silently overwritten by one.
_OMITTED_KEY = "_omitted"
# Metrics whose value is also stored under a dedicated top-level card key, so
# carrying them here would publish the same object twice. Only ``validation``
# qualifies: ``card["validation"] = metrics["validation"]``.
#
# ``warnings`` deliberately does NOT: the card's top-level ``warnings`` comes
# from ``config["content_filter_warnings"]``, whereas the options engine puts
# its own annualisation warnings under ``metrics["warnings"]`` - a different
# list with no other home. Excluding it would silently discard them.
_DEDICATED_CARD_KEYS = ("validation",)
BACKTEST_SUMMARY_KEYS = (
    "codes",
    "start_date",
    "end_date",
    "interval",
    "engine",
    "initial_cash",
    "source",
)


def write_run_card(
    run_dir: Path,
    config: Mapping[str, Any],
    metrics: Mapping[str, Any],
    *,
    data_sources: Sequence[str] | None = None,
    strategy_path: Path | None = None,
    warnings: Sequence[str] | None = None,
    artifact_refs: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Write JSON and Markdown run cards for a backtest run.

    Args:
        run_dir: Directory where run_card.json and run_card.md are written.
        config: Full backtest configuration. Only a summary and hash are stored.
        metrics: Backtest metrics. Scalar values are stored; ``validation`` is
            stored under its own top-level key. Non-scalar metrics are carried
            in ``structured_metrics``.
        data_sources: Data sources used by the run.
        strategy_path: Optional strategy source file to hash for reproducibility.
        warnings: Optional warnings to include in the card.
        artifact_refs: Optional IRR-AGL artifact references.

    Returns:
        The run card payload written to ``run_card.json``.
    """
    run_dir = Path(run_dir)
    run_dir.mkdir(parents=True, exist_ok=True)

    config_file = run_dir / "config.json"
    reproducibility: dict[str, Any] = {
        "config_hash": _file_hash(config_file) if config_file.exists() else _json_hash(config),
    }
    if strategy_path is not None:
        strategy_file = Path(strategy_path)
        if strategy_file.exists() and strategy_file.is_file():
            reproducibility["strategy_hash"] = _file_hash(strategy_file)

    card: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "generated_at": _utc_now(),
        "run_dir": str(run_dir),
        "backtest": _backtest_summary(config),
        "reproducibility": reproducibility,
        "data_sources": list(data_sources or []),
        "metrics": _scalar_metrics(metrics),
        "warnings": list(warnings or []),
        "artifacts": _list_artifacts(run_dir),
    }
    normalized_refs = _normalize_artifact_refs(artifact_refs)
    if normalized_refs:
        card["artifact_refs"] = normalized_refs
    structured = _structured_metrics(metrics)
    if structured:
        card["structured_metrics"] = structured
    if "validation" in metrics:
        card["validation"] = metrics["validation"]

    card = _json_safe(card)
    json_path = run_dir / "run_card.json"
    md_path = run_dir / "run_card.md"
    json_path.write_text(
        json.dumps(
            card,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            default=str,
            allow_nan=False,
        )
        + "\n",
        encoding="utf-8",
    )
    md_path.write_text(_render_markdown(card), encoding="utf-8")
    return card


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _json_hash(value: Mapping[str, Any]) -> str:
    payload = json.dumps(
        {key: val for key, val in value.items() if not str(key).startswith("_")},
        sort_keys=True,
        default=str,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _backtest_summary(config: Mapping[str, Any]) -> dict[str, Any]:
    return {key: config.get(key) for key in BACKTEST_SUMMARY_KEYS if key in config}


def _scalar_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Scalar metrics, minus any whose value has a dedicated top-level key."""
    return {
        key: value
        for key, value in metrics.items()
        if key not in _DEDICATED_CARD_KEYS and _is_scalar(value)
    }


def _structured_metrics(metrics: Mapping[str, Any]) -> dict[str, Any]:
    """Keep the non-scalar metrics that ``metrics`` cannot hold.

    ``metrics`` is a deliberately scalar-only, stable surface, so a dict- or
    list-shaped metric is filtered out of it. Discarding those outright loses
    evidence the engine authors for card readers: for example
    ``unfilled_plan_rejections_by_symbol`` names the sleeve and reason behind a
    rejection, while the scalar ``unfilled_plan_rejections`` beside it is an
    anonymous count. They are carried here instead, excluding
    ``_DEDICATED_CARD_KEYS`` - those already have their own top-level key and
    would otherwise be published twice.

    The card is written at the end of an already-completed run, so this must
    never raise: a value that cannot be serialised, or that is larger than
    ``_STRUCTURED_METRIC_MAX_BYTES``, is omitted and named under
    ``_OMITTED_KEY`` rather than allowed to fail the run or bloat the card. The
    bound is what keeps ``by_symbol``-style maps from turning into a
    multi-hundred-kilobyte card as new structured metrics are added.

    Args:
        metrics: Backtest metrics as passed to :func:`write_run_card`.

    Returns:
        The non-scalar metrics that fit, or an empty dict when there are none.
    """
    structured = {
        key: value
        for key, value in metrics.items()
        if key not in _DEDICATED_CARD_KEYS and not _is_scalar(value)
    }
    if not structured:
        return {}
    kept: dict[str, Any] = {}
    omitted: list[str] = []
    for key, value in structured.items():
        if key == _OMITTED_KEY:
            omitted.append(key)
            continue
        try:
            size = _serialised_size(value)
        except (TypeError, ValueError, RecursionError):
            omitted.append(key)
            continue
        if size > _STRUCTURED_METRIC_MAX_BYTES:
            omitted.append(key)
        else:
            kept[key] = value
    if omitted:
        kept[_OMITTED_KEY] = sorted(omitted)
    return kept


def _serialised_size(value: Any) -> int:
    """UTF-8 bytes this value occupies in the card's own JSON formatting.

    Measured on the normalised value (``_json_safe``, as the writer applies)
    and in bytes: ``len()`` on the string counts characters, which understates
    a CJK value roughly threefold, and the card is written indented rather than
    compact, so a compact dump would understate it again.
    """
    rendered = json.dumps(
        _json_safe(value),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
        default=str,
    )
    return len(rendered.encode("utf-8"))


def _json_safe(value: Any) -> Any:
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if isinstance(value, Mapping):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return value


def _is_scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _list_artifacts(run_dir: Path) -> list[dict[str, Any]]:
    candidates: list[Path] = []
    for relative in (Path("config.json"), Path("code/signal_engine.py")):
        path = run_dir / relative
        if path.exists() and path.is_file():
            candidates.append(path)

    artifacts_dir = run_dir / "artifacts"
    if artifacts_dir.exists() and artifacts_dir.is_dir():
        candidates.extend(path for path in artifacts_dir.rglob("*") if path.is_file())

    artifacts = []
    for path in sorted(candidates, key=lambda item: item.relative_to(run_dir).as_posix()):
        artifacts.append(
            {
                "path": path.relative_to(run_dir).as_posix(),
                "size_bytes": path.stat().st_size,
                "sha256": _file_hash(path),
            }
        )
    return artifacts


def _normalize_artifact_refs(artifact_refs: Sequence[Mapping[str, Any]] | None) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for ref in artifact_refs or []:
        if hasattr(ref, "model_dump"):
            value = ref.model_dump(mode="json")  # type: ignore[attr-defined]
        else:
            value = dict(ref)
        refs.append(_json_safe(value))
    return refs


def _render_markdown(card: Mapping[str, Any]) -> str:
    lines = [
        "# Backtest Run Card",
        "",
        f"Generated: {card['generated_at']}",
        f"Run directory: `{card['run_dir']}`",
        "",
        "## Backtest Summary",
    ]

    backtest = card.get("backtest", {})
    if backtest:
        lines.extend(f"- {key}: {value}" for key, value in backtest.items())
    else:
        lines.append("- No backtest summary fields provided.")

    lines.extend(["", "## Reproducibility"])
    reproducibility = card.get("reproducibility", {})
    lines.append(f"- config_hash: `{reproducibility.get('config_hash', '')}`")
    if "strategy_hash" in reproducibility:
        lines.append(f"- strategy_hash: `{reproducibility['strategy_hash']}`")

    lines.extend(["", "## Data Sources"])
    data_sources = card.get("data_sources", [])
    lines.extend(f"- {source}" for source in data_sources) if data_sources else lines.append("- None recorded.")

    lines.extend(["", "## Metrics"])
    metric_values = card.get("metrics", {})
    lines.extend(f"- {key}: {value}" for key, value in metric_values.items()) if metric_values else lines.append("- No scalar metrics recorded.")

    structured = card.get("structured_metrics", {})
    if structured:
        lines.extend(["", "## Structured metrics", ""])
        lines.append(
            "Non-scalar metrics, which the `metrics` block cannot hold - carried so "
            "they can be inspected by key instead of only as a flattened count."
        )
        lines.append("")
        # Deliberately not an inline code span: a value containing a backtick
        # would close the span early and corrupt the section. Formatted like
        # the scalar lines above instead.
        for key, value in structured.items():
            rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
            lines.append(f"- {key}: {rendered}")

    lines.extend(["", "## Validation"])
    if "validation" in card:
        validation = card["validation"]
        if isinstance(validation, Mapping):
            lines.extend(f"- {key}: {value}" for key, value in validation.items())
        else:
            lines.append(f"- {validation}")
    else:
        lines.append("- Not present.")

    warnings = card.get("warnings", [])
    if warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in warnings)

    lines.extend(["", "## Artifacts"])
    artifacts = card.get("artifacts", [])
    if artifacts:
        lines.extend(
            f"- `{artifact['path']}` ({artifact['size_bytes']} bytes, sha256 `{artifact['sha256']}`)"
            for artifact in artifacts
        )
    else:
        lines.append("- None found.")

    artifact_refs = card.get("artifact_refs", [])
    if artifact_refs:
        lines.extend(["", "## IRR Artifact Refs"])
        for ref in artifact_refs:
            if isinstance(ref, Mapping):
                label = ref.get("artifact_id", "")
                artifact_type = ref.get("artifact_type", "")
                digest = ref.get("sha256", "")
                uri = ref.get("uri", "")
                lines.append(f"- `{label}` ({artifact_type}, sha256 `{digest}`, uri `{uri}`)")
            else:
                lines.append(f"- {ref}")

    return "\n".join(lines) + "\n"
