from __future__ import annotations


def bonferroni_adjusted_p_value(selected_p_value: float, trial_count: int) -> float:
    if trial_count < 1:
        raise ValueError("trial_count must be >= 1")
    if selected_p_value < 0:
        raise ValueError("selected_p_value must be non-negative")
    return min(1.0, selected_p_value * trial_count)
