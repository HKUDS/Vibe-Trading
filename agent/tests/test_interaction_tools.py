import json

from src.tools.ask_user_tool import AskUserTool
from src.tools.plan_tool import PlanTool


def test_plan_contract_emits_update():
    events = []
    result = json.loads(PlanTool(event_callback=lambda name, data: events.append((name, data))).execute(
        steps=[{"step": "Inspect", "status": "in_progress"}]
    ))
    assert result["status"] == "ok"
    assert events[0][0] == "plan.updated"


def test_question_contract_is_waiting_and_cannot_grant_permission():
    events = []
    result = json.loads(AskUserTool(event_callback=lambda name, data: events.append((name, data))).execute(
        prompt="Choose a format", options=["CSV", "JSON"]
    ))
    assert result["status"] == "waiting_user"
    assert "permission" in AskUserTool.description
    assert events[0][0] == "question.asked"


def test_contracts_reject_invalid_shapes():
    assert json.loads(PlanTool().execute(steps=[]))["status"] == "error"
    assert json.loads(AskUserTool().execute(prompt="", options=["only"]))["status"] == "error"
