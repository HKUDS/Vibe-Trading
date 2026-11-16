"""A prepared child earns evidence from its own sealed backtest only."""

import json
import shutil
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from src.strategy_discovery.adaptation_workflow import prepare_adaptation, validate_adapted_run
from src.strategy_discovery.evidence_store import EvidenceStore
from src.strategy_discovery.models import EvidenceRow
from src.strategy_store.models import Artifact, ArtifactStatus, ArtifactType, ValidationStatus
from src.strategy_store.sqlite_store import SqliteStrategyStore
from src.tools.strategy_discovery_tool import refresh_strategy_evidence_core


@pytest.fixture
def context(tmp_path, monkeypatch):
    import src.strategy_store._shared as shared

    monkeypatch.setenv("VIBE_TRADING_HOME", str(tmp_path))
    monkeypatch.setenv("VIBE_TRADING_STRATEGY_DISCOVERY_DB_PATH", str(tmp_path / "evidence.db"))
    store = SqliteStrategyStore(tmp_path / "sdm.db")
    monkeypatch.setattr(shared, "_store", store)
    parent = Artifact(id="parent", type=ArtifactType.STRATEGY, name="parent", universe="old",
                      signal_definition="Alternate 5 held bars and 5 flat bars", entry_rules="next open",
                      exit_rules="next open", position_sizing="full position", run_dir="/parent/run",
                      signal_engine_path="/parent/code.py", status=ArtifactStatus.ACTIVE)
    store.register_artifact(parent)
    evidence = EvidenceStore(tmp_path / "evidence.db")
    evidence.upsert_rows([EvidenceRow(strategy_id="sdm:parent", regime="bull_market",
                                     trades_in_regime=40, date_ranges=("2023-01 to 2025-12",),
                                     evidence_quality="adequate", provenance="parent-run")])
    return store, evidence


def prepare(context, **overrides):
    values = dict(strategy_id="sdm:parent", name="child", universe="new",
                  config={"codes": ["AAPL.US"], "start_date": "2024-01-01", "end_date": "2024-02-08",
                          "source": "local", "initial_cash": 100000, "commission": 0},
                  store=context[0], evidence_store=context[1], today=date(2026, 1, 31))
    values.update(overrides)
    return prepare_adaptation(**values)


def seal_fixture(result):
    from backtest.run_card import write_run_card
    from tests.test_strategy_discovery_harness import _write_run_fixture

    root = Path(result["run_dir"])
    fixture = _write_run_fixture(root / "fixture")
    shutil.copytree(fixture / "artifacts", root / "artifacts")
    shutil.copyfile(fixture / "state.json", root / "state.json")
    (root / "code/signal_engine.py").write_text("class SignalEngine: pass\n")
    write_run_card(root, json.loads((root / "config.json").read_text()), {"trade_count": 9},
                   strategy_path=root / "code/signal_engine.py")
    return root


def test_child_starts_without_evidence_attestation_or_parent_code(context):
    result = prepare(context)
    child = context[0].get_artifact(result["strategy_id"].removeprefix("sdm:"))
    assert child.derived_from == "parent"
    assert child.signal_definition == context[0].get_artifact("parent").signal_definition
    assert child.validation_status == ValidationStatus.UNVALIDATED
    assert child.approver is None and child.model_version is None
    assert context[1].get_rows(strategy_id=result["strategy_id"]) == []
    assert child.signal_engine_path.startswith(result["run_dir"])
    assert not Path(child.signal_engine_path).exists()
    assert result["parent_evidence"][0]["provenance"] == "parent-run"


@pytest.mark.parametrize("change", ["stale", "insufficient", "disabled", "factor", "wrong-parent"])
def test_parent_refusals_leave_no_child(context, change):
    store, evidence = context
    parent = store.get_artifact("parent")
    if change == "disabled":
        store.update_status("parent", ArtifactStatus.DISABLED)
    elif change == "factor":
        store.update_artifact(replace(parent, type=ArtifactType.FACTOR))
    else:
        row = evidence.get_rows()[0]
        updates = {"stale": {"date_ranges": ("2020-01 to 2020-12",)},
                   "insufficient": {"evidence_quality": "insufficient"},
                   "wrong-parent": {"strategy_id": "sdm:someone-else"}}[change]
        evidence.replace_rows([replace(row, **updates)])
    with pytest.raises(ValueError):
        prepare(context)
    assert len(store.list_artifacts()) == 1


