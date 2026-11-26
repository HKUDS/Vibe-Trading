"""Swarm YAML preset loader."""

from __future__ import annotations

import uuid
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from string import Formatter

import yaml

from src.swarm.models import RunStatus, SwarmAgentSpec, SwarmRun, SwarmTask, TaskStatus
from src.swarm.task_store import topological_layers, validate_dag

PRESETS_DIR = Path(__file__).resolve().parent / "presets"
#: Search upgrade-safe user presets first so they can override bundled names.
USER_PRESETS_DIR = Path.home() / ".vibe-trading" / "swarm" / "presets"
_INTERNAL_TEMPLATE_VARS = {"upstream_context"}


def _redact_home(path: Path) -> str:
    """Hide the absolute home directory from user-facing errors (CWE-209)."""
    try:
        return "~/" + str(path.relative_to(Path.home()))
    except ValueError:
        return str(path)


def _validate_preset_name(name: str) -> str:
    """Reject names that are empty or could escape a presets directory."""
    cleaned = (name or "").strip()
    if not cleaned or cleaned in {".", ".."} or "/" in cleaned or "\\" in cleaned:
        raise ValueError(f"invalid preset name: {name!r}")
    return cleaned


def _preset_search_dirs() -> tuple[Path, ...]:
    """Directories searched for presets, highest priority first."""
    return (USER_PRESETS_DIR, PRESETS_DIR)


def resolve_preset_path(name: str) -> Path | None:
    """Locate a preset YAML file, giving the user directory precedence.

    Args:
        name: Preset name without the .yaml extension.

    Returns:
        Path to the first matching file, or None if neither directory has one.

    Raises:
        ValueError: If the name is blank, dot-only as . or .., or contains a path separator.
    """
    cleaned = _validate_preset_name(name)
    for directory in _preset_search_dirs():
        path = directory / f"{cleaned}.yaml"
        if path.is_file():
            return path
    return None


def load_preset(name: str) -> dict:
    """Load a YAML preset by name (user directory first, then bundled).

    Args:
        name: Preset name without the .yaml extension.

    Returns:
        Parsed YAML content.

    Raises:
        ValueError: If the name is blank, is . or .., or contains a path separator.
        FileNotFoundError: If the preset file exists in neither the user nor bundled directory.
        yaml.YAMLError: If the file cannot be parsed as YAML.
    """
    path = resolve_preset_path(name)
    if path is None:
        available = sorted({
            p.stem
            for directory in _preset_search_dirs()
            if directory.exists()
            for p in directory.glob("*.yaml")
        })
        raise FileNotFoundError(
            f"Preset {name!r} not found in {_redact_home(USER_PRESETS_DIR)} or "
            f"the bundled presets. Available: {available}"
        )
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def list_presets() -> list[dict]:
    """Return summary info for all available presets, sorted by name.

    Returns:
        Summary dictionaries with name, title, description, agent_count, variables, and source. A
        user preset overrides a bundled preset with the same file stem.
    """
    by_stem: dict[str, dict] = {}
    for directory, source in ((PRESETS_DIR, "bundled"), (USER_PRESETS_DIR, "user")):
        if not directory.exists():
            continue
        for path in sorted(directory.glob("*.yaml")):
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except Exception:
                continue
            if not isinstance(data, dict):
                continue
            # Later iteration (user) intentionally replaces bundled stems.
            by_stem[path.stem] = {
                "name": data.get("name", path.stem),
                "title": data.get("title", ""),
                "description": data.get("description", ""),
                "agent_count": len(data.get("agents", [])),
                "variables": data.get("variables", []),
                "source": source,
            }

    return sorted(by_stem.values(), key=lambda entry: entry["name"])


def _declared_variable_names(raw_variables: list) -> set[str]:
    """Extract variable names from the YAML variables section."""
    names: set[str] = set()
    for item in raw_variables:
        if isinstance(item, dict):
            name = item.get("name")
        else:
            name = str(item)
        if name:
            names.add(str(name))
    return names


def _template_variables(template: str) -> set[str]:
    """Return Python format fields referenced by a prompt template."""
    variables: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template or ""):
        if not field_name:
            continue
        root = field_name.split(".", 1)[0].split("[", 1)[0]
        if root and root not in _INTERNAL_TEMPLATE_VARS:
            variables.add(root)
    return variables


