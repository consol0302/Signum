from __future__ import annotations

import argparse
import hashlib
import json
import math
from bisect import bisect_right
from pathlib import Path
from typing import Any

import cv2


class EncodingError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Encode timestamped browser PNG frames without discarding source timing."
    )
    parser.add_argument("capture", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--fps", type=float, default=30.0)
    parser.add_argument("--allow-invalid", action="store_true")
    return parser.parse_args()


def resample_mapping(
    frames: list[dict[str, Any]],
    *,
    duration_seconds: float,
    output_fps: float,
) -> list[dict[str, Any]]:
    if output_fps <= 0 or not math.isfinite(output_fps):
        raise EncodingError("output fps must be finite and positive")
    if duration_seconds <= 0 or not math.isfinite(duration_seconds):
        raise EncodingError("capture duration must be finite and positive")
    if not frames:
        raise EncodingError("capture contains no frames")
    source_timestamps = [float(frame["timestamp_seconds"]) for frame in frames]
    if any(
        not math.isfinite(value) or value < 0 for value in source_timestamps
    ) or source_timestamps != sorted(source_timestamps):
        raise EncodingError("source frame timestamps must be finite and ordered")
    origin = source_timestamps[0]
    timestamps = [value - origin for value in source_timestamps]
    output_count = max(1, int(math.ceil(duration_seconds * output_fps)))
    mapping = []
    for output_index in range(output_count):
        output_timestamp = output_index / output_fps
        source_position = max(0, bisect_right(timestamps, output_timestamp) - 1)
        source = frames[source_position]
        mapping.append(
            {
                "output_frame_index": output_index,
                "output_timestamp_seconds": output_timestamp,
                "source_sequence": int(source["sequence"]),
                "source_timestamp_seconds": source_timestamps[source_position],
                "source_relative_timestamp_seconds": timestamps[source_position],
                "source_file": source["file"],
                "source_age_seconds": max(
                    0.0, output_timestamp - timestamps[source_position]
                ),
            }
        )
    return mapping


def encode_capture(
    capture_path: Path,
    output_path: Path,
    *,
    output_fps: float,
    allow_invalid: bool = False,
) -> dict[str, Any]:
    capture_source = capture_path.resolve()
    capture = _read_object(capture_source, "capture")
    if capture.get("schema_version") != 1:
        raise EncodingError("capture must use schema_version 1")
    if capture.get("valid") is not True and not allow_invalid:
        raise EncodingError("refusing to encode a capture marked invalid")
    frames = capture.get("frames")
    if not isinstance(frames, list) or not frames:
        raise EncodingError("capture frames must be a non-empty array")
    policy = capture.get("capture_policy")
    if not isinstance(policy, dict):
        raise EncodingError("capture is missing capture_policy")
    duration = float(policy.get("duration_seconds"))
    mapping = resample_mapping(
        frames,
        duration_seconds=duration,
        output_fps=output_fps,
    )
    destination = output_path.resolve()
    report_path = destination.with_suffix(".encoding.json")
    if destination.exists() or report_path.exists():
        raise EncodingError("refusing to overwrite an existing video or encoding report")
    destination.parent.mkdir(parents=True, exist_ok=True)

    first_path = capture_source.parent / str(frames[0]["file"])
    first = cv2.imread(str(first_path), cv2.IMREAD_COLOR)
    if first is None:
        raise EncodingError(f"could not read source frame: {first_path}")
    height, width = first.shape[:2]
    source_rows = {int(frame["sequence"]): frame for frame in frames}
    writer = cv2.VideoWriter(
        str(destination),
        cv2.VideoWriter_fourcc(*"MJPG"),
        output_fps,
        (width, height),
    )
    if not writer.isOpened():
        raise EncodingError(f"could not create output video: {destination}")
    cached_sequence: int | None = None
    cached_image = None
    try:
        for row in mapping:
            sequence = int(row["source_sequence"])
            if sequence != cached_sequence:
                source = capture_source.parent / str(source_rows[sequence]["file"])
                cached_image = cv2.imread(str(source), cv2.IMREAD_COLOR)
                if cached_image is None:
                    raise EncodingError(f"could not read source frame: {source}")
                if cached_image.shape[:2] != (height, width):
                    raise EncodingError("source frame dimensions changed during capture")
                cached_sequence = sequence
            assert cached_image is not None
            writer.write(cached_image)
    finally:
        writer.release()

    decoded = cv2.VideoCapture(str(destination))
    if not decoded.isOpened():
        raise EncodingError("encoded video could not be reopened")
    try:
        decoded_count = int(decoded.get(cv2.CAP_PROP_FRAME_COUNT))
        decoded_fps = float(decoded.get(cv2.CAP_PROP_FPS))
        decoded_width = int(decoded.get(cv2.CAP_PROP_FRAME_WIDTH))
        decoded_height = int(decoded.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        decoded.release()
    used_sequences = {int(row["source_sequence"]) for row in mapping}
    source_sequences = {int(frame["sequence"]) for frame in frames}
    max_source_age = max(float(row["source_age_seconds"]) for row in mapping)
    report = {
        "schema_version": 1,
        "status": "completed",
        "capture": str(capture_source),
        "capture_sha256": _sha256_file(capture_source),
        "capture_bytes": capture_source.stat().st_size,
        "capture_valid": capture.get("valid"),
        "video": str(destination),
        "video_sha256": _sha256_file(destination),
        "video_bytes": destination.stat().st_size,
        "output_fps": output_fps,
        "output_frame_count": len(mapping),
        "source_frame_count": len(frames),
        "used_source_frame_count": len(used_sequences),
        "unused_source_sequences": sorted(source_sequences - used_sequences),
        "maximum_source_age_seconds": max_source_age,
        "decoded_video": {
            "fps": decoded_fps,
            "frame_count": decoded_count,
            "width": decoded_width,
            "height": decoded_height,
        },
        "mapping": mapping,
    }
    if decoded_count != len(mapping) or (decoded_width, decoded_height) != (
        width,
        height,
    ):
        raise EncodingError("encoded video verification failed")
    report_path.write_text(_json_text(report), encoding="utf-8")
    return report


def _read_object(path: Path, kind: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EncodingError(f"{kind} file was not found: {path}") from error
    except json.JSONDecodeError as error:
        raise EncodingError(f"{kind} file is invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise EncodingError(f"{kind} file must contain an object")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True) + "\n"


def main() -> None:
    args = parse_args()
    report = encode_capture(
        args.capture,
        args.output,
        output_fps=args.fps,
        allow_invalid=args.allow_invalid,
    )
    print(
        json.dumps(
            {
                "status": report["status"],
                "video": report["video"],
                "output_frames": report["output_frame_count"],
                "source_frames": report["source_frame_count"],
                "unused_source_frames": len(report["unused_source_sequences"]),
                "maximum_source_age_seconds": report["maximum_source_age_seconds"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
