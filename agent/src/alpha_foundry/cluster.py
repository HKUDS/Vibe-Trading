from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from src.alpha_foundry.novelty import compute_novelty


@dataclass
class FactorCluster:
    cluster_id: str
    representative_factor_id: str
    members: list[str] = field(default_factory=list)


def cluster_by_rank_correlation(
    factors: dict[str, pd.DataFrame],
    *,
    threshold: float = 0.90,
) -> list[FactorCluster]:
    clusters: list[FactorCluster] = []
    representatives: dict[str, pd.DataFrame] = {}

    for factor_id, panel in factors.items():
        if not representatives:
            clusters.append(
                FactorCluster(
                    cluster_id=f"cluster-1",
                    representative_factor_id=factor_id,
                    members=[factor_id],
                )
            )
            representatives[factor_id] = panel
            continue

        metrics = compute_novelty(candidate=panel, existing=representatives)
        if metrics.max_factor_rank_corr_to_existing >= threshold:
            for cluster in clusters:
                if cluster.representative_factor_id == metrics.nearest_existing_factor_id:
                    cluster.members.append(factor_id)
                    break
        else:
            cluster_id = f"cluster-{len(clusters) + 1}"
            clusters.append(
                FactorCluster(
                    cluster_id=cluster_id,
                    representative_factor_id=factor_id,
                    members=[factor_id],
                )
            )
            representatives[factor_id] = panel

    return clusters
