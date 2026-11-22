import json

from src.tools.ask_user_tool import AskUserTool
from src.tools.plan_tool import PlanTool


def test_plan_contract_emits_update():
    events = []
    result = json.loads(PlanTool(event_callback=lambda name, data: events.append((name, data))).execute(
        steps=[{"step": "Inspect", "status": "in_progress"}]
    ))
    assert result["status"] == "ok"
    assert events == [("item.started", {
        "kind": "item.started",
        "item": {"type": "plan", "plan_id": result["plan_id"], "steps": result["steps"]},
        "session_id": None,
    })]


def test_question_contract_is_waiting_and_cannot_grant_permission():
    events = []
    result = json.loads(AskUserTool(event_callback=lambda name, data: events.append((name, data))).execute(
        prompt="Choose a format", options=["CSV", "JSON"]
    ))
    assert result["status"] == "waiting_user"
    assert "permission" in AskUserTool.description
    assert events == [("item.started", {
        "kind": "item.started",
        "item": {"type": "question", "question_id": result["question_id"],
                 "prompt": "Choose a format", "options": ["CSV", "JSON"], "allow_free_text": True},
        "session_id": None,
    })]


def test_contracts_reject_invalid_shapes():
    assert json.loads(PlanTool().execute(steps=[]))["status"] == "error"
    assert json.loads(AskUserTool().execute(prompt="", options=["only"]))["status"] == "error"


def test_interaction_previews_and_results_scrub_tool_output():
    events = []
    marker = "api_key=private-preview-value"

    def publish(name, data):
        events.append(data["item"])

    question = json.loads(AskUserTool(event_callback=publish).execute(prompt=marker, options=["plain", marker]))
    plan = json.loads(PlanTool(event_callback=publish).execute(steps=[{"step": marker, "status": "pending"}]))
    assert "private-preview-value" not in str([events, question, plan])
    assert events[0]["options"] == question["options"] == ["plain", "api_key=[redacted]"]
    assert events[1]["steps"] == plan["steps"] == [{"step": "api_key=[redacted]", "status": "pending"}]
