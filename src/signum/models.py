from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np


@dataclass(frozen=True)
class VideoMetadata:
    path: Path
    fps: float
    frame_count: int
    width: int
    height: int
    fourcc: str

    @property
    def duration_seconds(self) -> float:
        return self.frame_count / self.fps if self.fps > 0 else 0.0

    def to_dict(self) -> dict[str, object]:
        return {
            "path": str(self.path.resolve()),
            "duration_seconds": self.duration_seconds,
            "fps": self.fps,
            "frame_count": self.frame_count,
            "width": self.width,
            "height": self.height,
            "codec_fourcc": self.fourcc,
        }


@dataclass
class Candidate:
    frame_index: int
    timestamp: float
    source_start: float
    source_end: float
    frame_difference: float = 0.0
    histogram_difference: float = 0.0
    motion_score: float = 0.0
    scene_change: bool = False
    importance: float = 0.0
    discovery: str = "scheduled"
    signature: np.ndarray = field(
        default_factory=lambda: np.empty((0, 0), dtype=np.uint8), repr=False
    )

    def to_dict(self) -> dict[str, object]:
        return {
            "frame_index": self.frame_index,
            "timestamp": self.timestamp,
            "source_interval": [self.source_start, self.source_end],
            "importance": self.importance,
            "discovery": self.discovery,
            "signals": {
                "frame_difference": self.frame_difference,
                "histogram_difference": self.histogram_difference,
                "motion_score": self.motion_score,
                "scene_change": self.scene_change,
            },
        }
