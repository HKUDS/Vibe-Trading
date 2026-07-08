from __future__ import annotations

from src.alpha_foundry.seed_bank import AlphaSeed, SeedBank


def test_seed_bank_loads_unique_seed_ids() -> None:
    bank = SeedBank(
        [
            AlphaSeed(seed_id="seed_a", formula="rank(close)", source="fixture"),
            AlphaSeed(seed_id="seed_b", formula="rank(volume)", source="fixture"),
        ]
    )

    assert [seed.seed_id for seed in bank.list()] == ["seed_a", "seed_b"]
    assert bank.get("seed_a").formula == "rank(close)"


def test_seed_bank_rejects_duplicate_seed_ids() -> None:
    try:
        SeedBank(
            [
                AlphaSeed(seed_id="dup", formula="rank(close)", source="fixture"),
                AlphaSeed(seed_id="dup", formula="rank(volume)", source="fixture"),
            ]
        )
    except ValueError as exc:
        assert "duplicate seed_id" in str(exc)
    else:
        raise AssertionError("duplicate seed ids must be rejected")
