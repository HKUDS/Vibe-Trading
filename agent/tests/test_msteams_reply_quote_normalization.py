"""Regression: a multi-paragraph quoted Teams message must not leak its later
paragraphs into what the agent is told is the user's own reply.
"""

from __future__ import annotations

from src.channels.msteams import MSTeamsChannel


def _sanitize(text: str) -> str:
    channel = MSTeamsChannel.__new__(MSTeamsChannel)
    activity = {
        "type": "message",
        "text": text,
        "replyToId": "msg-123",
        "channelData": {},
    }
    return channel._sanitize_inbound_text(activity)


class TestReplyQuoteNormalization:
    def test_multi_paragraph_quote_stays_fully_in_the_quote(self) -> None:
        text = (
            "Reply wrapper\nFirst paragraph of the original quoted message.\n\n"
            "Second paragraph of the original quoted message.\n\n"
            "Here is my actual reply."
        )

        result = _sanitize(text)

        assert "User is replying to: First paragraph of the original quoted message. " \
            "Second paragraph of the original quoted message." in result
        assert result.endswith("User reply: Here is my actual reply.")
        assert "Second paragraph of the original quoted message." not in result.split(
            "User reply:"
        )[1]

    def test_single_paragraph_quote_still_works(self) -> None:
        text = "Reply wrapper\nSingle paragraph quote.\n\nHere is my actual reply."

        result = _sanitize(text)

        assert result == (
            "User is replying to: Single paragraph quote.\n"
            "User reply: Here is my actual reply."
        )
