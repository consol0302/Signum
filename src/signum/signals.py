from __future__ import annotations

import cv2
import numpy as np

from .config import SamplerConfig
from .models import Candidate, VideoMetadata
from .video import iter_candidate_frames, resized_gray


def _histogram(gray: np.ndarray) -> np.ndarray:
    hist = cv2.calcHist([gray], [0], None, [32], [0, 256])
    return cv2.normalize(hist, hist, norm_type=cv2.NORM_L1).flatten()


def analyze_candidates(
    metadata: VideoMetadata, indices: list[int], config: SamplerConfig
) -> list[Candidate]:
    candidates: list[Candidate] = []
    previous_gray: np.ndarray | None = None
    previous_hist: np.ndarray | None = None
    half_step = 0.5 / config.candidate_hz

    for frame_index, frame in iter_candidate_frames(metadata, indices):
        gray = resized_gray(frame, config.analysis_width)
        hist = _histogram(gray)
        timestamp = frame_index / metadata.fps
        candidate = Candidate(
            frame_index=frame_index,
            timestamp=timestamp,
            source_start=max(0.0, timestamp - half_step),
            source_end=min(metadata.duration_seconds, timestamp + half_step),
            signature=cv2.resize(gray, (16, 9), interpolation=cv2.INTER_AREA),
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

    _score_candidates(candidates, config)
    return candidates


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
