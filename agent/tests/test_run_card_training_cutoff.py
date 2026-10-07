import json
from pathlib import Path

from backtest.run_card import write_run_card


def test_run_card_records_model_and_warns_when_window_precedes_cutoff(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "strategy_provenance.json").write_text(
        json.dumps(
            {
                "files": {
                    "config.json": {
                        "provider": "openai",
                        "model_id": "gpt-5.6-luna",
                        "model_source": "configured",
                    },
                    "code/signal_engine.py": {
                        "provider": "openrouter",
                        "model_id": "claude-sonnet-4-5",
                        "model_source": "provider_response",
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    card = write_run_card(
        run_dir,
        {
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "model_training_cutoff": "2025-01-01",
        },
        {},
    )

    assert card["model_provenance"]["files"] == {
        "config.json": {
            "provider": "openai",
            "model_id": "gpt-5.6-luna",
            "model_source": "configured",
        },
        "code/signal_engine.py": {
            "provider": "openrouter",
            "model_id": "claude-sonnet-4-5",
            "model_source": "provider_response",
        },
    }
    assert card["model_provenance"]["training_cutoff"] == "2025-01-01"
    assert card["model_provenance"]["cutoff_source"] == "config"
    assert any(
        "results may reflect what the model remembers" in w for w in card["warnings"]
    )
    markdown = (run_dir / "run_card.md").read_text(encoding="utf-8")
    assert "config.json: openai/gpt-5.6-luna (configured)" in markdown
    assert (
        "code/signal_engine.py: openrouter/claude-sonnet-4-5 (provider_response)"
        in markdown
    )


def test_run_card_treats_unknown_cutoff_as_exposed(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "strategy_provenance.json").write_text(
        json.dumps(
            {
                "files": {
                    "config.json": {
                        "provider": "openrouter",
                        "model_id": "custom/model",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    card = write_run_card(
        run_dir,
        {"start_date": "2025-01-01", "end_date": "2025-12-31"},
        {},
    )

    assert card["model_provenance"]["training_cutoff"] is None
    assert (
        card["model_provenance"]["files"]["config.json"]["model_id"] == "custom/model"
    )
    assert any(
        "cutoff" in w.lower() and "unknown" in w.lower() for w in card["warnings"]
    )


def test_run_card_warns_when_existing_strategy_has_incomplete_provenance(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    signal_path = run_dir / "code" / "signal_engine.py"
    signal_path.parent.mkdir(parents=True)
    signal_path.write_text("class SignalEngine: pass\n", encoding="utf-8")
    (run_dir / "strategy_provenance.json").write_text(
        json.dumps(
            {
                "files": {
                    "code/signal_engine.py": {"provider": "openai"},
                }
            }
        ),
        encoding="utf-8",
    )

    card = write_run_card(
        run_dir,
        {
            "start_date": "2025-01-01",
            "end_date": "2025-01-02",
            "model_training_cutoff": "2025-01-01",
        },
        {},
    )

    source = card["model_provenance"]["files"]["code/signal_engine.py"]
    assert source["provider"] == "openai"
    assert source["model_id"] is None
    assert any(
        "provenance" in warning.lower() and "incomplete" in warning.lower()
        for warning in card["warnings"]
    )


def test_run_card_warns_when_strategy_files_have_no_provenance(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "run"
    (run_dir / "code").mkdir(parents=True)
    (run_dir / "config.json").write_text("{}\n", encoding="utf-8")
    (run_dir / "code" / "signal_engine.py").write_text(
        "class SignalEngine: pass\n",
        encoding="utf-8",
    )

    card = write_run_card(
        run_dir,
        {
            "start_date": "2025-01-01",
            "end_date": "2025-01-02",
            "model_training_cutoff": "2025-01-01",
        },
        {},
    )

    for path in ("config.json", "code/signal_engine.py"):
        assert card["model_provenance"]["files"][path]["model_id"] is None
        assert any(
            path in warning and "provenance" in warning.lower()
            for warning in card["warnings"]
        )


def test_run_card_does_not_warn_when_window_reaches_cutoff(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "strategy_provenance.json").write_text(
        json.dumps(
            {
                "files": {
                    "config.json": {"provider": "openai", "model_id": "gpt-5.6-luna"},
                    "code/signal_engine.py": {
                        "provider": "openai",
                        "model_id": "gpt-5.6-luna",
                    },
                }
            }
        ),
        encoding="utf-8",
    )

    card = write_run_card(
        run_dir,
        {
            "start_date": "2025-01-01",
            "end_date": "2025-01-01",
            "model_training_cutoff": "2025-01-01",
        },
        {},
    )

    assert not any("training cutoff" in w.lower() for w in card["warnings"])
