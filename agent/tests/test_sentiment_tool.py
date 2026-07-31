"""Tests for the sentiment analysis tool."""

import json
from unittest.mock import patch

from src.tools.sentiment_tool import (
    SentimentTool,
    _score_text,
    _tokenize,
)


class TestTokenize:
    def test_empty(self):
        assert _tokenize("") == []

    def test_punctuation_only(self):
        assert _tokenize("!!! $$$") == []

    def test_mixed(self):
        tokens = _tokenize("Tesla beats earnings ESTIMATES!!!")
        assert "tesla" in tokens
        assert "beats" in tokens
        assert "earnings" in tokens
        assert "estimates" in tokens
        assert "!!!" not in " ".join(tokens)


class TestScoreText:
    def test_strongly_bullish(self):
        r = _score_text("profit surge growth rally record beat upgrade strong")
        assert r["score"] == 1.0
        assert r["positive"] == 8
        assert r["negative"] == 0

    def test_strongly_bearish(self):
        r = _score_text("crash plunge loss decline drop scandal weak downgrade")
        assert r["score"] == -1.0
        assert r["positive"] == 0
        assert r["negative"] == 8

    def test_neutral(self):
        r = _score_text("Tesla announced quarterly results today")
        assert r["score"] == 0.0
        assert r["positive"] == 0
        assert r["negative"] == 0

    def test_flat_is_neutral(self):
        """'flat' was removed from negative terms — financial neutral."""
        r = _score_text("markets flat today")
        assert r["score"] == 0.0

    def test_mixed(self):
        r = _score_text("profit beat expectations but future outlook worry decline")
        # profit, beat = 2 pos; worry, decline = 2 neg; (2-2)/4 = 0
        assert r["score"] == 0.0

    def test_slightly_bullish(self):
        r = _score_text("earnings beat profit growth outlook worry")
        # 4 positive (beat, profit, growth) vs 1 negative (worry) → (3-1)/4 = 0.5
        # Actually: beat, profit, growth = 3 pos; worry = 1 neg; score = (3-1)/4 = 0.5
        assert r["score"] == 0.5

    def test_real_headlines(self):
        """Verify scoring makes sense on realistic financial headlines."""
        assert _score_text("Tesla crushes earnings estimates, stock surges")["score"] > 0.5
        assert _score_text("Company warns of revenue miss, shares plunge")["score"] < -0.5
        assert _score_text("Fed holds rates steady as expected")["score"] == 0.0

    def test_empty_text(self):
        r = _score_text("")
        assert r["score"] == 0.0
        assert r["positive"] == 0

    def test_no_alpha_tokens(self):
        r = _score_text("123 456 !!! ???")
        assert r["score"] == 0.0


class TestSentimentTool:
    def test_missing_mode(self):
        tool = SentimentTool()
        result = json.loads(tool.execute())
        assert result["ok"] is False
        assert "Unknown mode" in result["error"]

    def test_unknown_mode(self):
        tool = SentimentTool()
        result = json.loads(tool.execute(mode="invalid"))
        assert result["ok"] is False

    def test_sentiment_score_missing_text(self):
        tool = SentimentTool()
        result = json.loads(tool.execute(mode="sentiment_score"))
        assert result["ok"] is False
        assert "text" in result["error"]

    def test_sentiment_score_success(self):
        tool = SentimentTool()
        result = json.loads(tool.execute(mode="sentiment_score", text="profit surge growth"))
        assert result["ok"] is True
        assert result["score"] == 1.0

    def test_sentiment_text_truncated(self):
        tool = SentimentTool()
        long_text = "bullish " * 1000
        result = json.loads(tool.execute(mode="sentiment_score", text=long_text))
        assert result["ok"] is True
        assert len(result["text"]) <= 500

    def test_fear_greed_success(self):
        tool = SentimentTool()
        mock_data = json.dumps({
            "data": [{"value": "28", "value_classification": "Fear"}]
        }).encode()
        with patch("urllib.request.urlopen", return_value=type("m", (), {"read": lambda s: mock_data, "__enter__": lambda s: s, "__exit__": lambda s,*a: None})()):
            result = json.loads(tool.execute(mode="fear_greed_index"))
        assert result["ok"] is True
        assert result["value"] == 28
        assert result["classification"] == "Fear"

    def test_fear_greed_failure(self):
        tool = SentimentTool()
        with patch("urllib.request.urlopen", side_effect=OSError("network down")):
            result = json.loads(tool.execute(mode="fear_greed_index"))
        assert result["ok"] is False
        assert "Failed to fetch" in result["error"]

    def test_fear_greed_empty_data(self):
        tool = SentimentTool()
        mock_data = json.dumps({"data": []}).encode()
        with patch("urllib.request.urlopen", return_value=type("m", (), {"read": lambda s: mock_data, "__enter__": lambda s: s, "__exit__": lambda s,*a: None})()):
            result = json.loads(tool.execute(mode="fear_greed_index"))
        assert result["ok"] is False

    def test_fear_greed_malformed_json(self):
        tool = SentimentTool()
        mock_data = b"not json"
        with patch("urllib.request.urlopen", return_value=type("m", (), {"read": lambda s: mock_data, "__enter__": lambda s: s, "__exit__": lambda s,*a: None})()):
            result = json.loads(tool.execute(mode="fear_greed_index"))
        assert result["ok"] is False

    def test_fear_greed_missing_value(self):
        tool = SentimentTool()
        mock_data = json.dumps({"data": [{"value_classification": "Neutral"}]}).encode()
        with patch("urllib.request.urlopen", return_value=type("m", (), {"read": lambda s: mock_data, "__enter__": lambda s: s, "__exit__": lambda s,*a: None})()):
            result = json.loads(tool.execute(mode="fear_greed_index"))
        assert result["ok"] is True
        assert result["value"] == 0  # default int

    def test_sentiment_unicode(self):
        """Non-ASCII text should not crash."""
        tool = SentimentTool()
        result = json.loads(tool.execute(mode="sentiment_score", text="特斯拉 profit 增长 surge 🚀"))
        assert result["ok"] is True
        assert result["score"] == 1.0  # profit + surge

    def test_sentiment_very_long(self):
        """Very long text should not crash or timeout."""
        tool = SentimentTool()
        result = json.loads(tool.execute(mode="sentiment_score", text="profit " * 5000))
        assert result["ok"] is True
        # 5000 "profit" tokens → all positive → score = 1.0
        assert result["score"] == 1.0

    def test_sentiment_no_alpha(self):
        tool = SentimentTool()
        result = json.loads(tool.execute(mode="sentiment_score", text="12345 67890 !@#$%"))
        assert result["ok"] is True
        assert result["score"] == 0.0

    def test_non_string_text_coerced(self):
        """Non-string text should be coerced to string, not crash."""
        tool = SentimentTool()
        result = json.loads(tool.execute(mode="sentiment_score", text=12345))
        assert result["ok"] is True
        assert isinstance(result["text"], str)

    def test_non_string_mode_coerced(self):
        """Non-string mode should be coerced."""
        tool = SentimentTool()
        result = json.loads(tool.execute(mode=999))
        assert result["ok"] is False
