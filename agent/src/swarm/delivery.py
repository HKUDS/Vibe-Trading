"""Deliver available research while retaining each task's actual outcome."""

from src.swarm.models import RunStatus, SwarmRun, TaskStatus


def refresh_report(run: SwarmRun, final_task_ids: list[str]) -> None:
    """Select a final synthesis or assemble available results without another LLM."""
    run.report_is_partial = run.status != RunStatus.completed
    final = next(
        (t for t in run.tasks if t.id in final_task_ids and t.status == TaskStatus.completed and t.summary), None
    )
    if final and len(final_task_ids) == 1:
        run.final_report = final.summary
        return
    roles = {a.id: a.role or a.id for a in run.agents}
    sections = []
    for task in run.tasks:
        body = task.summary or ""
        if body.strip():
            sections.append(f"## {roles.get(task.agent_id, task.agent_id)} ({task.status.value})\n\n{body}")
    run.final_report = "\n\n".join(sections) or None
