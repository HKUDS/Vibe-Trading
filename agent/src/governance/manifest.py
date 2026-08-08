"""Run manifest: a content-addressed fingerprint of "what produced this run".

A :class:`RunManifest` answers "under what methodology was that number
produced" without carrying the methodology's raw, possibly sensitive
content: the system prompt is stored only as a hash, each injected skill is
stored as ``(name, content_hash)`` so a later diff can name exactly which
skill's body changed, the tool registry is stored as its sorted name list
plus a hash, and a curated set of package versions pins the numeric/runtime
environment. Composition in, one deterministic hash out.

**Hash scope is the composition, not the instance.** ``timestamp`` and
``run_id`` are recorded on the manifest for provenance but are deliberately
EXCLUDED from ``manifest_hash``. Two runs on different days under the exact
same system prompt / skills / tools / package versions must hash identically
— that repeatability is the entire point (it lets you ask "did methodology
change between run A and run B", not just "did time pass between them"). If
timestamp were hashed, the manifest hash would never repeat and
:func:`diff_manifests` would report a spurious change on every single call.

**No hidden clock.** Per the governance task's hard requirement, this module
never calls ``datetime.now()`` / ``time.time()``. The caller (whoever builds
the manifest at the moment a run starts) supplies ``timestamp`` explicitly.

**This module is intentionally standalone.** It does not import
``src.agent.*`` (protected tree) or reach into a live tool registry / skills
loader itself — it accepts already-extracted composition data (raw system
prompt text to hash, a name->content mapping for skills, an iterable of tool
names, a package-version mapping) so it can be unit tested and reused
without any run-time wiring. Wiring this into the actual agent loop is
explicitly OUT OF SCOPE for this module (the loop lives under the protected
``src/agent/`` tree) — see "Mount points" below for where a future change
would plug in.

Mount points for a future integration (NOT implemented here)::

    1. System prompt: wherever ``src/agent/context.py`` (or
       ``src/agent/loop.py``) finalizes the system prompt string for a run,
       pass that raw string as ``system_prompt=`` to
       :func:`build_run_manifest`. Only the hash is ever persisted.

    2. Skills actually injected: the same context-building step (and/or
       ``src/tools/load_skill_tool.py`` for skills pulled in mid-run via the
       ``load_skill`` tool) knows which :class:`src.agent.skills.Skill`
       objects were injected this turn. Pass
       ``{skill.name: skill.body for skill in injected}`` as ``skills=``.

    3. Tool registry composition: ``src.tools.build_registry(...)`` (this
       one lives under the OPEN ``src/tools/`` tree, not protected) already
       exposes ``ToolRegistry.tool_names`` — see
       ``agent/src/agent/tools.py:87`` and the project CLAUDE.md line
       "measured off ``build_registry().tool_names`` on a default checkout".
       Pass that list as ``tool_names=``.

    4. Package versions: call :func:`collect_key_package_versions` once per
       process/run start and pass the result as ``package_versions=``.

    5. Timestamp: the run/session start time the loop already tracks (e.g.
       a ``started_at`` captured when the run begins) should be passed as
       ``timestamp=``; this module must never generate it itself.

    6. Persistence: analogous to how ``src.agent.trace.TraceWriter`` writes
       ``trace.jsonl`` durably next to a run, a future change could persist
       ``RunManifest.to_json()`` as ``manifest.json`` in the same run/session
       directory (fsync'd the same way trace records are). Not implemented
       here — that directory-resolution logic lives in the protected
       ``src/agent/`` tree.
"""

from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping, Sequence

__all__ = [
    "SkillRecord",
    "ToolRegistrySnapshot",
    "RunManifest",
    "ManifestDiff",
    "build_run_manifest",
    "diff_manifests",
    "collect_key_package_versions",
]

