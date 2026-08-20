from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Literal


Strategy = Literal["hybrid", "score_only", "uniform"]


@dataclass(frozen=True)
class SamplerConfig:
    """Deterministic sampler configuration.

    Weights apply after each signal is normalized by its per-video non-zero
    95th percentile. They express relative priority, not learned probability.
    """

    budget: int = 32
    candidate_hz: float = 4.0
    analysis_width: int = 192
    min_distance_seconds: float = 0.5
    coverage_fraction: float = 0.25
    duplicate_threshold: float = 0.012
    motion_pixel_threshold: int = 18
    frame_weight: float = 0.45
    histogram_weight: float = 0.20
    motion_weight: float = 0.35
    scene_threshold: float = 0.45
    scene_boost: float = 0.25
    strategy: Strategy = "hybrid"

    def validate(self) -> None:
        if self.budget <= 0:
            raise ValueError("budget must be greater than zero")
        if self.candidate_hz <= 0:
            raise ValueError("candidate_hz must be greater than zero")
        if self.analysis_width < 16:
            raise ValueError("analysis_width must be at least 16")
        if self.min_distance_seconds < 0:
            raise ValueError("min_distance_seconds cannot be negative")
        if not 0 <= self.coverage_fraction <= 1:
            raise ValueError("coverage_fraction must be between 0 and 1")
        if not 0 <= self.duplicate_threshold <= 1:
            raise ValueError("duplicate_threshold must be between 0 and 1")
        if self.motion_pixel_threshold < 0 or self.motion_pixel_threshold > 255:
            raise ValueError("motion_pixel_threshold must be between 0 and 255")
        if min(self.frame_weight, self.histogram_weight, self.motion_weight) < 0:
            raise ValueError("signal weights cannot be negative")
        if self.frame_weight + self.histogram_weight + self.motion_weight <= 0:
            raise ValueError("at least one signal weight must be positive")
        if self.strategy not in ("hybrid", "score_only", "uniform"):
            raise ValueError(f"unknown strategy: {self.strategy}")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)
