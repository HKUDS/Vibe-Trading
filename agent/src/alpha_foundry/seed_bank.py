from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class AlphaSeed:
    seed_id: str
    formula: str
    source: str
    parent_seed_id: str | None = None


class SeedBank:
    def __init__(self, seeds: list[AlphaSeed]) -> None:
        seen: set[str] = set()
        for seed in seeds:
            if seed.seed_id in seen:
                raise ValueError(f"duplicate seed_id: {seed.seed_id}")
            seen.add(seed.seed_id)
        self._seeds = list(seeds)
        self._by_id = {seed.seed_id: seed for seed in seeds}

    def list(self) -> list[AlphaSeed]:
        return list(self._seeds)

    def get(self, seed_id: str) -> AlphaSeed:
        return self._by_id[seed_id]
