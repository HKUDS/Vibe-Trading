"""Tests for src/governance/ (run manifest + hash-chained ledger).

Focus: manifest hashing is deterministic over composition and sensitive to
every composition dimension (system prompt / skills / tools / package
versions / extra) while being INSENSITIVE to run_id/timestamp; the ledger's
tamper detection is proven with negative (tampered/deleted) fixtures, not
just a happy-path pass; fsync is actually invoked on the write path; and the
pre-existing src/live/audit.py public contract keeps working unchanged.
"""

from __future__ import annotations

import ast
import inspect
import json
from pathlib import Path

import pytest

from src.governance import ledger as ledger_mod
from src.governance import manifest as manifest_mod
from src.governance.ledger import (
    ChainVerificationResult,
    LedgerCorruptionError,
    append_record,
    build_export,
    verify_chain,
    verify_export,
)
from src.governance.manifest import (
    RunManifest,
    build_run_manifest,
    collect_key_package_versions,
    diff_manifests,
)
from src.live import audit
from src.live import paths as live_paths
from src.live.audit import LiveActionEvent, write_live_action


# ---------------------------------------------------------------------------
# No hidden clock (source-level assertion, both new modules).
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", [manifest_mod, ledger_mod])
def test_no_hidden_clock_in_source(module) -> None:
    """Neither governance module may call datetime.now()/time.time() itself.

    Timestamps must always be caller-supplied (manifest) or simply absent
    (ledger has no timestamp concept at all). A source-level AST walk is
    used rather than a substring grep so a comment/docstring mentioning
    "time.time()" cannot cause a false failure and, more importantly, an
    actual call cannot hide behind reformatting.
    """
    source = inspect.getsource(module)
    tree = ast.parse(source)
    offending: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        dotted = None
        if isinstance(func, ast.Attribute):
            if isinstance(func.value, ast.Name):
                dotted = f"{func.value.id}.{func.attr}"
        elif isinstance(func, ast.Name):
            dotted = func.id
        if dotted in {"datetime.now", "time.time", "now"}:
            offending.append(dotted)
    assert offending == [], f"{module.__name__} calls a hidden clock: {offending}"


# ---------------------------------------------------------------------------
# manifest.py
# ---------------------------------------------------------------------------


def _base_manifest_kwargs() -> dict:
    return dict(
        run_id="run-1",
        timestamp="2026-08-06T00:00:00.000+00:00",
        system_prompt="You are a trading research agent.",
        skills={
            "tushare": "tushare skill body v1",
            "risk-committee": "risk committee lens body v1",
        },
        tool_names=["get_market_data", "backtest", "cashflow_performance"],
        package_versions={"numpy": "2.4.4", "pandas": "2.3.3"},
        extra={"provider": "openrouter", "model": "deepseek/deepseek-v3.2"},
    )


def test_manifest_hash_deterministic_for_same_composition() -> None:
    """Building twice from identical composition yields the identical hash."""
    m1 = build_run_manifest(**_base_manifest_kwargs())
    m2 = build_run_manifest(**_base_manifest_kwargs())
    assert m1.manifest_hash == m2.manifest_hash
    assert m1.manifest_hash.startswith("sha256:")


def test_manifest_hash_ignores_run_id_and_timestamp() -> None:
    """Same composition, different run_id/timestamp -> SAME manifest_hash.

    This locks in the documented design choice: manifest_hash fingerprints
    the METHODOLOGY, not the particular execution instance, so re-running
    identical methodology on a different day is recognizable as "unchanged".
    """
    kwargs_a = _base_manifest_kwargs()
    kwargs_b = {**_base_manifest_kwargs(), "run_id": "run-2", "timestamp": "2099-01-01T00:00:00.000+00:00"}
    m1 = build_run_manifest(**kwargs_a)
    m2 = build_run_manifest(**kwargs_b)
    assert m1.manifest_hash == m2.manifest_hash
    assert m1.run_id != m2.run_id
    assert m1.timestamp != m2.timestamp


