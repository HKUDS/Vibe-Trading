"""Ready-to-run research playbooks for the scheduled-research scheduler.

A playbook is a markdown file with a YAML frontmatter header, living in the
``playbooks/`` data directory beside this module. The frontmatter is the
catalogue record (name, description, suggested cadence, the data capabilities
a run needs); the body is the instruction text that becomes
``ScheduledResearchJob.prompt`` verbatim.

Two properties every template is written around, both forced by how the
scheduler actually runs a job (``executor.py`` dispatches ``job.prompt`` through
``src/api/scheduled_routes.py::_dispatch_scheduled_research_job``):

* The prompt is persisted once at creation and re-sent unchanged on every fire,
  so nothing may be baked in that is only true on the authoring day. Every
  template resolves "today" at run time.
* No template names a tool. A playbook states the data *capability* it needs in
  plain language and lets the agent route to whatever tool provides it, so the
  templates survive changes to the tool surface.

Discovery order: the directory named by ``VIBE_TRADING_PLAYBOOK_DIR`` (when
set) is searched before the bundled directory, and a user file wins on slug
collision -- the override rule user skills already follow.

Note on naming: this module and the data directory are both called
``playbooks``. A directory without ``__init__.py`` is only a namespace-package
candidate, which the import system consults *after* file loaders, so
``import src.scheduled_research.playbooks`` always resolves to this module.
``tests/test_research_playbooks.py`` pins that.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

import yaml

from src.config.accessor import get_env_config
from src.scheduled_research.models import (
    JobStatus,
    ScheduledResearchJob,
    validate_schedule,
    validate_timezone,
    validate_timezone_shape,
)

_PLAYBOOK_DIR_ENV = "VIBE_TRADING_PLAYBOOK_DIR"
_BUNDLED_DIR = Path(__file__).resolve().parent / "playbooks"

# Opening ---, the YAML block, closing ---, then the body. Deliberately stricter
# than src.agent.frontmatter: playbook metadata carries block sequences of
# natural-language phrases (which contain commas), and that parser's inline
# ``[a, b]`` form would shred them.
_FRONTMATTER_RE = re.compile(r"^---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n(.*))?$", re.DOTALL)
_PLACEHOLDER_RE = re.compile(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_REQUIRED_META = ("name", "description", "suggested_schedule", "data_capabilities")
# One substituted variable is user text pasted into a prompt that is persisted
# and replayed forever; cap it so a paste accident cannot bloat every run.
_MAX_VARIABLE_CHARS = 4000

# Sentinel for "caller did not pass a timezone", distinct from an explicit None
# (which means UTC and is a legitimate override of a suggested zone).
_KEEP = object()


class PlaybookError(ValueError):
    """Raised when a playbook file is malformed or used with bad arguments."""


class PlaybookNotFoundError(PlaybookError):
    """Raised when no playbook matches a requested slug."""


@dataclass(frozen=True)
class ResearchPlaybook:
    """One parsed playbook template.

    Attributes:
        slug: Filename stem, the stable id used by the CLI and REST layers.
        name: Human-readable title from the frontmatter.
        description: One-line summary for catalogue listings.
        suggested_schedule: Default schedule string, in the scheduler's format
            (interval milliseconds or a 5-field cron expression).
        suggested_timezone: Default IANA timezone key for cron evaluation, or
            ``None`` for UTC.
        markets: Market tags this playbook targets.
        data_capabilities: Plain-language descriptions of the data a run needs.
            Deliberately not tool names -- routing is the agent's job.
        variables: Declared placeholder names mapped to their default text.
        body: Instruction text, with ``{{placeholders}}`` unresolved.
        path: File the playbook was loaded from.
    """

    slug: str
    name: str
    description: str
    suggested_schedule: str
    suggested_timezone: Optional[str]
    markets: Tuple[str, ...]
    data_capabilities: Tuple[str, ...]
    variables: Dict[str, str] = field(default_factory=dict)
    body: str = ""
    path: Optional[Path] = None

    def render(self, variables: Optional[Mapping[str, Any]] = None) -> str:
        """Return the instruction body with placeholders substituted.

        Args:
            variables: Overrides keyed by declared variable name. A key that
                is not declared by this playbook is an error rather than a
                silent no-op. A blank value falls back to the declared default.

        Returns:
            The prompt text to hand to the scheduler.

        Raises:
            PlaybookError: If an undeclared variable is supplied or a value
                exceeds the length cap.
        """
        values = dict(self.variables)
        for key, raw in (variables or {}).items():
            if key not in values:
                raise PlaybookError(
                    f"playbook {self.slug!r} has no variable {key!r}; declared: {sorted(values)}"
                )
            text = str(raw).strip()
            if len(text) > _MAX_VARIABLE_CHARS:
                raise PlaybookError(
                    f"playbook variable {key!r} is {len(text)} chars; the cap is {_MAX_VARIABLE_CHARS}"
                )
            if text:
                values[key] = text
        # Every placeholder in the body was checked against ``variables`` at
        # load time, so this substitution cannot leave one behind.
        return _PLACEHOLDER_RE.sub(lambda m: values[m.group(1)], self.body)

    def to_job(
        self,
        *,
        job_id: Optional[str] = None,
        schedule: Optional[str] = None,
        timezone: Any = _KEEP,
        variables: Optional[Mapping[str, Any]] = None,
        config: Optional[Mapping[str, Any]] = None,
        next_run_at: Optional[int] = None,
        now_ms: Optional[int] = None,
    ) -> ScheduledResearchJob:
        """Build a schedulable job from this playbook.

        The result is ready for ``ScheduledResearchJobStore.upsert`` and mirrors
        what ``POST /scheduled-runs`` builds, including its first-fire rule: a
        cron job carrying a timezone first fires at its first authored
        occurrence, while interval jobs and timezone-less jobs fire immediately.

        Args:
            job_id: Explicit job id. Defaults to a slug-prefixed unique id.
            schedule: Schedule override. Defaults to ``suggested_schedule``.
            timezone: Timezone override. Omit to keep ``suggested_timezone``;
                pass ``None`` explicitly to force UTC.
            variables: Placeholder overrides, as for :meth:`render`.
            config: Session config forwarded to the agent run. A ``playbook``
                provenance key is added when the caller did not set one;
                ``AgentConfigOverride`` ignores unknown keys
                (``src/config/schema.py`` ``extra="ignore"``), so this is inert
                for config resolution.
            next_run_at: Explicit first-fire epoch-ms, bypassing the rule above.
            now_ms: Injectable clock for tests, in epoch milliseconds.

        Returns:
            A ``PENDING`` :class:`ScheduledResearchJob`.

        Raises:
            PlaybookError: If a supplied variable is invalid.
            ValueError: If the schedule or timezone is malformed, or the cron
                expression has no occurrence within the executor's search
                window.
        """
        resolved_schedule = (schedule if schedule is not None else self.suggested_schedule).strip()
        validate_schedule(resolved_schedule)
        tz = self.suggested_timezone if timezone is _KEEP else timezone
        validate_timezone(tz)

        now = int(time.time() * 1000) if now_ms is None else now_ms
        if next_run_at is None:
            next_run_at = now
            if tz is not None and not resolved_schedule.isdigit():
                # Imported here, not at module scope: the executor pulls in the
                # env config and the tool-redaction module (~0.5s), which a CLI
                # that only lists the catalogue should not pay for.
                from src.scheduled_research.executor import next_due

                next_run_at = next_due(resolved_schedule, now, tz)

        job_config: Dict[str, Any] = dict(config or {})
        job_config.setdefault("playbook", self.slug)

        return ScheduledResearchJob(
            id=job_id or f"playbook-{self.slug}-{uuid.uuid4().hex[:8]}",
            prompt=self.render(variables),
            schedule=resolved_schedule,
            next_run_at=next_run_at,
            status=JobStatus.PENDING,
            created_at=now,
            config=job_config,
            timezone=tz,
        )

    def to_dict(self, include_body: bool = False) -> Dict[str, Any]:
        """Return a JSON-serializable catalogue record.

        Args:
            include_body: Include the raw instruction body. Off by default so
                a catalogue listing stays small.

        Returns:
            A plain dict suitable for a REST response or CLI rendering.
        """
        data: Dict[str, Any] = {
            "slug": self.slug,
            "name": self.name,
            "description": self.description,
            "suggested_schedule": self.suggested_schedule,
            "suggested_timezone": self.suggested_timezone,
            "markets": list(self.markets),
            "data_capabilities": list(self.data_capabilities),
            "variables": dict(self.variables),
        }
        if include_body:
            data["body"] = self.body
        return data


def _string_list(value: Any, key: str, path: Path) -> Tuple[str, ...]:
    """Coerce a frontmatter value to a tuple of non-empty strings."""
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list) or not value:
        raise PlaybookError(f"playbook {path}: {key!r} must be a non-empty list of strings")
    items = tuple(str(item).strip() for item in value)
    if any(not item for item in items):
        raise PlaybookError(f"playbook {path}: {key!r} contains an empty entry")
    return items


def load_playbook_file(path: Path) -> ResearchPlaybook:
    """Parse one playbook markdown file.

    Args:
        path: Path to a ``.md`` playbook file.

    Returns:
        The parsed :class:`ResearchPlaybook`.

    Raises:
        PlaybookError: If the filename is not a valid slug, the file has no
            frontmatter, is missing a required key, declares a malformed
            schedule/timezone, has an empty body, or uses a placeholder it
            never declared.
        OSError: If the file cannot be read.
    """
    # Checked here, not only in get_playbook: the filename IS the slug, so a
    # file that list_playbooks would happily enumerate but get_playbook would
    # refuse (``My_Playbook.md``) must fail loudly at load rather than appear
    # in the catalogue as an entry nobody can select.
    if not _SLUG_RE.fullmatch(path.stem):
        raise PlaybookError(
            f"playbook {path}: filename stem {path.stem!r} is not a valid slug; "
            "use lowercase letters, digits and hyphens (e.g. 'my-playbook.md')"
        )
    # utf-8-sig, not utf-8: a BOM left by a Windows editor would otherwise sit
    # in front of the opening '---' and surface as a bogus "missing frontmatter".
    text = path.read_text(encoding="utf-8-sig")
    match = _FRONTMATTER_RE.match(text)
    if match is None:
        raise PlaybookError(f"playbook {path}: missing '---' YAML frontmatter header")

    try:
        meta = yaml.safe_load(match.group(1) or "") or {}
    except yaml.YAMLError as exc:
        raise PlaybookError(f"playbook {path}: frontmatter is not valid YAML ({exc})") from exc
    if not isinstance(meta, dict):
        raise PlaybookError(f"playbook {path}: frontmatter must be a mapping")

    missing = [key for key in _REQUIRED_META if not meta.get(key)]
    if missing:
        raise PlaybookError(f"playbook {path}: frontmatter is missing {missing}")

    body = (match.group(2) or "").strip()
    if not body:
        raise PlaybookError(f"playbook {path}: body is empty")

    schedule = str(meta["suggested_schedule"]).strip()
    try:
        validate_schedule(schedule)
    except ValueError as exc:
        raise PlaybookError(f"playbook {path}: {exc}") from exc

    tz = meta.get("suggested_timezone")
    tz = str(tz).strip() or None if tz is not None else None
    # Shape only, not resolution: a bundled zone key that this host's tz
    # database lacks must not make the whole catalogue unlistable. to_job()
    # resolves it, the same place POST /scheduled-runs does.
    validate_timezone_shape(tz)

    raw_variables = meta.get("variables") or {}
    if not isinstance(raw_variables, dict):
        raise PlaybookError(f"playbook {path}: 'variables' must be a mapping of name to default")
    variables = {str(k): str(v) for k, v in raw_variables.items()}

    undeclared = sorted(set(_PLACEHOLDER_RE.findall(body)) - set(variables))
    if undeclared:
        raise PlaybookError(f"playbook {path}: body uses undeclared variables {undeclared}")

    return ResearchPlaybook(
        slug=path.stem,
        name=str(meta["name"]).strip(),
        description=str(meta["description"]).strip(),
        suggested_schedule=schedule,
        suggested_timezone=tz,
        markets=_string_list(meta.get("markets") or ["global"], "markets", path),
        data_capabilities=_string_list(meta["data_capabilities"], "data_capabilities", path),
        variables=variables,
        body=body,
        path=path,
    )


def playbook_dirs(directory: Optional[Path] = None) -> List[Path]:
    """Return the directories searched for playbooks, highest priority first.

    Args:
        directory: When given, the only directory searched.

    Returns:
        A list of directory paths (which may not exist).
    """
    if directory is not None:
        return [Path(directory).expanduser()]
    dirs: List[Path] = []
    override = get_env_config().paths.vibe_trading_playbook_dir.strip()
    if override:
        dirs.append(Path(override).expanduser())
    dirs.append(_BUNDLED_DIR)
    return dirs


def list_playbooks(directory: Optional[Path] = None) -> List[ResearchPlaybook]:
    """Load every available playbook, sorted by slug.

    A slug found in an earlier directory shadows the same slug later, so a user
    file overrides the bundled one.

    Args:
        directory: Search only this directory instead of the default chain.

    Returns:
        The parsed playbooks, sorted by slug.

    Raises:
        PlaybookError: If any discovered file fails to parse. A broken playbook
            is surfaced, not skipped -- silently dropping it would hide the
            file the user is trying to fix.
    """
    found: Dict[str, ResearchPlaybook] = {}
    for candidate_dir in playbook_dirs(directory):
        if not candidate_dir.is_dir():
            continue
        for path in sorted(candidate_dir.glob("*.md")):
            if path.stem not in found:
                found[path.stem] = load_playbook_file(path)
    return [found[slug] for slug in sorted(found)]


def get_playbook(slug: str, directory: Optional[Path] = None) -> ResearchPlaybook:
    """Load a single playbook by slug.

    Args:
        slug: Playbook slug (its filename stem).
        directory: Search only this directory instead of the default chain.

    Returns:
        The parsed playbook.

    Raises:
        PlaybookNotFoundError: If the slug is malformed or no file matches.
        PlaybookError: If the matching file fails to parse.
    """
    if not isinstance(slug, str) or not _SLUG_RE.fullmatch(slug):
        raise PlaybookNotFoundError(f"invalid playbook slug: {slug!r}")
    for candidate_dir in playbook_dirs(directory):
        path = candidate_dir / f"{slug}.md"
        if path.is_file():
            return load_playbook_file(path)
    available = ", ".join(p.slug for p in list_playbooks(directory)) or "none"
    raise PlaybookNotFoundError(f"unknown playbook {slug!r}; available: {available}")


def build_job(slug: str, directory: Optional[Path] = None, **kwargs: Any) -> ScheduledResearchJob:
    """Load a playbook by slug and turn it into a schedulable job.

    Args:
        slug: Playbook slug.
        directory: Search only this directory instead of the default chain.
        **kwargs: Forwarded to :meth:`ResearchPlaybook.to_job`.

    Returns:
        A ``PENDING`` :class:`ScheduledResearchJob`.

    Raises:
        PlaybookNotFoundError: If no playbook matches *slug*.
        PlaybookError: If the file fails to parse or a variable is invalid.
    """
    return get_playbook(slug, directory).to_job(**kwargs)
