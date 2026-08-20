from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from .config import SamplerConfig
from .models import Candidate, VideoMetadata
from .video import iter_frames, resized_gray


@dataclass(frozen=True)
class CandidateAnalysis:
    candidates: list[Candidate]
    scheduled_candidate_count: int
    coarse_scanned_frames: int
    promoted_spike_count: int


def _histogram(gray: np.ndarray) -> np.ndarray:
    hist = cv2.calcHist([gray], [0], None, [32], [0, 256])
    return cv2.normalize(hist, hist, norm_type=cv2.NORM_L1).flatten()


def analyze_candidates(
    metadata: VideoMetadata, indices: list[int], config: SamplerConfig
) -> CandidateAnalysis:
    candidates: list[Candidate] = []
    scheduled = set(indices)
    previous_gray: np.ndarray | None = None
    previous_hist: np.ndarray | None = None
    previous_tiny: np.ndarray | None = None
    coarse_records: list[tuple[int, float, float, np.ndarray]] = []
    half_step = 0.5 / config.candidate_hz

    for frame_index, frame in iter_frames(metadata):
        tiny: np.ndarray | None = None
        if config.spike_guard:
            tiny = _tiny_gray(frame)
            coarse_difference = 0.0
            coarse_motion = 0.0
            if previous_tiny is not None:
                tiny_delta = cv2.absdiff(tiny, previous_tiny)
                coarse_difference = float(np.mean(tiny_delta) / 255.0)
                coarse_motion = float(
                    np.mean(tiny_delta >= config.motion_pixel_threshold)
                )
            coarse_records.append(
                (frame_index, coarse_difference, coarse_motion, tiny.copy())
            )
            previous_tiny = tiny

        if frame_index not in scheduled:
            continue
        if tiny is None:
            tiny = _tiny_gray(frame)
        gray = resized_gray(frame, config.analysis_width)
        hist = _histogram(gray)
        timestamp = frame_index / metadata.fps
        candidate = Candidate(
            frame_index=frame_index,
            timestamp=timestamp,
            source_start=max(0.0, timestamp - half_step),
            source_end=min(metadata.duration_seconds, timestamp + half_step),
            signature=tiny.copy(),
        )
        if previous_gray is not None and previous_hist is not None:
            difference = cv2.absdiff(gray, previous_gray)
            candidate.frame_difference = float(np.mean(difference) / 255.0)
            candidate.motion_score = float(
                np.mean(difference >= config.motion_pixel_threshold)
            )
            candidate.histogram_difference = float(
                cv2.compareHist(hist, previous_hist, cv2.HISTCMP_BHATTACHARYYA)
            )
        candidates.append(candidate)
        previous_gray = gray
        previous_hist = hist

    promoted = (
        _promote_spikes(metadata, coarse_records, scheduled, config)
        if config.spike_guard
        else []
    )
    candidates.extend(promoted)
    candidates.sort(key=lambda item: item.frame_index)
    _score_candidates(candidates, config)
    return CandidateAnalysis(
        candidates=candidates,
        scheduled_candidate_count=len(indices),
        coarse_scanned_frames=len(coarse_records),
        promoted_spike_count=len(promoted),
    )


def _tiny_gray(frame: np.ndarray) -> np.ndarray:
    tiny = cv2.resize(frame, (16, 9), interpolation=cv2.INTER_AREA)
    return cv2.cvtColor(tiny, cv2.COLOR_BGR2GRAY)


def _promote_spikes(
    metadata: VideoMetadata,
    records: list[tuple[int, float, float, np.ndarray]],
    scheduled: set[int],
    config: SamplerConfig,
) -> list[Candidate]:
    """Promote the first frame of each abrupt full-frame change run.

    Consecutive above-threshold frames are treated as one transition. Choosing
    the first frame keeps a one-frame flash rather than its return to the
    unchanged background.
    """

    promoted: list[Candidate] = []
    previous_above = False
    frame_half_width = 0.5 / metadata.fps
    for frame_index, difference, motion, signature in records:
        above = difference >= config.spike_threshold
        if above and not previous_above and frame_index not in scheduled:
            timestamp = frame_index / metadata.fps
            promoted.append(
                Candidate(
                    frame_index=frame_index,
                    timestamp=timestamp,
                    source_start=max(0.0, timestamp - frame_half_width),
                    source_end=min(
                        metadata.duration_seconds, timestamp + frame_half_width
                    ),
                    frame_difference=difference,
                    motion_score=motion,
                    signature=signature,
                    discovery="spike_guard",
                )
            )
        previous_above = above
    return promoted


def _robust_scale(values: np.ndarray) -> np.ndarray:
    nonzero = values[values > 0]
    if nonzero.size == 0:
        return np.zeros_like(values)
    scale = float(np.percentile(nonzero, 95))
    if scale <= 1e-12:
        return np.zeros_like(values)
    return np.clip(values / scale, 0.0, 1.5)


def _score_candidates(candidates: list[Candidate], config: SamplerConfig) -> None:
    if not candidates:
        return
    frame = _robust_scale(np.array([c.frame_difference for c in candidates]))
    histogram = _robust_scale(np.array([c.histogram_difference for c in candidates]))
    motion = _robust_scale(np.array([c.motion_score for c in candidates]))
    weight_sum = config.frame_weight + config.histogram_weight + config.motion_weight

    for index, candidate in enumerate(candidates):
        candidate.scene_change = bool(
            candidate.frame_difference >= config.scene_threshold
            or candidate.histogram_difference >= config.scene_threshold
        )
        weighted = (
            config.frame_weight * frame[index]
            + config.histogram_weight * histogram[index]
            + config.motion_weight * motion[index]
        ) / weight_sum
        candidate.importance = float(
            weighted + (config.scene_boost if candidate.scene_change else 0.0)
        )
