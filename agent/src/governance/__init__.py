"""Governance primitives: run manifests + a tamper-evident hash-chained ledger.

Two independent pieces, both standalone (no dependency on the protected
``src/agent/`` tree, no wall-clock reads):

- ``manifest``: :func:`build_run_manifest` fingerprints a run's methodology
  composition (system prompt hash, injected-skill content hashes, tool
  registry, key package versions) into one deterministic ``manifest_hash``,
  and :func:`diff_manifests` names exactly what changed between two runs.
- ``ledger``: :func:`append_record` / :func:`verify_chain` implement a
  generic hash-chained, fsynced, append-only JSONL ledger. ``src/live/audit.py``
  wires this in as an opt-in ``chain=True`` mode on its existing
  ``write_live_action`` — see that module's docstring for the integration.

Neither module writes into a real run directory or the live-action ledger
by itself; callers supply paths/composition data explicitly.
"""

from src.governance.ledger import (
    EXPORT_FORMAT,
    GENESIS_PREV_HASH,
    ChainBreak,
    ChainVerificationResult,
    LedgerCorruptionError,
    append_record,
    build_export,
    compute_record_hash,
    export_chain_to_file,
    verify_chain,
    verify_export,
)
from src.governance.manifest import (
    ManifestDiff,
    RunManifest,
    SkillRecord,
    ToolRegistrySnapshot,
    build_run_manifest,
    collect_key_package_versions,
    diff_manifests,
)

__all__ = [
    # ledger
    "EXPORT_FORMAT",
    "GENESIS_PREV_HASH",
    "ChainBreak",
    "ChainVerificationResult",
    "LedgerCorruptionError",
    "append_record",
    "build_export",
    "compute_record_hash",
    "export_chain_to_file",
    "verify_chain",
    "verify_export",
    # manifest
    "ManifestDiff",
    "RunManifest",
    "SkillRecord",
    "ToolRegistrySnapshot",
    "build_run_manifest",
    "collect_key_package_versions",
    "diff_manifests",
]