def inspect_preset(name: str) -> dict:
    """Validate a swarm preset and return a dry-run execution plan.

    Args:
        name: Preset name without the .yaml extension.

    Returns:
        Plan with agent and task details, topological layers, variable use, and validation errors or
        warnings.
    """
    data = load_preset(name)
    run = build_run_from_preset(name, {})

    errors: list[str] = []
    warnings: list[str] = []

    agent_ids = [agent.id for agent in run.agents]
    task_ids = [task.id for task in run.tasks]
    agent_id_set = set(agent_ids)
    task_id_set = set(task_ids)

    for duplicate in sorted(item for item, count in Counter(agent_ids).items() if count > 1):
        errors.append(f"Duplicate agent id: {duplicate}")
    for duplicate in sorted(item for item, count in Counter(task_ids).items() if count > 1):
        errors.append(f"Duplicate task id: {duplicate}")

    for task in run.tasks:
        if task.agent_id not in agent_id_set:
            errors.append(f"Task '{task.id}' references unknown agent '{task.agent_id}'")
        for upstream_task_id in task.input_tasks().values():
            if upstream_task_id not in task_id_set:
                errors.append(
                    f"Task '{task.id}' input_from references unknown task '{upstream_task_id}'"
                )

    layers: list[list[str]] = []
    try:
        validate_dag(run.tasks)
        layers = topological_layers(run.tasks)
    except ValueError as exc:
        errors.append(str(exc))

    declared_variables = _declared_variable_names(data.get("variables", []))
    used_variables: set[str] = set()
    for task in run.tasks:
        try:
            used_variables.update(_template_variables(task.prompt_template) - task.input_from.keys())
        except ValueError as exc:
            errors.append(f"Task '{task.id}' has invalid prompt template: {exc}")

    missing_declarations = sorted(used_variables - declared_variables)
    unused_declarations = sorted(declared_variables - used_variables)
    if missing_declarations:
        warnings.append(
            "Prompt templates use undeclared variables: " + ", ".join(missing_declarations)
        )
    if unused_declarations:
        warnings.append(
            "Declared variables are not used by task prompt templates: "
            + ", ".join(unused_declarations)
        )

    task_agent = {task.id: task.agent_id for task in run.tasks}
    return {
        "name": data.get("name", name),
        "title": data.get("title", ""),
        "description": data.get("description", ""),
        "prefetch_grounding": run.prefetch_grounding,
        "valid": not errors,
        "errors": errors,
        "warnings": warnings,
        "variables": sorted(declared_variables),
        "used_variables": sorted(used_variables),
        "agents": [
            {"id": agent.id, "role": agent.role, "tools": agent.tools, "skills": agent.skills}
            for agent in run.agents
        ],
        "tasks": [
            {
                "id": task.id,
                "agent_id": task.agent_id,
                "depends_on": task.depends_on,
                "input_from": task.input_from,
                "tools": task.tools,
            }
            for task in run.tasks
        ],
        "layers": [
            [{"task_id": task_id, "agent_id": task_agent.get(task_id, "")} for task_id in layer]
            for layer in layers
        ],
    }


def missing_required_variables(data: dict, user_vars: dict[str, str]) -> list[str]:
    """Name the preset's required variables that the caller left absent or blank.

    Args:
        data: Parsed preset YAML.
        user_vars: Variables supplied for the run.

    Returns:
        Required variable names, in declaration order, without a non-blank string value.
    """
    return [item["name"] for item in data.get("variables", [])
            if isinstance(item, dict) and item.get("required") and item.get("name")
            and not (isinstance(user_vars.get(item["name"]), str) and user_vars[item["name"]].strip())]


def build_run_from_preset(
    preset_name: str, user_vars: dict[str, str], *, validate_variables: bool = False,
) -> SwarmRun:
    """Create a pending swarm run from a preset and user variables.

    Args:
        preset_name: Name of the preset to load.
        user_vars: User-provided variables saved for prompt template rendering.
        validate_variables: Refuse a run whose required variables are missing. Inspection builds
            an unfilled plan without it; execution always sets it.

    Returns:
        New run with a generated ID, agent specifications, and tasks initialized as pending or
        blocked by dependencies.

    Raises:
        ValueError: If a required variable is missing (with validate_variables), a task's tools
            exceed its agent's whitelist, or an input selection is malformed.
    """
    data = load_preset(preset_name)
    if validate_variables:
        missing = missing_required_variables(data, user_vars)
        if missing:
            described = {v.get("name"): v.get("description", "") for v in data.get("variables", []) if isinstance(v, dict)}
            raise ValueError(
                "Missing required preset variables; pass them in `variables`: "
                + "; ".join(f"{name} ({described[name]})" if described.get(name) else name for name in missing)
            )

    agents: list[SwarmAgentSpec] = []
    for agent_data in data.get("agents", []):
        agents.append(SwarmAgentSpec(
            id=agent_data["id"],
            role=agent_data.get("role", ""),
            system_prompt=agent_data.get("system_prompt", ""),
            tools=agent_data.get("tools", []),
            skills=agent_data.get("skills", []),
            max_iterations=agent_data.get("max_iterations", 25),
            timeout_seconds=agent_data.get("timeout_seconds", 300),
            model_name=agent_data.get("model_name"),
            max_retries=agent_data.get("max_retries", 2),
        ))

    tasks: list[SwarmTask] = []
    for task_data in data.get("tasks", []):
        depends_on = task_data.get("depends_on", [])
        status = TaskStatus.blocked if depends_on else TaskStatus.pending
        tasks.append(SwarmTask(
            id=task_data["id"],
            agent_id=task_data["agent_id"],
            prompt_template=task_data.get("prompt_template", ""),
            depends_on=depends_on,
            blocked_by=list(depends_on),
            input_from=task_data.get("input_from", {}),
            tools=task_data.get("tools"),
            status=status,
        ))

    agent_map = {agent.id: agent for agent in agents}
    for task in tasks:
        if task.agent_id in agent_map:
            task.effective_tools(agent_map[task.agent_id])

    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d-%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    run_id = f"swarm-{ts}-{short_uuid}"

    return SwarmRun(
        id=run_id,
        preset_name=preset_name,
        status=RunStatus.pending,
        user_vars=user_vars,
        prefetch_grounding=data.get("prefetch_grounding", True),
        agents=agents,
        tasks=tasks,
        created_at=now.isoformat(),
    )
