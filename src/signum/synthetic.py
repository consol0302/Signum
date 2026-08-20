from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import cv2
import numpy as np


@dataclass(frozen=True)
class GroundTruthEvent:
    name: str
    start: float
    end: float
    tolerance: float = 0.10


@dataclass(frozen=True)
class SyntheticCase:
    name: str
    description: str
    duration: float
    fps: int
    budget: int
    events: tuple[GroundTruthEvent, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


WIDTH = 160
HEIGHT = 96


def _base_grid(frame_index: int = 0) -> np.ndarray:
    frame = np.full((HEIGHT, WIDTH, 3), 28, dtype=np.uint8)
    cv2.line(frame, (0, 72), (WIDTH - 1, 72), (65, 65, 65), 1)
    cv2.rectangle(frame, (8, 8), (35, 28), (52, 52, 52), -1)
    return frame


def _static_short_motion(index: int, fps: int) -> np.ndarray:
    frame = _base_grid(index)
    start, end = int(2.50 * fps), int(3.10 * fps)
    if start <= index <= end:
        progress = (index - start) / max(1, end - start)
        x = 45 + int(progress * 70)
        cv2.rectangle(frame, (x, 42), (x + 16, 58), (235, 235, 235), -1)
    return frame


def _scene_cuts(index: int, fps: int) -> np.ndarray:
    time_s = index / fps
    if time_s < 2.0:
        color = (30, 45, 150)
    elif time_s < 4.0:
        color = (140, 45, 30)
    else:
        color = (30, 145, 55)
    frame = np.full((HEIGHT, WIDTH, 3), color, dtype=np.uint8)
    cv2.circle(frame, (80, 48), 15, (220, 220, 220), -1)
    return frame


def _slow_change(index: int, fps: int) -> np.ndarray:
    frame = _base_grid(index)
    time_s = index / fps
    progress = np.clip((time_s - 1.0) / 4.0, 0.0, 1.0)
    value = int(28 + 32 * progress)
    cv2.rectangle(frame, (55, 30), (105, 65), (value, value, value), -1)
    if time_s >= 4.8:
        cv2.circle(frame, (80, 47), 2, (90, 90, 90), -1)
    return frame


def _brief_flash(index: int, fps: int) -> np.ndarray:
    frame = _base_grid(index)
    # At 20 fps and 4 Hz candidate analysis, index 52 lies between candidates.
    if index == 52:
        frame[:] = 255
    return frame


def _continuous_motion(index: int, fps: int) -> np.ndarray:
    x = (index * 5) % WIDTH
    gradient = np.arange(WIDTH, dtype=np.uint8)
    shifted = np.roll(gradient, x)
    frame = np.repeat(shifted[None, :, None], HEIGHT, axis=0)
    frame = np.repeat(frame, 3, axis=2)
    if int(2.75 * fps) <= index <= int(3.05 * fps):
        cv2.circle(frame, (80, 48), 5, (0, 0, 255), -1)
    return frame


def _repetitive_motion(index: int, fps: int) -> np.ndarray:
    frame = _base_grid(index)
    phase = (index // 5) % 2
    x = 35 if phase == 0 else 105
    color = (230, 230, 230)
    if int(4.0 * fps) <= index <= int(4.3 * fps):
        color = (20, 20, 250)
    cv2.rectangle(frame, (x, 38), (x + 18, 57), color, -1)
    return frame


def _camera_pan(index: int, fps: int) -> np.ndarray:
    frame = np.zeros((HEIGHT, WIDTH, 3), dtype=np.uint8)
    offset = (index * 3) % 32
    for x in range(-offset, WIDTH, 32):
        cv2.rectangle(frame, (x, 0), (x + 15, HEIGHT - 1), (38, 52, 72), -1)
    if int(3.25 * fps) <= index <= int(3.60 * fps):
        cv2.rectangle(frame, (74, 42), (86, 54), (10, 10, 245), -1)
    return frame


CASES: tuple[tuple[SyntheticCase, Callable[[int, int], np.ndarray]], ...] = (
    (
        SyntheticCase(
            "static_short_motion",
            "mostly static with one short moving object",
            6.0,
            20,
            6,
            (GroundTruthEvent("moving_object", 2.50, 3.10),),
        ),
        _static_short_motion,
    ),
    (
        SyntheticCase(
            "hard_scene_cuts",
            "two hard cuts between stable scenes",
            6.0,
            20,
            6,
            (
                GroundTruthEvent("cut_one", 2.0, 2.05),
                GroundTruthEvent("cut_two", 4.0, 4.05),
            ),
        ),
        _scene_cuts,
    ),
    (
        SyntheticCase(
            "slow_change",
            "low-amplitude change accumulating over four seconds",
            6.0,
            20,
            6,
            (GroundTruthEvent("change_complete", 4.8, 5.2),),
        ),
        _slow_change,
    ),
    (
        SyntheticCase(
            "brief_flash",
            "one-frame flash between candidate samples",
            6.0,
            20,
            6,
            (GroundTruthEvent("flash", 2.60, 2.60, tolerance=0.03),),
        ),
        _brief_flash,
    ),
    (
        SyntheticCase(
            "continuous_motion",
            "global motion with a small local marked event",
            6.0,
            20,
            6,
            (GroundTruthEvent("local_marker", 2.75, 3.05),),
        ),
        _continuous_motion,
    ),
    (
        SyntheticCase(
            "repetitive_motion",
            "repeated large motion with a brief color change",
            6.0,
            20,
            6,
            (GroundTruthEvent("color_change", 4.0, 4.3),),
        ),
        _repetitive_motion,
    ),
    (
        SyntheticCase(
            "camera_pan",
            "continuous global panning with a small local event",
            6.0,
            20,
            6,
            (GroundTruthEvent("local_marker", 3.25, 3.60),),
        ),
        _camera_pan,
    ),
)


def generate_suite(output_dir: Path) -> list[tuple[SyntheticCase, Path]]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated: list[tuple[SyntheticCase, Path]] = []
    for case, renderer in CASES:
        path = output_dir / f"{case.name}.avi"
        writer = cv2.VideoWriter(
            str(path), cv2.VideoWriter_fourcc(*"MJPG"), case.fps, (WIDTH, HEIGHT)
        )
        if not writer.isOpened():
            raise RuntimeError("OpenCV MJPEG writer is unavailable")
        try:
            for frame_index in range(int(case.duration * case.fps)):
                writer.write(renderer(frame_index, case.fps))
        finally:
            writer.release()
        generated.append((case, path))
    return generated
