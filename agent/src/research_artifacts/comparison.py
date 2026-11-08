"""Deterministic comparisons between immutable research revisions."""

from __future__ import annotations

import difflib
import json
from collections import Counter
from itertools import islice
from typing import Any

from .models import ResearchArtifactRevision

_MAX_DIFF_LINES = 400
_METADATA_FIELDS = (
    "subject",
    "universe",
    "data_as_of",
    "verification_status",
    "completeness",
    "hypothesis_id",
    "goal_id",
    "session_id",
    "run_id",
)


def _canonical_json(value: object) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _revision_summary(revision: ResearchArtifactRevision) -> dict[str, Any]:
    return {
        "revision_id": revision.revision_id,
        "revision_number": revision.revision_number,
        "created_at": revision.created_at,
        "content_hash": revision.content_hash,
        "provenance_hash": revision.provenance_hash,
    }


def _newline_style(content: str) -> str:
    endings = {
        "crlf" if line.endswith("\r\n") else "lf" if line.endswith("\n") else "cr"
        for line in content.splitlines(keepends=True)
        if line.endswith(("\n", "\r"))
    }
    if not endings:
        return "none"
    return endings.pop() if len(endings) == 1 else "mixed"


def _diff_lines(
    from_revision: ResearchArtifactRevision,
    to_revision: ResearchArtifactRevision,
    *,
    show_line_endings: bool,
):
    raw_lines = difflib.unified_diff(
        from_revision.content.splitlines(keepends=True),
        to_revision.content.splitlines(keepends=True),
        fromfile=from_revision.revision_id,
        tofile=to_revision.revision_id,
        lineterm="",
    )
    visible_endings = {"\r\n": "\\r\\n", "\n": "\\n", "\r": "\\r"}
    for index, line in enumerate(raw_lines):
        is_header = index < 2 or line.startswith("@@")
        ending = "\r\n" if line.endswith("\r\n") else line[-1:] if line.endswith(("\n", "\r")) else ""
        text = line[: -len(ending)] if ending else line
        yield text + (visible_endings[ending] if show_line_endings and not is_header and ending else "")
        if not is_header and not ending:
            yield "\\ No newline at end of file"


def _content_comparison(
    from_revision: ResearchArtifactRevision,
    to_revision: ResearchArtifactRevision,
) -> dict[str, Any]:
    from_lines = from_revision.content.splitlines()
    to_lines = to_revision.content.splitlines()
    from_newline_style = _newline_style(from_revision.content)
    to_newline_style = _newline_style(to_revision.content)
    changed = from_revision.content != to_revision.content
    diff: list[str] = []
    truncated = False
    if changed:
        pending = list(
            islice(
                _diff_lines(
                    from_revision,
                    to_revision,
                    show_line_endings=from_newline_style != to_newline_style
                    or "mixed" in (from_newline_style, to_newline_style),
                ),
                _MAX_DIFF_LINES + 1,
            )
        )
        truncated = len(pending) > _MAX_DIFF_LINES
        diff = pending[:_MAX_DIFF_LINES]
    return {
        "changed": changed,
        "from_hash": from_revision.content_hash,
        "to_hash": to_revision.content_hash,
        "from_line_count": len(from_lines),
        "to_line_count": len(to_lines),
        "from_newline_style": from_newline_style,
        "to_newline_style": to_newline_style,
        "diff": diff,
        "truncated": truncated,
    }


def _ordered_unmatched(
    evidence: tuple[dict[str, Any], ...],
    unmatched: Counter[str],
) -> list[dict[str, Any]]:
    remaining = unmatched.copy()
    result: list[dict[str, Any]] = []
    for item in evidence:
        key = _canonical_json(item)
        if remaining[key] > 0:
            result.append(item)
            remaining[key] -= 1
    return result


def _evidence_comparison(
    from_revision: ResearchArtifactRevision,
    to_revision: ResearchArtifactRevision,
) -> dict[str, Any]:
    from_sequence = tuple(_canonical_json(item) for item in from_revision.evidence)
    to_sequence = tuple(_canonical_json(item) for item in to_revision.evidence)
    from_counts = Counter(from_sequence)
    to_counts = Counter(to_sequence)
    added = _ordered_unmatched(to_revision.evidence, to_counts - from_counts)
    removed = _ordered_unmatched(from_revision.evidence, from_counts - to_counts)
    order_changed = not added and not removed and from_sequence != to_sequence
    return {
        "added": added,
        "removed": removed,
        "unchanged_count": sum((from_counts & to_counts).values()),
        "order_changed": order_changed,
        "changed": bool(added or removed or order_changed),
    }


def compare_revisions(
    from_revision: ResearchArtifactRevision,
    to_revision: ResearchArtifactRevision,
) -> dict[str, Any]:
    """Compare two revisions without modifying content or revalidating research."""
    metadata = {
        field: {
            "from": getattr(from_revision, field),
            "to": getattr(to_revision, field),
        }
        for field in _METADATA_FIELDS
        if getattr(from_revision, field) != getattr(to_revision, field)
    }
    return {
        "artifact_id": from_revision.artifact_id,
        "from": _revision_summary(from_revision),
        "to": _revision_summary(to_revision),
        "content": _content_comparison(from_revision, to_revision),
        "evidence": _evidence_comparison(from_revision, to_revision),
        "metadata": metadata,
    }