#: Curated distributions whose version can shift a computed number or change
#: available functionality. Rationale per package:
#:   - "vibe-trading-ai": pins the code release itself.
#:   - "numpy" / "pandas" / "scipy": the numeric kernel every metric,
#:     optimizer, and quantlib formula (agent/src/quantlib/) runs on top of —
#:     a minor version bump in any of them can silently shift a computed
#:     number (e.g. a different BLAS path, a changed default ddof).
#:   - "langchain" / "langchain-core": fix the tool-calling / message
#:     contract the ReAct loop (agent/src/agent/loop.py) depends on.
#:   - "statsmodels" / "arch": back the optional econometrics surface
#:     (stationarity/cointegration/GARCH in agent/src/quantlib/) gated
#:     behind the "stats" extra; recorded as ``None`` when not installed,
#:     which is itself methodology-relevant (those functions were simply
#:     unavailable for this run).
_KEY_PACKAGES: tuple[str, ...] = (
    "vibe-trading-ai",
    "langchain",
    "langchain-core",
    "numpy",
    "pandas",
    "scipy",
    "statsmodels",
    "arch",
)


def _canonical_json(obj: Any) -> str:
    """Serialize ``obj`` deterministically for hashing (sorted keys, compact)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _sha256_hex(text: str) -> str:
    """Return the hex SHA-256 digest of ``text``."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _hash_prefixed(text: str) -> str:
    """Return a self-describing ``sha256:<hex>`` digest of ``text``."""
    return f"sha256:{_sha256_hex(text)}"


@dataclass(frozen=True)
class SkillRecord:
    """One injected skill's identity + content fingerprint.

    Only the hash is stored, never the body — a skill can carry arbitrary
    (possibly long, possibly sensitive-in-context) text, and the manifest is
    meant to be small and safe to persist/share.

    Attributes:
        name: Skill name (``Skill.name`` in ``src.agent.skills``).
        content_hash: ``sha256:<hex>`` of the exact body text that was
            injected for this run.
    """

    name: str
    content_hash: str

    @classmethod
    def from_content(cls, name: str, content: str) -> "SkillRecord":
        """Build a record by hashing ``content`` now.

        Args:
            name: Skill name.
            content: Full skill body text as actually injected.

        Returns:
            A new :class:`SkillRecord`.
        """
        return cls(name=name, content_hash=_hash_prefixed(content))


@dataclass(frozen=True)
class ToolRegistrySnapshot:
    """The tool registry's composition for a run: sorted names + one hash.

    Attributes:
        tool_names: Deduplicated tool names, sorted for determinism.
        tools_hash: ``sha256:<hex>`` over the canonical JSON of
            ``tool_names`` — changes if any tool is added, removed, or
            renamed.
    """

    tool_names: tuple[str, ...]
    tools_hash: str

    @classmethod
    def from_names(cls, tool_names: Iterable[str]) -> "ToolRegistrySnapshot":
        """Build a snapshot from an (unordered, possibly duplicated) iterable.

        Args:
            tool_names: Tool names, e.g. ``ToolRegistry.tool_names``.

        Returns:
            A new :class:`ToolRegistrySnapshot` with names sorted.
        """
        names = tuple(sorted(set(tool_names)))
        digest = _hash_prefixed(_canonical_json(list(names)))
        return cls(tool_names=names, tools_hash=digest)


def _pairs(mapping: Mapping[str, Any] | None) -> tuple[tuple[str, Any], ...]:
    """Return ``mapping`` as a sorted, hashable tuple of ``(key, value)`` pairs."""
    return tuple(sorted((mapping or {}).items()))


def _compute_manifest_hash(
    *,
    system_prompt_hash: str,
    skills: tuple[SkillRecord, ...],
    tools: ToolRegistrySnapshot,
    package_versions: tuple[tuple[str, Any], ...],
    extra: tuple[tuple[str, Any], ...],
) -> str:
    """Hash the run composition (NOT ``run_id``/``timestamp`` — see module docstring).

    ``tools.tools_hash`` alone (rather than re-embedding the full name list)
    is sufficient input here: it is itself a deterministic hash of the
    sorted tool-name list, so any tool addition/removal/rename already
    changes ``tools_hash`` and therefore this hash too.
    """
    payload = {
        "system_prompt_hash": system_prompt_hash,
        "skills": [[record.name, record.content_hash] for record in skills],
        "tools_hash": tools.tools_hash,
        "package_versions": list(package_versions),
        "extra": list(extra),
    }
    return _hash_prefixed(_canonical_json(payload))