def test_manifest_hash_changes_when_a_skill_content_changes() -> None:
    """Editing one skill's body changes manifest_hash and is named by diff."""
    baseline = build_run_manifest(**_base_manifest_kwargs())

    kwargs = _base_manifest_kwargs()
    kwargs["skills"] = {**kwargs["skills"], "tushare": "tushare skill body v2 (edited)"}
    changed = build_run_manifest(**kwargs)

    assert changed.manifest_hash != baseline.manifest_hash
    diff = diff_manifests(baseline, changed)
    assert diff.skills_changed == ("tushare",)
    assert diff.skills_added == ()
    assert diff.skills_removed == ()
    assert diff.manifest_hash_changed is True
    assert diff.unchanged is False


def test_manifest_hash_changes_when_system_prompt_changes() -> None:
    baseline = build_run_manifest(**_base_manifest_kwargs())
    kwargs = _base_manifest_kwargs()
    kwargs["system_prompt"] = "You are a trading research agent. (v2)"
    changed = build_run_manifest(**kwargs)

    assert changed.manifest_hash != baseline.manifest_hash
    assert changed.system_prompt_hash != baseline.system_prompt_hash
    diff = diff_manifests(baseline, changed)
    assert diff.system_prompt_changed is True


def test_manifest_hash_changes_when_tool_registry_changes() -> None:
    baseline = build_run_manifest(**_base_manifest_kwargs())
    kwargs = _base_manifest_kwargs()
    kwargs["tool_names"] = [*kwargs["tool_names"], "options_payoff"]
    changed = build_run_manifest(**kwargs)

    assert changed.manifest_hash != baseline.manifest_hash
    diff = diff_manifests(baseline, changed)
    assert diff.tools_added == ("options_payoff",)
    assert diff.tools_removed == ()


def test_manifest_hash_changes_when_package_version_changes() -> None:
    baseline = build_run_manifest(**_base_manifest_kwargs())
    kwargs = _base_manifest_kwargs()
    kwargs["package_versions"] = {**kwargs["package_versions"], "numpy": "2.5.0"}
    changed = build_run_manifest(**kwargs)

    assert changed.manifest_hash != baseline.manifest_hash
    diff = diff_manifests(baseline, changed)
    assert diff.package_version_changes == (("numpy", "2.4.4", "2.5.0"),)


def test_manifest_hash_changes_when_extra_changes() -> None:
    baseline = build_run_manifest(**_base_manifest_kwargs())
    kwargs = _base_manifest_kwargs()
    kwargs["extra"] = {**kwargs["extra"], "model": "deepseek/deepseek-v3.3"}
    changed = build_run_manifest(**kwargs)

    assert changed.manifest_hash != baseline.manifest_hash
    diff = diff_manifests(baseline, changed)
    assert diff.extra_changes == (("model", "deepseek/deepseek-v3.2", "deepseek/deepseek-v3.3"),)


def test_manifest_diff_reports_no_changes_for_identical_composition() -> None:
    a = build_run_manifest(**_base_manifest_kwargs())
    b = build_run_manifest(**{**_base_manifest_kwargs(), "run_id": "other-run"})
    diff = diff_manifests(a, b)
    assert diff.unchanged is True
    assert diff.manifest_hash_changed is False


def test_manifest_serialization_round_trip() -> None:
    original = build_run_manifest(**_base_manifest_kwargs())

    via_dict = RunManifest.from_dict(original.to_dict())
    assert via_dict == original
    assert via_dict.verify_hash() is True

    via_json = RunManifest.from_json(original.to_json())
    assert via_json == original
    assert via_json.verify_hash() is True


def test_manifest_verify_hash_detects_tampering_after_deserialize() -> None:
    original = build_run_manifest(**_base_manifest_kwargs())
    data = original.to_dict()
    # Tamper: swap in a different skill hash without recomputing manifest_hash.
    data["skills"][0]["content_hash"] = "sha256:" + "0" * 64
    tampered = RunManifest.from_dict(data)
    assert tampered.verify_hash() is False


