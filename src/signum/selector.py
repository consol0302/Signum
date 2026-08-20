from __future__ import annotations

import numpy as np

from .config import SamplerConfig
from .models import Candidate


def signature_distance(left: Candidate, right: Candidate) -> float:
    if left.signature.shape != right.signature.shape or left.signature.size == 0:
        return 1.0
    return float(
        np.mean(
            np.abs(left.signature.astype(np.float32) - right.signature.astype(np.float32))
        )
        / 255.0
    )


def uniform_select(candidates: list[Candidate], budget: int) -> list[Candidate]:
    if budget >= len(candidates):
        return list(candidates)
    positions = np.linspace(0, len(candidates) - 1, budget)
    indices = sorted({int(round(value)) for value in positions})
    # Rounding can theoretically collide; fill deterministically if it does.
    for index in range(len(candidates)):
        if len(indices) >= budget:
            break
        if index not in indices:
            indices.append(index)
    return [candidates[index] for index in sorted(indices[:budget])]


def _is_temporally_allowed(
    candidate: Candidate, selected: list[Candidate], minimum_distance: float
) -> bool:
    return all(
        abs(candidate.timestamp - item.timestamp) >= minimum_distance for item in selected
    )


def _is_distinct(
    candidate: Candidate, selected: list[Candidate], threshold: float
) -> bool:
    return all(signature_distance(candidate, item) >= threshold for item in selected)


def _ranked(candidates: list[Candidate]) -> list[Candidate]:
    return sorted(candidates, key=lambda item: (-item.importance, item.frame_index))


def score_only_select(
    candidates: list[Candidate], config: SamplerConfig
) -> list[Candidate]:
    target = min(config.budget, len(candidates))
    selected: list[Candidate] = []
    ranked = _ranked(candidates)
    _append_pass(ranked, selected, target, config, require_gap=True, require_distinct=True)
    _append_pass(ranked, selected, target, config, require_gap=False, require_distinct=True)
    _append_pass(ranked, selected, target, config, require_gap=False, require_distinct=False)
    return sorted(selected, key=lambda item: item.frame_index)


def hybrid_select(candidates: list[Candidate], config: SamplerConfig) -> list[Candidate]:
    """Reserve coverage anchors, then spend remaining budget on importance."""

    target = min(config.budget, len(candidates))
    if target == 0:
        return []
    anchor_count = min(target, max(1, int(round(target * config.coverage_fraction))))
    anchors = uniform_select(candidates, anchor_count)
    selected: list[Candidate] = []
    _append_pass(anchors, selected, target, config, require_gap=False, require_distinct=True)
    ranked = _ranked(candidates)
    _append_pass(ranked, selected, target, config, require_gap=True, require_distinct=True)
    _append_pass(ranked, selected, target, config, require_gap=False, require_distinct=True)
    _append_pass(ranked, selected, target, config, require_gap=False, require_distinct=False)
    return sorted(selected, key=lambda item: item.frame_index)


def _append_pass(
    source: list[Candidate],
    selected: list[Candidate],
    target: int,
    config: SamplerConfig,
    *,
    require_gap: bool,
    require_distinct: bool,
) -> None:
    selected_indices = {item.frame_index for item in selected}
    for candidate in source:
        if len(selected) >= target:
            return
        if candidate.frame_index in selected_indices:
            continue
        if require_gap and not _is_temporally_allowed(
            candidate, selected, config.min_distance_seconds
        ):
            continue
        if require_distinct and not _is_distinct(
            candidate, selected, config.duplicate_threshold
        ):
            continue
        selected.append(candidate)
        selected_indices.add(candidate.frame_index)


def select_candidates(
    candidates: list[Candidate], config: SamplerConfig
) -> list[Candidate]:
    if config.strategy == "uniform":
        return uniform_select(candidates, config.budget)
    if config.strategy == "score_only":
        return score_only_select(candidates, config)
    return hybrid_select(candidates, config)
