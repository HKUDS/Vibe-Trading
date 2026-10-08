from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.pixel_agents.office import DEFAULT_OFFICE_PATH, OfficeManager


def _build_parser() -> argparse.ArgumentParser:
    storage_parent = argparse.ArgumentParser(add_help=False)
    storage_parent.add_argument("--storage", type=str, default=str(DEFAULT_OFFICE_PATH), help="Path to the JSON office state")

    parser = argparse.ArgumentParser(description="Pixel Agents office manager", parents=[storage_parent])
    subparsers = parser.add_subparsers(dest="command")

    init_cmd = subparsers.add_parser("init", help="Initialize office state", parents=[storage_parent])
    init_cmd.set_defaults(action="init")

    add_agent_cmd = subparsers.add_parser("agent", help="Add an agent to the office", parents=[storage_parent])
    add_agent_cmd.add_argument("--id", required=True)
    add_agent_cmd.add_argument("--name", required=True)
    add_agent_cmd.add_argument("--role", required=True)
    add_agent_cmd.add_argument("--specialties", nargs="*", default=[])
    add_agent_cmd.add_argument("--office", default="trading-floor")
    add_agent_cmd.set_defaults(action="agent")

    task_cmd = subparsers.add_parser("task", help="Create a task for the office", parents=[storage_parent])
    task_cmd.add_argument("--id", required=True)
    task_cmd.add_argument("--title", required=True)
    task_cmd.add_argument("--description", required=True)
    task_cmd.add_argument("--workstream", default="trading")
    task_cmd.add_argument("--priority", default="normal")
    task_cmd.add_argument("--owner", default="ops")
    task_cmd.set_defaults(action="task")

    assign_cmd = subparsers.add_parser("assign", help="Assign a task to an agent", parents=[storage_parent])
    assign_cmd.add_argument("--task-id", required=True)
    assign_cmd.add_argument("--agent-id", default=None)
    assign_cmd.set_defaults(action="assign")

    complete_cmd = subparsers.add_parser("complete", help="Complete a task", parents=[storage_parent])
    complete_cmd.add_argument("--task-id", required=True)
    complete_cmd.add_argument("--result", required=True)
    complete_cmd.set_defaults(action="complete")

    list_cmd = subparsers.add_parser("list", help="List tasks and agents", parents=[storage_parent])
    list_cmd.set_defaults(action="list")

    dashboard_cmd = subparsers.add_parser("dashboard", help="Show the office dashboard", parents=[storage_parent])
    dashboard_cmd.set_defaults(action="dashboard")

    return parser


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()
    storage = Path(args.storage)
    manager = OfficeManager(storage)

    if args.command is None:
        parser.print_help()
        return

    if args.action == "init":
        if storage.exists():
            print(f"Office state already exists: {storage}")
            return
        manager = OfficeManager(storage)
        manager._save_state()
        print(f"Initialized Pixel office at {storage}")
        return

    if args.action == "agent":
        agent = manager.add_agent(
            agent_id=args.id,
            name=args.name,
            role=args.role,
            specialties=args.specialties,
            office=args.office,
        )
        print(json.dumps({"agent": agent.to_dict()}, indent=2, ensure_ascii=False))
        return

    if args.action == "task":
        task = manager.create_task(
            task_id=args.id,
            title=args.title,
            description=args.description,
            workstream=args.workstream,
            priority=args.priority,
            owner=args.owner,
        )
        print(json.dumps({"task": task.to_dict()}, indent=2, ensure_ascii=False))
        return

    if args.action == "assign":
        task = manager.assign_task(args.task_id, agent_id=args.agent_id)
        if task is None:
            print(f"No eligible agent available for task {args.task_id}")
            return
        print(json.dumps({"task": task.to_dict()}, indent=2, ensure_ascii=False))
        return

    if args.action == "complete":
        task = manager.complete_task(args.task_id, args.result)
        if task is None:
            print(f"Task not found: {args.task_id}")
            return
        print(json.dumps({"task": task.to_dict()}, indent=2, ensure_ascii=False))
        return

    if args.action == "list":
        print(json.dumps({"agents": manager.list_agents(), "tasks": manager.list_tasks()}, indent=2, ensure_ascii=False))
        return

    if args.action == "dashboard":
        print(json.dumps(manager.dashboard(), indent=2, ensure_ascii=False))
        return

    parser.print_help()


if __name__ == "__main__":
    main()