def test_scoped_refresh_retains_parent_and_reports_childs_own_quality(context):
    result = prepare(context)
    root = seal_fixture(result)
    before = context[1].get_rows(strategy_id="sdm:parent")
    validate_adapted_run(result["strategy_id"], root)
    output = refresh_strategy_evidence_core(runs=[{"strategy_id": result["strategy_id"], "run_dir": str(root)}], scope="strategies")
    assert output["rows"] > 0, output
    assert context[1].get_rows(strategy_id="sdm:parent") == before
    rows = context[1].get_rows(strategy_id=result["strategy_id"])
    assert all(row.provenance != "parent-run" for row in rows)
    assert all(row.evidence_quality != "adequate" for row in rows)


@pytest.mark.parametrize("mutation", ["other-run", "dates", "codes", "description", "code", "equity", "failed", "no-card", "symlink"])
def test_alternate_or_changed_run_cannot_be_adopted(context, tmp_path, mutation):
    result = prepare(context)
    root = seal_fixture(result)
    if mutation == "other-run":
        other = tmp_path / "runs/other"
        shutil.copytree(root, other)
        root = other
    elif mutation in {"dates", "codes"}:
        config = json.loads((root / "config.json").read_text())
        config["start_date" if mutation == "dates" else "codes"] = "2020-01-01" if mutation == "dates" else ["MSFT.US"]
        (root / "config.json").write_text(json.dumps(config))
    elif mutation == "description":
        child = context[0].get_artifact(result["strategy_id"].removeprefix("sdm:"))
        context[0].update_artifact(replace(child, signal_definition="different"))
    elif mutation in {"code", "equity"}:
        path = root / ("code/signal_engine.py" if mutation == "code" else "artifacts/equity.csv")
        path.write_text(path.read_text() + "\nchanged\n")
    elif mutation == "failed":
        (root / "state.json").write_text('{"status":"failed"}')
    elif mutation == "no-card":
        (root / "run_card.json").unlink()
    elif mutation == "symlink":
        path = root / "artifacts/equity.csv"
        other = tmp_path / "elsewhere.csv"
        path.rename(other)
        path.symlink_to(other)
    before = context[1].get_rows()
    output = refresh_strategy_evidence_core(runs=[{"strategy_id": result["strategy_id"], "run_dir": str(root)}], scope="strategies")
    assert output["rows"] == 0 and output["skipped"], output
    assert context[1].get_rows() == before


def test_real_local_backtest_to_child_evidence(context, tmp_path):
    """Real file loader, code generation write, subprocess engine and refresh; no network/model."""
    import numpy as np
    import pandas as pd
    import yaml
    from src.tools.backtest_tool import run_backtest
    from src.tools.write_file_tool import WriteFileTool

    config = {"source": "local", "codes": ["AAPL.US"], "start_date": "2024-01-01", "end_date": "2025-12-31",
              "benchmark": "AAPL.US", "initial_cash": 100000, "commission": 0, "interval": "1D", "engine": "daily"}
    result = prepare(context, config=config)
    code = '''import numpy as np
import pandas as pd
class SignalEngine:
    def generate(self, data_map):
        return {code: pd.Series((np.arange(len(frame)) % 10 < 5).astype(float), index=frame.index) for code, frame in data_map.items()}
'''
    written = json.loads(WriteFileTool().execute(path=str(Path(result["run_dir"]) / "code/signal_engine.py"), content=code))
    assert written["status"] == "ok"
    index = pd.bdate_range(config["start_date"], config["end_date"])
    close = 100 + np.arange(len(index)) * 0.1 + np.sin(np.arange(len(index)) / 5)
    data_file = tmp_path / "synthetic.csv"
    pd.DataFrame({"date": index, "open": close, "high": close + 1, "low": close - 1, "close": close, "volume": 100000}).to_csv(data_file, index=False)
    local_config = Path.home() / ".vibe-trading/data-bridge/config.yaml"
    local_config.parent.mkdir(parents=True, exist_ok=True)
    local_config.write_text(yaml.safe_dump({"sources": [{"symbol": "AAPL.US", "type": "csv", "path": str(data_file)}]}))
    try:
        backtest = json.loads(run_backtest(result["run_dir"]))
        assert backtest["status"] == "ok", backtest
        output = refresh_strategy_evidence_core(runs=[{"strategy_id": result["strategy_id"], "run_dir": result["run_dir"]}], scope="strategies")
        assert output["rows"] > 0 and not output["skipped"], output
        assert context[1].get_rows(strategy_id="sdm:parent")[0].provenance == "parent-run"
    finally:
        local_config.unlink(missing_ok=True)


