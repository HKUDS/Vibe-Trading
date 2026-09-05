"""Run-manifest integrity checks for Harness reports."""

from __future__ import annotations

from src.governance.manifest import RunManifest

from .artifacts import ArtifactBundle
from .schema import Verdict, VerdictStatus


def manifest_verdict(bundle: ArtifactBundle) -> Verdict:
    """Verify the persisted methodology hash and expose its comparison fields."""
    if "manifest" in bundle.errors:
        return Verdict(
            VerdictStatus.INVALID_ARTIFACT,
            "methodology.manifest_integrity",
            True,
            bundle.errors["manifest"],
            ("run_manifest.json",),
        )
    if "manifest" not in bundle.present:
        return Verdict(
            VerdictStatus.NOT_EVALUABLE,
            "methodology.manifest_integrity",
            True,
            None,
            ("run_manifest.json",),
        )
    try:
        manifest = RunManifest.from_dict(bundle.manifest or {})
        valid = manifest.verify_hash()
    except (KeyError, TypeError, ValueError) as exc:
        return Verdict(
            VerdictStatus.INVALID_ARTIFACT,
            "methodology.manifest_integrity",
            True,
            str(exc),
            ("run_manifest.json",),
        )
    observed = {
        "valid": valid,
        "manifest_hash": manifest.manifest_hash,
        "tool_count": len(manifest.tools.tool_names),
        "tools_hash": manifest.tools.tools_hash,
    }
    return Verdict(
        VerdictStatus.PASS if valid else VerdictStatus.INVALID_ARTIFACT,
        "methodology.manifest_integrity",
        True,
        observed,
        ("run_manifest.json",),
    )