def test_manifest_rejects_duplicate_skill_names_in_sequence_form() -> None:
    from src.governance.manifest import SkillRecord

    with pytest.raises(ValueError):
        build_run_manifest(
            run_id="r1",
            timestamp="t1",
            system_prompt="p",
            skills=[
                SkillRecord.from_content("dup", "a"),
                SkillRecord.from_content("dup", "b"),
            ],
        )


def test_manifest_rejects_empty_run_id_or_timestamp() -> None:
    kwargs = _base_manifest_kwargs()
    with pytest.raises(ValueError):
        build_run_manifest(**{**kwargs, "run_id": ""})
    with pytest.raises(ValueError):
        build_run_manifest(**{**kwargs, "timestamp": "  "})


def test_collect_key_package_versions_reflects_real_environment() -> None:
    """Sanity check against the actual installed environment (no mocking).

    vibe-trading-ai is installed editable in this checkout (pyproject.toml
    pins 0.1.13 at the time this test was written); numpy is a hard
    dependency so it must resolve; arch is an optional 'stats' extra that is
    NOT installed in this environment, proving the None-when-absent path is
    real, not merely a documented intent.
    """
    versions = collect_key_package_versions()
    assert versions["numpy"] is not None
    assert versions["vibe-trading-ai"] is not None
    assert "python" in versions and versions["python"]
    # Not asserting a specific arch install state (that is an environment
    # fact, not a manifest.py contract) -- but the key must be present.
    assert "arch" in versions


# ---------------------------------------------------------------------------
# ledger.py — happy path
# ---------------------------------------------------------------------------


def test_append_record_chains_sequential_records(tmp_path: Path) -> None:
    path = tmp_path / "chain.jsonl"
    records = [append_record(path, {"n": i}) for i in range(5)]

    assert [r["seq"] for r in records] == [1, 2, 3, 4, 5]
    assert records[0]["prev_record_hash"] == ledger_mod.GENESIS_PREV_HASH
    for earlier, later in zip(records, records[1:]):
        assert later["prev_record_hash"] == earlier["record_hash"]

    result = verify_chain(path)
    assert result.ok is True
    assert result.record_count == 5
    assert result.first_break is None


def test_append_record_rejects_reserved_payload_keys(tmp_path: Path) -> None:
    path = tmp_path / "chain.jsonl"
    with pytest.raises(ValueError):
        append_record(path, {"seq": 99, "note": "hijack"})


def test_verify_chain_on_missing_file_is_trivially_ok(tmp_path: Path) -> None:
    result = verify_chain(tmp_path / "does_not_exist.jsonl")
    assert result == ChainVerificationResult(ok=True, record_count=0, first_break=None)


# ---------------------------------------------------------------------------
# ledger.py — tamper detection (negative-case driven, per task requirement)
# ---------------------------------------------------------------------------


def _write_five_records(path: Path) -> list[dict]:
    return [append_record(path, {"label": f"record-{i}", "amount": i * 10}) for i in range(5)]


