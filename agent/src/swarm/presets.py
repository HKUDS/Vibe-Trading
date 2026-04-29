"""Swarm YAML preset loader.

Reads YAML preset files from the bundled ``presets/`` directory next to this
module and parses them into SwarmRun / SwarmAgentSpec / SwarmTask data models.
Keeping the YAMLs inside the ``src.swarm`` package guarantees identical
behavior under editable installs and built wheels.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

from src.swarm.models import RunStatus, SwarmAgentSpec, SwarmRun, SwarmTask, TaskStatus

PRESETS_DIR = Path(__file__).resolve().parent / "presets"


def load_preset(name: str) -> dict:
    """Load a YAML preset by name.

    Args:
        name: Preset name (without .yaml extension).

    Returns:
        Parsed YAML dict.

    Raises:
        FileNotFoundError: If the preset file does not exist.
    """
    path = PRESETS_DIR / f"{name}.yaml"
    if not path.exists():
        available = [p.stem for p in PRESETS_DIR.glob("*.yaml")] if PRESETS_DIR.exists() else []
        raise FileNotFoundError(
            f"Preset '{name}' not found at {path}. Available: {available}"
        )
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def list_presets() -> list[dict]:
    """Return summary info for all available presets.

    Returns:
        List of dicts with keys: name, title, description, agent_count, variables.
    """
    if not PRESETS_DIR.exists():
        return []

    results: list[dict] = []
    for path in sorted(PRESETS_DIR.glob("*.yaml")):
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception:
            continue

        results.append({
            "name": data.get("name", path.stem),
            "title": data.get("title", ""),
            "description": data.get("description", ""),
            "agent_count": len(data.get("agents", [])),
            "variables": data.get("variables", []),
        })

    return results


def build_run_from_preset(preset_name: str, user_vars: dict[str, str]) -> SwarmRun:
    """Create a SwarmRun from a preset with user variables applied.

    Steps:
        1. Load preset YAML
        2. Create SwarmAgentSpec list from agents section
        3. Create SwarmTask list from tasks section
        4. Generate run_id: f"swarm-{datetime}-{uuid[:8]}"
        5. Return SwarmRun with all fields populated

    Args:
        preset_name: Name of the preset to load.
        user_vars: User-provided variables for prompt template rendering.

    Returns:
        Fully constructed SwarmRun instance (status=pending).

    Raises:
        FileNotFoundError: If preset does not exist.
        ValueError: If preset YAML is malformed.
    """
    data = load_preset(preset_name)

    # Parse agents
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

    # Parse tasks, initialize blocked_by from depends_on
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
            status=status,
        ))

    # Generate run ID
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d-%H%M%S")
    short_uuid = uuid.uuid4().hex[:8]
    run_id = f"swarm-{ts}-{short_uuid}"

    return SwarmRun(
        id=run_id,
        preset_name=preset_name,
        status=RunStatus.pending,
        user_vars=user_vars,
        agents=agents,
        tasks=tasks,
        created_at=now.isoformat(),
    )
