from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


DEFAULT_OFFICE_PATH = Path.home() / ".vibe-trading" / "pixel-office" / "office_state.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Agent:
    id: str
    name: str
    role: str
    status: str = "idle"
    load: int = 0
    specialities: List[str] = field(default_factory=list)
    office: str = "trading-floor"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Task:
    id: str
    title: str
    description: str
    workstream: str = "trading"
    priority: str = "normal"
    owner: str = "ops"
    status: str = "queued"
    assigned_to: Optional[str] = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    result: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class OfficeManager:
    """Simple runtime for delegating work among Pixel Agents.

    The manager stores state in a JSON file so it is easy to inspect, version,
    and extend later with a web dashboard or a broker automation layer.
    """

    def __init__(self, storage_path: Optional[str | Path] = None):
        self.storage_path = Path(storage_path) if storage_path is not None else DEFAULT_OFFICE_PATH
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        self.state = self._load_state()

    def _load_state(self) -> Dict[str, Any]:
        if not self.storage_path.exists():
            return {"office_name": "Pixel Trading Office", "created_at": _utc_now(), "agents": [], "tasks": []}

        try:
            with self.storage_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except json.JSONDecodeError:
            return {"office_name": "Pixel Trading Office", "created_at": _utc_now(), "agents": [], "tasks": []}

        payload.setdefault("agents", [])
        payload.setdefault("tasks", [])
        return payload

    def _save_state(self) -> None:
        self.storage_path.parent.mkdir(parents=True, exist_ok=True)
        with self.storage_path.open("w", encoding="utf-8") as handle:
            json.dump(self.state, handle, indent=2, ensure_ascii=False)
            handle.write("\n")

    def add_agent(
        self,
        *,
        agent_id: str,
        name: str,
        role: str,
        specialties: Optional[List[str]] = None,
        office: str = "trading-floor",
    ) -> Agent:
        agent = Agent(
            id=agent_id,
            name=name,
            role=role,
            specialities=specialties or [],
            office=office,
        )
        agents = self.state.setdefault("agents", [])
        for idx, existing in enumerate(agents):
            if existing.get("id") == agent.id:
                agents[idx] = agent.to_dict()
                self._save_state()
                return agent
        agents.append(agent.to_dict())
        self._save_state()
        return agent

    def create_task(
        self,
        *,
        task_id: str,
        title: str,
        description: str,
        workstream: str = "trading",
        priority: str = "normal",
        owner: str = "ops",
    ) -> Task:
        task = Task(
            id=task_id,
            title=title,
            description=description,
            workstream=workstream,
            priority=priority,
            owner=owner,
        )
        tasks = self.state.setdefault("tasks", [])
        tasks.append(task.to_dict())
        self._save_state()
        return task

    def find_agent(self, agent_id: str) -> Optional[Dict[str, Any]]:
        for agent in self.state.get("agents", []):
            if agent.get("id") == agent_id:
                return agent
        return None

    def _compatible_agent(self, task: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        role = task.get("workstream")
        for agent in self.state.get("agents", []):
            if agent.get("status") != "idle":
                continue
            if role in {"trading", "research"} and agent.get("role") in {"research", "execution"}:
                return agent
            if role == "risk" and agent.get("role") == "risk":
                return agent
            if role == "execution" and agent.get("role") == "execution":
                return agent
        return None

    def assign_task(self, task_id: str, agent_id: Optional[str] = None) -> Optional[Task]:
        tasks = self.state.get("tasks", [])
        task_index = next((idx for idx, item in enumerate(tasks) if item.get("id") == task_id), None)
        if task_index is None:
            return None

        task = tasks[task_index]
        agent = None
        if agent_id:
            agent = self.find_agent(agent_id)
        else:
            agent = self._compatible_agent(task)

        if agent is None:
            return None

        task["assigned_to"] = agent["id"]
        task["status"] = "assigned"
        task["updated_at"] = _utc_now()

        for existing in self.state["agents"]:
            if existing.get("id") == agent["id"]:
                existing["status"] = "busy"
                existing["load"] = int(existing.get("load", 0)) + 1
                break

        self._save_state()
        return Task(**task)

    def complete_task(self, task_id: str, result: str) -> Optional[Task]:
        tasks = self.state.get("tasks", [])
        task_index = next((idx for idx, item in enumerate(tasks) if item.get("id") == task_id), None)
        if task_index is None:
            return None

        task = tasks[task_index]
        task["status"] = "completed"
        task["result"] = result
        task["updated_at"] = _utc_now()
        assigned_to = task.get("assigned_to")

        if assigned_to:
            for agent in self.state["agents"]:
                if agent.get("id") == assigned_to:
                    agent["status"] = "idle"
                    break

        self._save_state()
        return Task(**task)

    def list_tasks(self) -> List[Dict[str, Any]]:
        return list(self.state.get("tasks", []))

    def list_agents(self) -> List[Dict[str, Any]]:
        return list(self.state.get("agents", []))

    def dashboard(self) -> Dict[str, Any]:
        tasks = self.list_tasks()
        agents = self.list_agents()
        completed = sum(1 for task in tasks if task.get("status") == "completed")
        pending = sum(1 for task in tasks if task.get("status") in {"queued", "assigned"})
        return {
            "office_name": self.state.get("office_name", "Pixel Trading Office"),
            "agent_count": len(agents),
            "task_count": len(tasks),
            "busy_agents": sum(1 for agent in agents if agent.get("status") == "busy"),
            "idle_agents": sum(1 for agent in agents if agent.get("status") == "idle"),
            "completed": completed,
            "pending": pending,
            "agents": agents,
            "tasks": tasks,
        }


if __name__ == "__main__":
    manager = OfficeManager()
    print(json.dumps(manager.dashboard(), indent=2, ensure_ascii=False))
