"""Deterministic JSON and Markdown rendering for revision comparisons."""

from __future__ import annotations

import hashlib
import html
import json
import re
from typing import Any

from .models import ResearchArtifactExport


def _inline(value: object) -> str:
    """Render stored identifiers and metadata as literal text on one line."""
    single_line = html.escape(" ".join(str(value).splitlines()))
    return re.sub(r"([\\`*_\[\]])", r"\\\1", single_line)


def _fenced(content: str, language: str) -> str:
    longest_run = max((len(run) for run in re.findall(r"`+", content)), default=0)
    fence = "`" * max(3, longest_run + 1)
    return f"{fence}{language}\n{content}\n{fence}"


def _markdown_comparison(comparison: dict[str, Any]) -> str:
    content = comparison["content"]
    evidence = comparison["evidence"]
    metadata = comparison["metadata"]
    lines = [
        "# Research revision comparison",
        "",
        f"Artifact ID: {_inline(comparison['artifact_id'])}",
        "",
    ]
    for label, revision in (("From", comparison["from"]), ("To", comparison["to"])):
        lines.extend(
            [
                f"{label} revision: r{revision['revision_number']}",
                f"Revision ID: {_inline(revision['revision_id'])}",
                f"Created at: {_inline(revision['created_at'])}",
                f"Content SHA-256: {_inline(revision['content_hash'])}",
                f"Provenance SHA-256: {_inline(revision['provenance_hash'])}",
                "",
            ]
        )
    lines.extend(
        [
            "## Content",
            "",
            f"Changed: {'yes' if content['changed'] else 'no'}",
            f"Lines: {content['from_line_count']} -> {content['to_line_count']}",
            f"Newline style: {_inline(content['from_newline_style'])} -> {_inline(content['to_newline_style'])}",
            f"From SHA-256: {_inline(content['from_hash'])}",
            f"To SHA-256: {_inline(content['to_hash'])}",
            "",
        ]
    )
    if content["diff"]:
        lines.extend([_fenced("\n".join(content["diff"]), "diff"), ""])
    else:
        lines.extend(["No content changes.", ""])
    if content["truncated"]:
        lines.extend(
            [
                f"Diff truncated after {len(content['diff'])} generated lines. "
                "Full-content hashes and line counts cover the complete selected revisions.",
                "",
            ]
        )
    evidence_json = json.dumps(evidence, ensure_ascii=False, indent=2, allow_nan=False)
    lines.extend(
        [
            "## Evidence",
            "",
            f"Changed: {'yes' if evidence['changed'] else 'no'}",
            f"Added: {len(evidence['added'])}",
            f"Removed: {len(evidence['removed'])}",
            f"Unchanged: {evidence['unchanged_count']}",
            f"Order changed: {'yes' if evidence['order_changed'] else 'no'}",
            "",
            _fenced(evidence_json, "json"),
            "",
            "## Metadata",
            "",
        ]
    )
    if metadata:
        metadata_json = json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False)
        lines.extend([_fenced(metadata_json, "json"), ""])
    else:
        lines.extend(["No metadata changes.", ""])
    lines.extend(["Read-only comparison. Exporting does not revalidate research.", ""])
    return "\n".join(lines)


def render_comparison_export(comparison: dict[str, Any], format: str = "json") -> ResearchArtifactExport:
    """Render one exact comparison without adding volatile export metadata."""
    artifact_id = comparison["artifact_id"]
    from_number = comparison["from"]["revision_number"]
    to_number = comparison["to"]["revision_number"]
    stem = f"{artifact_id}-r{from_number}-r{to_number}"
    if format == "json":
        content = (
            json.dumps(
                {
                    "schema_version": 1,
                    "kind": "research_artifact_revision_comparison",
                    "comparison": comparison,
                },
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
            + "\n"
        )
        filename = f"{stem}.json"
        media_type = "application/json"
    elif format == "markdown":
        content = _markdown_comparison(comparison)
        filename = f"{stem}.md"
        media_type = "text/markdown; charset=utf-8"
    else:
        raise ValueError("export format must be 'json' or 'markdown'")
    return ResearchArtifactExport(
        filename=filename,
        media_type=media_type,
        content=content,
        sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
    )
