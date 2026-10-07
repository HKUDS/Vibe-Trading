"""The generated broker capability matrix must match the profile registry (#1626)."""

from __future__ import annotations

from src.trading.capability_matrix import README_PATH, render, render_block, sync_readme
from src.trading.profiles import BUILTIN_PROFILES


def test_capability_matrix_block_in_readme_is_current() -> None:
    """CI drift guard: the README's marked block equals a fresh render.

    Fails red when a connector profile changed without regenerating:
    python -m src.trading.capability_matrix
    """
    text = README_PATH.read_text(encoding="utf-8")
    assert render_block() in text, (
        "README's broker-capability-matrix block is stale; regenerate with python -m src.trading.capability_matrix"
    )


def _rows() -> dict[str, list[str]]:
    return {
        cells[0].strip("`"): cells
        for line in render().splitlines()
        if line.startswith("| `")
        for cells in [[cell.strip() for cell in line.strip("|").split("|")]]
    }


def test_each_profile_keeps_its_own_permissions_and_transport() -> None:
    rows = _rows()
    assert set(rows) == {p.id for p in BUILTIN_PROFILES}
    assert len(rows) == len(BUILTIN_PROFILES)
    for profile in BUILTIN_PROFILES:
        row = rows[profile.id]
        assert row[1:4] == [profile.connector, profile.environment, profile.transport]
        assert row[4] == ("read-only" if profile.readonly else "write-enabled")
        rendered_caps = set()
        for cell in (row[5], row[7]):
            if cell != "none declared":
                rendered_caps.update(item.strip("`") for item in cell.split(", "))
        assert rendered_caps == set(profile.capabilities)
        assert row[6] == (profile.transport if "quotes.read" in profile.capabilities else "none declared")


def test_paper_order_capability_never_becomes_a_live_permission() -> None:
    rows = _rows()
    for broker in ("upbit", "dhan", "shoonya", "zerodha", "longbridge"):
        profiles = [p for p in BUILTIN_PROFILES if p.connector == broker]
        assert any(p.environment == "paper" and "orders.place" in p.capabilities for p in profiles)
        for profile in profiles:
            if profile.environment == "live":
                assert rows[profile.id][8] == "disabled (read-only)"
                assert "orders.place" not in rows[profile.id][7]
    assert rows["alpaca-live-trade"][8] == "mandate required"
    assert rows["robinhood-live-mcp"][8] == "mandate required"
    assert rows["robinhood-live-mcp-readonly"][6] == "none declared"
    assert "positions.edit" in rows["etoro-live-trade"][7]


def test_only_builtin_declarations_are_rendered(monkeypatch) -> None:
    from dataclasses import replace
    from src.trading import capability_matrix

    profile = replace(
        BUILTIN_PROFILES[0],
        id="test-profile",
        capabilities=("quotes.read", "future.capability"),
        config={"credential": "DO-NOT-PUBLISH"},
        notes="DO-NOT-PUBLISH",
    )
    monkeypatch.setattr(capability_matrix, "BUILTIN_PROFILES", (profile,))
    rendered = render()
    assert "DO-NOT-PUBLISH" not in rendered
    assert "future.capability" in rendered
    assert "not successful runtime" in rendered


def test_sync_readme_replaces_only_the_marked_block() -> None:
    text = README_PATH.read_text(encoding="utf-8")
    synced = sync_readme(text)
    assert synced == text  # already current
    # drift the block's content while keeping the markers, as a profile edit
    # without regeneration would
    without = text.replace(render(), "stale\n")
    assert sync_readme(without) == text  # regenerates back to current


def test_sync_readme_rejects_missing_or_duplicate_markers() -> None:
    import pytest

    for text in ("no block", render_block() + render_block()):
        with pytest.raises(ValueError):
            sync_readme(text)