def test_generated_child_code_records_current_model_without_touching_active_run(context, tmp_path):
    from types import SimpleNamespace
    from src.agent.write_targets import record_written_target

    result = prepare(context)
    path = Path(result["run_dir"]) / "code/signal_engine.py"
    path.write_text("class SignalEngine: pass\n")
    active = tmp_path / "runs/active"
    active.mkdir()
    record_written_target({"path": str(path)}, written_files=set(), run_dir=str(active),
                          llm_runtime=SimpleNamespace(provider="test-provider"),
                          active_model_id="actual-response-model", active_model_source="response")
    provenance = json.loads((path.parent.parent / "strategy_provenance.json").read_text())
    assert provenance["files"]["code/signal_engine.py"]["model_id"] == "actual-response-model"
    assert not (active / "strategy_provenance.json").exists()
    elsewhere = tmp_path / "elsewhere/code"
    elsewhere.mkdir(parents=True)
    record_written_target({"path": str(elsewhere / "signal_engine.py")}, written_files=set(), run_dir=str(active),
                          llm_runtime=SimpleNamespace(provider="test-provider"),
                          active_model_id="actual-response-model", active_model_source="response")
    assert not (elsewhere.parent / "strategy_provenance.json").exists()


def test_api_auth_and_cli_prepare_share_child_contract(context, tmp_path, capsys):
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
    from cli import _legacy
    from src.api.strategy_adaptation_routes import register_strategy_adaptation_routes

    # API and CLI use the actual clock. Keep their parent's evidence non-stale.
    row = context[1].get_rows()[0]
    context[1].replace_rows([replace(row, date_ranges=(f"2023-01 to {date.today():%Y-%m}",))])
    allow = False

    def auth():
        if not allow:
            raise HTTPException(401, "auth required")

    app = FastAPI()
    register_strategy_adaptation_routes(app, auth)
    client = TestClient(app)
    config = {"source": "local", "codes": ["AAPL.US"], "start_date": "2024-01-01", "end_date": "2024-02-08"}
    payload = {"strategy_id": "sdm:parent", "name": "api child", "universe": "new", "config": config}
    assert client.post("/api/strategy-adaptations", json=payload).status_code == 401
    assert client.post("/api/strategy-adaptations/evidence", json={"runs": []}).status_code == 401
    allow = True
    response = client.post("/api/strategy-adaptations", json=payload)
    assert response.status_code == 200, response.text
    child = response.json()
    assert child["derived_from"] == "sdm:parent"
    assert context[0].get_adaptation_binding(child["strategy_id"].removeprefix("sdm:"))["codes"] == config["codes"]
    config_path = tmp_path / "input.json"
    config_path.write_text(json.dumps(config))
    code = _legacy.main(["strategy-evidence", "adapt", "--strategy-id", "sdm:parent", "--name", "cli child",
                         "--universe", "new", "--config", str(config_path)])
    assert code == 0
    output = json.loads(capsys.readouterr().out)
    assert output["derived_from"] == "sdm:parent" and output["strategy_id"] != child["strategy_id"]
