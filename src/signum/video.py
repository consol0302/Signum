from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import cv2
import numpy as np

from .models import VideoMetadata


class VideoError(RuntimeError):
    pass


def _decode_fourcc(value: float) -> str:
    integer = int(value)
    return "".join(chr((integer >> (8 * i)) & 0xFF) for i in range(4)).strip("\x00")


def probe_video(path: Path) -> VideoMetadata:
    source = Path(path)
    if not source.is_file():
        raise VideoError(f"video does not exist: {source}")

    capture = cv2.VideoCapture(str(source))
    if not capture.isOpened():
        raise VideoError(f"OpenCV could not open video: {source}")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        frame_count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fourcc = _decode_fourcc(capture.get(cv2.CAP_PROP_FOURCC))
    finally:
        capture.release()

    if fps <= 0 or frame_count <= 0 or width <= 0 or height <= 0:
        raise VideoError(
            f"invalid video metadata: fps={fps}, frames={frame_count}, size={width}x{height}"
        )
    return VideoMetadata(source, fps, frame_count, width, height, fourcc)


def candidate_indices(metadata: VideoMetadata, candidate_hz: float) -> list[int]:
    step = max(1, int(round(metadata.fps / candidate_hz)))
    indices = list(range(0, metadata.frame_count, step))
    last = metadata.frame_count - 1
    if indices[-1] != last:
        indices.append(last)
    return indices


def iter_candidate_frames(
    metadata: VideoMetadata, indices: list[int]
) -> Iterator[tuple[int, np.ndarray]]:
    """Decode sequentially, yielding only requested frames."""

    wanted = set(indices)
    for frame_index, frame in iter_frames(metadata):
        if frame_index in wanted:
            yield frame_index, frame


def iter_frames(metadata: VideoMetadata) -> Iterator[tuple[int, np.ndarray]]:
    """Decode every source frame in display order."""

    capture = cv2.VideoCapture(str(metadata.path))
    if not capture.isOpened():
        raise VideoError(f"OpenCV could not open video: {metadata.path}")
    try:
        frame_index = 0
        while True:
            ok, frame = capture.read()
            if not ok:
                break
            yield frame_index, frame
            frame_index += 1
    finally:
        capture.release()
    if frame_index < metadata.frame_count:
        raise VideoError(
            f"decode stopped at frame {frame_index} of {metadata.frame_count}"
        )


def resized_gray(frame: np.ndarray, max_width: int) -> np.ndarray:
    height, width = frame.shape[:2]
    if width > max_width:
        scale = max_width / width
        frame = cv2.resize(
            frame,
            (max_width, max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def extract_frames(
    metadata: VideoMetadata, frame_indices: list[int], frames_dir: Path
) -> dict[int, str]:
    frames_dir.mkdir(parents=True, exist_ok=True)
    ordered = sorted(set(frame_indices))
    names: dict[int, str] = {}
    for index, frame in iter_candidate_frames(metadata, ordered):
        timestamp = index / metadata.fps
        name = f"frame_{index:09d}_{timestamp:012.3f}s.jpg"
        destination = frames_dir / name
        if not cv2.imwrite(str(destination), frame):
            raise VideoError(f"failed to write frame: {destination}")
        names[index] = name
    if len(names) != len(ordered):
        missing = sorted(set(ordered) - names.keys())
        raise VideoError(f"failed to extract frame indices: {missing}")
    return names