@dataclass(frozen=True)
class RunManifest:
    """Immutable fingerprint of one run's methodology composition.

    Attributes:
        run_id: Caller-supplied run/session identifier. NOT part of
            ``manifest_hash``.
        timestamp: Caller-supplied ISO-8601 (or otherwise caller-defined)
            timestamp string. NOT part of ``manifest_hash`` — see module
            docstring for why.
        system_prompt_hash: ``sha256:<hex>`` of the exact system prompt text.
        skills: Sorted-by-name tuple of :class:`SkillRecord`.
        tools: :class:`ToolRegistrySnapshot` of the tool registry.
        package_versions: Sorted ``(name, version_or_None)`` pairs.
        extra: Sorted ``(key, value)`` pairs for caller-defined composition
            dimensions not covered above (e.g. provider/model name). Small,
            non-sensitive strings only — unlike the system prompt/skills,
            these are stored raw, not hashed, because they are meant to be
            directly readable in a diff.
        manifest_hash: ``sha256:<hex>`` over everything above except
            ``run_id``/``timestamp``. Two manifests with identical
            composition always produce the identical ``manifest_hash``.
    """

    run_id: str
    timestamp: str
    system_prompt_hash: str
    skills: tuple[SkillRecord, ...]
    tools: ToolRegistrySnapshot
    package_versions: tuple[tuple[str, Any], ...]
    extra: tuple[tuple[str, Any], ...]
    manifest_hash: str

    def verify_hash(self) -> bool:
        """Recompute ``manifest_hash`` from the other fields and compare.

        Useful after deserializing a persisted manifest (``from_dict`` /
        ``from_json`` trust the stored hash at load time; this method is the
        integrity check that actually re-derives it).

        Returns:
            ``True`` when the stored ``manifest_hash`` matches a fresh
            recomputation, ``False`` if the manifest was hand-edited/corrupted.
        """
        expected = _compute_manifest_hash(
            system_prompt_hash=self.system_prompt_hash,
            skills=self.skills,
            tools=self.tools,
            package_versions=self.package_versions,
            extra=self.extra,
        )
        return expected == self.manifest_hash

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable representation.

        Returns:
            A plain dict; round-trips through :meth:`from_dict`.
        """
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "system_prompt_hash": self.system_prompt_hash,
            "skills": [
                {"name": record.name, "content_hash": record.content_hash}
                for record in self.skills
            ],
            "tools": {
                "tool_names": list(self.tools.tool_names),
                "tools_hash": self.tools.tools_hash,
            },
            "package_versions": dict(self.package_versions),
            "extra": dict(self.extra),
            "manifest_hash": self.manifest_hash,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> "RunManifest":
        """Reconstruct a manifest from :meth:`to_dict` output.

        The stored ``manifest_hash`` is trusted as-is (not recomputed) —
        call :meth:`verify_hash` afterward to check it was not tampered with.

        Args:
            data: A mapping produced by :meth:`to_dict` (or an equivalent
                deserialized JSON object).

        Returns:
            A new :class:`RunManifest`.
        """
        skills = tuple(
            sorted(
                (
                    SkillRecord(name=item["name"], content_hash=item["content_hash"])
                    for item in data["skills"]
                ),
                key=lambda record: record.name,
            )
        )
        tools = ToolRegistrySnapshot(
            tool_names=tuple(data["tools"]["tool_names"]),
            tools_hash=data["tools"]["tools_hash"],
        )
        return cls(
            run_id=data["run_id"],
            timestamp=data["timestamp"],
            system_prompt_hash=data["system_prompt_hash"],
            skills=skills,
            tools=tools,
            package_versions=_pairs(data.get("package_versions")),
            extra=_pairs(data.get("extra")),
            manifest_hash=data["manifest_hash"],
        )

    def to_json(self, *, indent: int | None = None) -> str:
        """Serialize to a JSON string.

        Args:
            indent: Optional pretty-print indent; compact when ``None``.

        Returns:
            JSON text; round-trips through :meth:`from_json`.
        """
        return json.dumps(self.to_dict(), sort_keys=True, ensure_ascii=False, indent=indent)

    @classmethod
    def from_json(cls, text: str) -> "RunManifest":
        """Deserialize from :meth:`to_json` output.

        Args:
            text: JSON text.

        Returns:
            A new :class:`RunManifest`.
        """
        return cls.from_dict(json.loads(text))


def build_run_manifest(
    *,
    run_id: str,
    timestamp: str,
    system_prompt: str,
    skills: Mapping[str, str] | Sequence[SkillRecord] = (),
    tool_names: Iterable[str] = (),
    package_versions: Mapping[str, Any] | None = None,
    extra: Mapping[str, Any] | None = None,
) -> RunManifest:
    """Build a :class:`RunManifest` from raw run composition data.

    Args:
        run_id: Run/session identifier (provenance only, not hashed).
        timestamp: Caller-supplied timestamp string (provenance only, not
            hashed). This function never reads the wall clock itself.
        system_prompt: Full system prompt text; only its hash is kept.
        skills: Either a ``{name: content}`` mapping (the common case — the
            caller already has the injected skills' full bodies) or a
            pre-built sequence of :class:`SkillRecord`.
        tool_names: Tool registry names, e.g. ``ToolRegistry.tool_names``.
        package_versions: ``{package: version_or_None}``; see
            :func:`collect_key_package_versions` for a ready-made curated
            collector.
        extra: Small caller-defined composition dimensions (e.g.
            ``{"provider": "openrouter", "model": "deepseek/deepseek-v3.2"}``).

    Returns:
        A new :class:`RunManifest` with ``manifest_hash`` computed over the
        composition (excluding ``run_id``/``timestamp``).

    Raises:
        ValueError: ``run_id``/``timestamp`` is empty, or ``skills`` contains
            two records with the same name.
    """
    if not run_id or not run_id.strip():
        raise ValueError("run_id must not be empty")
    if not timestamp or not timestamp.strip():
        raise ValueError("timestamp must not be empty")

    if isinstance(skills, Mapping):
        skill_records = tuple(
            sorted(
                (SkillRecord.from_content(name, content) for name, content in skills.items()),
                key=lambda record: record.name,
            )
        )
    else:
        skill_records = tuple(sorted(skills, key=lambda record: record.name))
        names = [record.name for record in skill_records]
        if len(names) != len(set(names)):
            raise ValueError(f"duplicate skill names in manifest input: {names}")

    tools_snapshot = ToolRegistrySnapshot.from_names(tool_names)
    pv_pairs = _pairs(package_versions)
    extra_pairs = _pairs(extra)

    manifest_hash = _compute_manifest_hash(
        system_prompt_hash=_hash_prefixed(system_prompt),
        skills=skill_records,
        tools=tools_snapshot,
        package_versions=pv_pairs,
        extra=extra_pairs,
    )

    return RunManifest(
        run_id=run_id,
        timestamp=timestamp,
        system_prompt_hash=_hash_prefixed(system_prompt),
        skills=skill_records,
        tools=tools_snapshot,
        package_versions=pv_pairs,
        extra=extra_pairs,
        manifest_hash=manifest_hash,
    )


@dataclass(frozen=True)
class ManifestDiff:
    """What changed between two :class:`RunManifest` instances.

    Attributes:
        system_prompt_changed: Whether ``system_prompt_hash`` differs.
        skills_added: Skill names present in ``b`` but not ``a``.
        skills_removed: Skill names present in ``a`` but not ``b``.
        skills_changed: Skill names present in both whose ``content_hash``
            differs — the direct answer to "which skill's content changed".
        tools_added: Tool names present in ``b`` but not ``a``.
        tools_removed: Tool names present in ``a`` but not ``b``.
        package_version_changes: ``(package, old_version, new_version)``
            triples for every package whose recorded version differs
            (``None`` on either side means added/removed/not-installed).
        extra_changes: Same shape as ``package_version_changes`` for the
            ``extra`` composition dimensions.
        manifest_hash_changed: Whether the overall ``manifest_hash`` differs.
    """

    system_prompt_changed: bool
    skills_added: tuple[str, ...]
    skills_removed: tuple[str, ...]
    skills_changed: tuple[str, ...]
    tools_added: tuple[str, ...]
    tools_removed: tuple[str, ...]
    package_version_changes: tuple[tuple[str, Any, Any], ...]
    extra_changes: tuple[tuple[str, Any, Any], ...]
    manifest_hash_changed: bool

    @property
    def unchanged(self) -> bool:
        """Whether nothing at all differs between the two manifests."""
        return not (
            self.system_prompt_changed
            or self.skills_added
            or self.skills_removed
            or self.skills_changed
            or self.tools_added
            or self.tools_removed
            or self.package_version_changes
            or self.extra_changes
        )


def diff_manifests(a: RunManifest, b: RunManifest) -> ManifestDiff:
    """Diff two manifests, naming exactly what changed.

    Args:
        a: The earlier (or "baseline") manifest.
        b: The later (or "candidate") manifest.

    Returns:
        A :class:`ManifestDiff` describing every difference.
    """
    a_skills = {record.name: record.content_hash for record in a.skills}
    b_skills = {record.name: record.content_hash for record in b.skills}
    skills_added = tuple(sorted(set(b_skills) - set(a_skills)))
    skills_removed = tuple(sorted(set(a_skills) - set(b_skills)))
    skills_changed = tuple(
        sorted(
            name
            for name in set(a_skills) & set(b_skills)
            if a_skills[name] != b_skills[name]
        )
    )

    a_tools = set(a.tools.tool_names)
    b_tools = set(b.tools.tool_names)
    tools_added = tuple(sorted(b_tools - a_tools))
    tools_removed = tuple(sorted(a_tools - b_tools))

    a_pv = dict(a.package_versions)
    b_pv = dict(b.package_versions)
    pv_changes = tuple(
        (key, a_pv.get(key), b_pv.get(key))
        for key in sorted(set(a_pv) | set(b_pv))
        if a_pv.get(key) != b_pv.get(key)
    )

    a_extra = dict(a.extra)
    b_extra = dict(b.extra)
    extra_changes = tuple(
        (key, a_extra.get(key), b_extra.get(key))
        for key in sorted(set(a_extra) | set(b_extra))
        if a_extra.get(key) != b_extra.get(key)
    )

    return ManifestDiff(
        system_prompt_changed=a.system_prompt_hash != b.system_prompt_hash,
        skills_added=skills_added,
        skills_removed=skills_removed,
        skills_changed=skills_changed,
        tools_added=tools_added,
        tools_removed=tools_removed,
        package_version_changes=pv_changes,
        extra_changes=extra_changes,
        manifest_hash_changed=a.manifest_hash != b.manifest_hash,
    )


def collect_key_package_versions(
    extra_packages: Iterable[str] = (),
) -> dict[str, str | None]:
    """Look up installed versions for the curated methodology-relevant set.

    See :data:`_KEY_PACKAGES` for the selection and per-package rationale.
    Also records the running interpreter's version under the ``"python"``
    key, since numeric/floating-point behavior is not guaranteed identical
    across CPython versions either.

    This performs filesystem/package-metadata lookups but never reads the
    wall clock, so it is safe to call from a hash-composition path.

    Args:
        extra_packages: Additional distribution names to look up alongside
            the curated list (e.g. a provider SDK selected at runtime, such
            as ``langchain-anthropic`` or ``langchain-deepseek``).

    Returns:
        ``{distribution_name: version}``, with ``None`` when a distribution
        is not installed (itself methodology-relevant: e.g. ``arch`` absent
        means GARCH-backed quantlib functions were unavailable this run).
    """
    from importlib.metadata import PackageNotFoundError, version

    names = tuple(dict.fromkeys((*_KEY_PACKAGES, *extra_packages)))
    result: dict[str, str | None] = {"python": platform.python_version()}
    for name in names:
        try:
            result[name] = version(name)
        except PackageNotFoundError:
            result[name] = None
    return result