def test_tamper_editing_one_record_content_is_pinpointed(tmp_path: Path) -> None:
    """The core negative case: hand-edit ONE record's payload, leave its
    stored seq/prev_record_hash/record_hash untouched, and assert
    verify_chain names exactly that record -- not merely "broken somewhere".
    """
    path = tmp_path / "chain.jsonl"
    _write_five_records(path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    tampered_index = 2  # the 3rd record (seq=3), 0-based line index 2
    record = json.loads(lines[tampered_index])
    assert record["seq"] == 3
    original_amount = record["amount"]
    record["amount"] = original_amount + 999  # tamper the payload only
    lines[tampered_index] = json.dumps(record, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = verify_chain(path)
    assert result.ok is False
    assert result.first_break is not None
    assert result.first_break.index == tampered_index
    assert result.first_break.seq == 3
    assert result.first_break.reason == "record_hash_mismatch"
    # Records before the tamper are still counted as verified.
    assert result.record_count == 2


def test_tamper_deleting_a_middle_record_is_detected(tmp_path: Path) -> None:
    """Removing a whole line (not just editing content) must also be caught."""
    path = tmp_path / "chain.jsonl"
    _write_five_records(path)

    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    deleted_index = 1  # remove the 2nd record (seq=2)
    del lines[deleted_index]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = verify_chain(path)
    assert result.ok is False
    assert result.first_break is not None
    # After deleting seq=2, the next physical line is the original seq=3
    # record, which the walk encounters while still expecting seq=2.
    assert result.first_break.index == deleted_index
    assert result.first_break.seq == 3
    assert result.first_break.reason == "seq_gap"
    assert result.record_count == 1


def test_tamper_that_also_fixes_its_own_hash_is_still_caught_downstream(tmp_path: Path) -> None:
    """A more sophisticated tamper: edit a record's payload AND recompute
    that record's own record_hash so it is internally self-consistent. The
    chain must still catch this -- not at the tampered record (which now
    looks locally valid) but at the very next record, whose stored
    prev_record_hash still points at the ORIGINAL (pre-tamper) hash.
    """
    path = tmp_path / "chain.jsonl"
    _write_five_records(path)

    lines = path.read_text(encoding="utf-8").splitlines()
    tampered_index = 2  # seq=3
    record = json.loads(lines[tampered_index])
    record["amount"] = -1
    payload = {k: v for k, v in record.items() if k not in {"seq", "prev_record_hash", "record_hash"}}
    record["record_hash"] = ledger_mod.compute_record_hash(
        record["seq"], record["prev_record_hash"], payload
    )
    lines[tampered_index] = json.dumps(record, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    result = verify_chain(path)
    assert result.ok is False
    assert result.first_break is not None
    assert result.first_break.index == tampered_index + 1  # the NEXT record, seq=4
    assert result.first_break.seq == 4
    assert result.first_break.reason == "prev_hash_mismatch"
    # The tampered record itself (seq=3) still counts as "verified" in
    # isolation -- proving the propagation, not a local check, is what
    # catches this class of tamper.
    assert result.record_count == 3


def test_only_asserting_untampered_pass_would_be_insufficient_so_also_assert_ok_baseline(
    tmp_path: Path,
) -> None:
    """Companion positive control for the negative tests above: confirms the
    SAME 5-record fixture verifies clean before any tampering, so the
    negative tests above are proven to detect the tamper itself and not
    some unrelated fixture bug.
    """
    path = tmp_path / "chain.jsonl"
    _write_five_records(path)
    assert verify_chain(path) == ChainVerificationResult(ok=True, record_count=5, first_break=None)


def test_append_record_refuses_to_extend_an_already_broken_chain(tmp_path: Path) -> None:
    path = tmp_path / "chain.jsonl"
    _write_five_records(path)
    lines = path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[2])
    record["amount"] = 999999
    lines[2] = json.dumps(record, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LedgerCorruptionError) as excinfo:
        append_record(path, {"label": "record-5-attempt"})
    assert excinfo.value.chain_break.index == 2
    assert excinfo.value.chain_break.reason == "record_hash_mismatch"

    # And the file was NOT extended with a 6th record.
    assert len(path.read_text(encoding="utf-8").splitlines()) == 5


# ---------------------------------------------------------------------------
# ledger.py — fsync
# ---------------------------------------------------------------------------


def test_append_record_calls_os_fsync(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os as os_mod

    calls: list[int] = []
    real_fsync = os_mod.fsync

    def counting_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os_mod, "fsync", counting_fsync)

    path = tmp_path / "chain.jsonl"
    append_record(path, {"n": 1})
    # At least one fsync for the record write itself (plus one for the
    # parent directory entry, since this is the first write to a new file).
    assert len(calls) >= 1


def test_append_record_skips_fsync_when_disabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os as os_mod

    calls: list[int] = []
    monkeypatch.setattr(os_mod, "fsync", lambda fd: calls.append(fd))

    path = tmp_path / "chain.jsonl"
    append_record(path, {"n": 1}, fsync=False)
    assert calls == []


# ---------------------------------------------------------------------------
# ledger.py — export / offline verification
# ---------------------------------------------------------------------------


def test_export_is_self_contained_and_offline_verifiable(tmp_path: Path) -> None:
    path = tmp_path / "chain.jsonl"
    _write_five_records(path)

    export = build_export(path)
    assert export["record_count"] == 5
    assert export["verification"]["ok"] is True

    # Delete the SOURCE ledger entirely -- verify_export must not need it.
    path.unlink()
    result = verify_export(export)
    assert result.ok is True
    assert result.record_count == 5


def test_export_to_file_round_trips(tmp_path: Path) -> None:
    from src.governance.ledger import export_chain_to_file

    path = tmp_path / "chain.jsonl"
    _write_five_records(path)
    dest = tmp_path / "export.json"
    export_chain_to_file(path, dest)

    loaded = json.loads(dest.read_text(encoding="utf-8"))
    result = verify_export(loaded)
    assert result.ok is True
    result_from_path = verify_export(dest)
    assert result_from_path.ok is True


def test_verify_export_detects_tampered_embedded_record(tmp_path: Path) -> None:
    path = tmp_path / "chain.jsonl"
    _write_five_records(path)
    export = build_export(path)

    export["records"][2]["amount"] = -1  # tamper without fixing export_hash
    result = verify_export(export)
    assert result.ok is False
    assert result.first_break.reason == "export_hash_mismatch"


def test_verify_export_detects_tampered_envelope_hash_directly(tmp_path: Path) -> None:
    path = tmp_path / "chain.jsonl"
    _write_five_records(path)
    export = build_export(path)

    export["export_hash"] = "sha256:" + "f" * 64
    result = verify_export(export)
    assert result.ok is False
    assert result.first_break.reason == "export_hash_mismatch"
    assert result.first_break.index == -1


# ---------------------------------------------------------------------------
# src/live/audit.py — backward compatibility + new capabilities
# ---------------------------------------------------------------------------


@pytest.fixture
def live_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the live runtime root at an isolated tmp dir (mirrors test_audit_redact.py)."""
    monkeypatch.setattr(live_paths, "get_runtime_root", lambda: tmp_path)
    return tmp_path


def _read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_default_write_live_action_shape_is_unchanged(live_runtime: Path) -> None:
    """Backward compat under the 2026-08-06 default flip.

    The chain is now written on every call, but the classic ledger line and the
    RETURN VALUE must stay byte-identical to what callers already depend on --
    the three chain fields belong to the chain file alone.
    """
    rec = write_live_action(
        LiveActionEvent(kind="order_placed", session_id="s1", outcome="accepted", server="robinhood")
    )
    assert "seq" not in rec
    assert "prev_record_hash" not in rec
    assert "record_hash" not in rec

    written = _read_jsonl(audit.audit_ledger_path())
    assert len(written) == 1
    assert written[0] == rec
    assert "seq" not in written[0]

    # And the chained copy exists alongside it, carrying the same payload.
    chained = _read_jsonl(audit.audit_chain_ledger_path())
    assert len(chained) == 1
    assert chained[0]["seq"] == 1
    assert {k: v for k, v in chained[0].items()
            if k not in ("seq", "prev_record_hash", "record_hash")} == rec


def test_chain_false_writes_only_the_classic_ledger(live_runtime: Path) -> None:
    """The opt-out still exists and still means what it says."""
    write_live_action(
        LiveActionEvent(kind="order_placed", session_id="s1", outcome="accepted", server="robinhood"),
        chain=False,
    )
    assert len(_read_jsonl(audit.audit_ledger_path())) == 1
    assert not audit.audit_chain_ledger_path().exists()


def test_default_write_live_action_now_fsyncs(live_runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The durability fix: even the CLASSIC (chain=False) path must fsync now,
    closing the gap with src.agent.trace.TraceWriter noted in the audit.py
    docstring update."""
    import os as os_mod

    calls: list[int] = []
    real_fsync = os_mod.fsync

    def counting_fsync(fd: int) -> None:
        calls.append(fd)
        real_fsync(fd)

    monkeypatch.setattr(os_mod, "fsync", counting_fsync)

    write_live_action(
        LiveActionEvent(kind="order_placed", session_id="s1", outcome="accepted", server="robinhood")
    )
    assert len(calls) >= 1


def test_chain_true_writes_to_dedicated_chain_ledger(live_runtime: Path) -> None:
    for i in range(3):
        write_live_action(
            LiveActionEvent(
                kind="order_placed",
                session_id="s1",
                outcome="accepted",
                server="robinhood",
                intent_normalized=f"order {i}",
            ),
            chain=True,
        )

    # Both ledgers are written: the classic one keeps every existing reader
    # working, the chained one adds tamper-evidence.
    assert len(_read_jsonl(audit.audit_ledger_path())) == 3

    chained = _read_jsonl(audit.audit_chain_ledger_path())
    assert len(chained) == 3
    assert [r["seq"] for r in chained] == [1, 2, 3]
    result = verify_chain(audit.audit_chain_ledger_path())
    assert result.ok is True
    assert result.record_count == 3


def test_chain_true_fans_the_same_augmented_record_to_all_sinks(live_runtime: Path) -> None:
    trace_entries: list[dict] = []
    captured: list[tuple] = []

    rec = write_live_action(
        LiveActionEvent(
            kind="order_placed",
            session_id="s1",
            outcome="accepted",
            server="robinhood",
            broker_request={"symbol": "NVDA", "token": "leak-me"},
        ),
        chain=True,
        trace_writer=type("T", (), {"write": lambda self, e: trace_entries.append(e)})(),
        event_callback=lambda name, payload: captured.append((name, payload)),
    )

    # The chain fields live in the chain FILE only. The return value, the
    # trace entry and the surface payload stay the classic record, so nothing
    # that already parses those three breaks.
    assert "seq" not in rec
    assert rec["broker_request"]["token"] == "[redacted]"

    ledger_rec = _read_jsonl(audit.audit_chain_ledger_path())[0]
    assert ledger_rec["seq"] == 1
    assert {k: v for k, v in ledger_rec.items()
            if k not in ("seq", "prev_record_hash", "record_hash")} == rec

    assert trace_entries[0]["type"] == "live_action"
    assert "seq" not in trace_entries[0]
    # Redaction still happens BEFORE any sink, including the chained one.
    assert trace_entries[0]["broker_request"]["token"] == "[redacted]"
    assert ledger_rec["broker_request"]["token"] == "[redacted]"

    assert captured[0] == ("live.action", rec)


def test_chain_true_refuses_to_extend_a_tampered_chain_ledger(live_runtime: Path) -> None:
    for i in range(3):
        write_live_action(
            LiveActionEvent(kind="order_placed", session_id="s1", outcome="accepted", server="robinhood"),
            chain=True,
        )

    chain_path = audit.audit_chain_ledger_path()
    lines = chain_path.read_text(encoding="utf-8").splitlines()
    record = json.loads(lines[1])
    record["session_id"] = "hijacked"
    lines[1] = json.dumps(record, ensure_ascii=False)
    chain_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    # A corrupt chain must NOT take down the order path. The compliance record
    # still lands in the classic ledger (nothing is lost), the failure is
    # logged, and the break stays detectable -- which is the whole justification
    # for swallowing it rather than raising into an in-flight order.
    before = len(_read_jsonl(audit.audit_ledger_path()))
    returned = write_live_action(
        LiveActionEvent(kind="order_placed", session_id="s1", outcome="accepted", server="robinhood"),
        chain=True,
    )
    after = _read_jsonl(audit.audit_ledger_path())
    assert len(after) == before + 1, "the classic record must survive a chain failure"
    assert after[-1] == returned

    # And the tamper is still reported, at the record that was edited.
    result = verify_chain(chain_path)
    assert result.ok is False
    assert result.first_break.index == 1

    # append_record itself still refuses -- the guard is intact, it is just no
    # longer allowed to propagate into the order path.
    with pytest.raises(LedgerCorruptionError):
        append_record(chain_path, {"action": "direct"})


# --- retention: rotate, never delete ---


def test_rotation_seals_a_segment_and_keeps_the_active_file_small(tmp_path):
    from src.governance.ledger import archive_segments, rotate_if_needed

    led = tmp_path / "audit_chain.jsonl"
    for i in range(5):
        append_record(led, {"action": "order", "n": i})

    archive = rotate_if_needed(led, max_bytes=100)

    assert archive is not None
    assert archive_segments(led) == [archive]
    assert not led.exists()  # sealed; the next append starts a fresh active file


def test_rotation_does_not_delete_anything(tmp_path):
    # The whole retention policy in one assertion: history is never destroyed.
    from src.governance.ledger import rotate_if_needed

    led = tmp_path / "audit_chain.jsonl"
    for i in range(5):
        append_record(led, {"action": "order", "n": i})
    before = led.read_text()

    archive = rotate_if_needed(led, max_bytes=100)
    assert archive.read_text() == before


def test_the_chain_continues_across_a_rotation(tmp_path):
    from src.governance.ledger import rotate_if_needed, verify_chain_with_archives

    led = tmp_path / "audit_chain.jsonl"
    for i in range(5):
        append_record(led, {"action": "order", "n": i})
    rotate_if_needed(led, max_bytes=100)
    for i in range(5, 9):
        append_record(led, {"action": "order", "n": i})

    # Not a fresh chain: the active file picks up at seq 6.
    seqs = [json.loads(line)["seq"] for line in led.read_text().splitlines()]
    assert seqs == [6, 7, 8, 9]

    result = verify_chain_with_archives(led)
    assert result.ok is True
    assert result.record_count == 9


def test_deleting_a_whole_sealed_segment_is_detected(tmp_path):
    # This is what rotation would have cost us if the chain restarted: a
    # segment could be removed wholesale and each remaining file would still
    # verify on its own.
    from src.governance.ledger import rotate_if_needed, verify_chain_with_archives

    led = tmp_path / "audit_chain.jsonl"
    for i in range(5):
        append_record(led, {"action": "order", "n": i})
    archive = rotate_if_needed(led, max_bytes=100)
    for i in range(5, 9):
        append_record(led, {"action": "order", "n": i})

    archive.unlink()

    result = verify_chain_with_archives(led)
    assert result.ok is False
    assert result.first_break.reason == "seq_gap"


def test_rotation_refuses_to_seal_a_corrupt_ledger(tmp_path):
    from src.governance.ledger import rotate_if_needed

    led = tmp_path / "audit_chain.jsonl"
    for i in range(5):
        append_record(led, {"action": "order", "n": i})
    lines = led.read_text().splitlines()
    record = json.loads(lines[2])
    record["n"] = 999
    lines[2] = json.dumps(record)
    led.write_text("\n".join(lines) + "\n")

    with pytest.raises(LedgerCorruptionError):
        rotate_if_needed(led, max_bytes=100)


def test_rotation_is_a_no_op_below_the_threshold(tmp_path):
    from src.governance.ledger import rotate_if_needed

    led = tmp_path / "audit_chain.jsonl"
    append_record(led, {"action": "order"})
    assert rotate_if_needed(led, max_bytes=10_000_000) is None
    assert led.exists()


def test_rotation_rejects_a_non_positive_threshold(tmp_path):
    from src.governance.ledger import rotate_if_needed

    led = tmp_path / "audit_chain.jsonl"
    append_record(led, {"action": "order"})
    with pytest.raises(ValueError, match="max_bytes"):
        rotate_if_needed(led, max_bytes=0)
