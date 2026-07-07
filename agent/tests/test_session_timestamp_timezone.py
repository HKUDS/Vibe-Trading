from datetime import datetime

from src.session.models import Attempt, Message, Session


def test_session_models_emit_timezone_aware_iso_timestamps() -> None:
    session = Session()
    message = Message()
    attempt = Attempt()

    for value in (session.created_at, session.updated_at, message.created_at, attempt.created_at):
        parsed = datetime.fromisoformat(value)
        assert parsed.tzinfo is not None

    attempt.mark_completed("done")
    assert attempt.completed_at is not None
    parsed_completed = datetime.fromisoformat(attempt.completed_at)
    assert parsed_completed.tzinfo is not None
