from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from statistics import median
from typing import Any

import cv2


class CaptureVerificationError(RuntimeError):
    pass


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Independently verify a timestamped Signum browser capture."
    )
    parser.add_argument("capture", type=Path)
    parser.add_argument("--case-id")
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def capture_statistics(frames: list[dict[str, Any]]) -> dict[str, Any]:
    timestamps = [float(frame["timestamp_seconds"]) for frame in frames]
    intervals = [
        timestamps[index] - timestamps[index - 1]
        for index in range(1, len(timestamps))
    ]
    elapsed = timestamps[-1] - timestamps[0] if len(timestamps) > 1 else 0.0
    durations = [float(frame["capture_duration_seconds"]) for frame in frames]
    return {
        "frame_count": len(frames),
        "elapsed_seconds": elapsed,
        "effective_average_fps": (
            (len(frames) - 1) / elapsed if elapsed > 0 else None
        ),
        "interval_seconds": {
            "minimum": min(intervals) if intervals else None,
            "median": median(intervals) if intervals else None,
            "p95": _quantile(intervals, 0.95),
            "maximum": max(intervals) if intervals else None,
        },
        "capture_duration_seconds": {
            "median": median(durations) if durations else None,
            "maximum": max(durations) if durations else None,
        },
        "timestamp_range_seconds": {
            "first": timestamps[0] if timestamps else None,
            "last": timestamps[-1] if timestamps else None,
        },
    }


def verify_capture(
    capture_path: Path,
    *,
    expected_case_id: str | None = None,
) -> dict[str, Any]:
    source = capture_path.resolve()
    root = source.parent
    capture = _read_object(source, "capture")
    if capture.get("schema_version") != 1:
        raise CaptureVerificationError("capture must use schema_version 1")
    case_id = capture.get("case_id")
    if not isinstance(case_id, str) or not case_id:
        raise CaptureVerificationError("capture case_id must be a string")
    checks: list[dict[str, Any]] = []
    if expected_case_id is not None:
        checks.append(
            _check("case_id", case_id == expected_case_id, expected_case_id, case_id)
        )
    viewport = capture.get("viewport")
    if not isinstance(viewport, dict):
        raise CaptureVerificationError("capture is missing viewport")
    expected_dimensions = (
        _positive_integer(viewport.get("width"), "viewport width"),
        _positive_integer(viewport.get("height"), "viewport height"),
    )
    frames = capture.get("frames")
    if not isinstance(frames, list) or not frames:
        raise CaptureVerificationError("capture frames must be a non-empty array")
    sequences = []
    timestamps = []
    for frame in frames:
        if not isinstance(frame, dict):
            raise CaptureVerificationError("capture frames must be objects")
        sequence = frame.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 0:
            raise CaptureVerificationError("frame sequence must be non-negative")
        sequences.append(sequence)
        timestamp = frame.get("timestamp_seconds")
        if (
            not isinstance(timestamp, (int, float))
            or isinstance(timestamp, bool)
            or not math.isfinite(timestamp)
            or timestamp < 0
        ):
            raise CaptureVerificationError("frame timestamps must be finite and non-negative")
        timestamps.append(float(timestamp))
        relative = frame.get("file")
        if not isinstance(relative, str) or not relative:
            raise CaptureVerificationError("frame file must be a string")
        path = _inside(root, relative, "frame")
        expected_hash = frame.get("sha256")
        expected_bytes = frame.get("encoded_bytes")
        exists = path.is_file()
        actual_hash = _sha256_file(path) if exists else None
        actual_bytes = path.stat().st_size if exists else None
        image = cv2.imread(str(path), cv2.IMREAD_COLOR) if exists else None
        actual_dimensions = (
            (int(image.shape[1]), int(image.shape[0])) if image is not None else None
        )
        checks.append(
            {
                "kind": f"frame:{sequence}",
                "path": str(path),
                "exists": exists,
                "expected_sha256": expected_hash,
                "actual_sha256": actual_hash,
                "expected_bytes": expected_bytes,
                "actual_bytes": actual_bytes,
                "expected_dimensions": list(expected_dimensions),
                "actual_dimensions": (
                    list(actual_dimensions) if actual_dimensions else None
                ),
                "valid": (
                    exists
                    and isinstance(expected_hash, str)
                    and actual_hash == expected_hash
                    and actual_bytes == expected_bytes
                    and actual_dimensions == expected_dimensions
                ),
            }
        )
    checks.append(
        _check(
            "frame_sequence_order",
            all(
                sequences[index] > sequences[index - 1]
                for index in range(1, len(sequences))
            ),
            "strictly increasing request indices; gaps preserve failed attempts",
            sequences,
        )
    )
    checks.append(
        _check(
            "timestamp_order",
            all(
                timestamps[index] > timestamps[index - 1]
                for index in range(1, len(timestamps))
            ),
            "strictly increasing",
            timestamps,
        )
    )

    action_spec = capture.get("action_spec")
    if not isinstance(action_spec, dict):
        raise CaptureVerificationError("capture is missing action_spec")
    action_path = _inside(root, action_spec.get("path"), "action spec")
    action_exists = action_path.is_file()
    action_hash = _sha256_file(action_path) if action_exists else None
    action_bytes = action_path.stat().st_size if action_exists else None
    action_check = {
        "kind": "action_spec",
        "path": str(action_path),
        "exists": action_exists,
        "expected_sha256": action_spec.get("sha256"),
        "actual_sha256": action_hash,
        "expected_bytes": action_spec.get("bytes"),
        "actual_bytes": action_bytes,
        "valid": (
            action_exists
            and action_hash == action_spec.get("sha256")
            and action_bytes == action_spec.get("bytes")
        ),
    }
    checks.append(action_check)
    action_payload = _read_object(action_path, "action spec") if action_exists else {}
    action_rows = capture.get("actions")
    if not isinstance(action_rows, list):
        raise CaptureVerificationError("capture actions must be an array")
    expected_action_ids = [
        row.get("id") for row in action_payload.get("actions", [])
    ] if isinstance(action_payload.get("actions"), list) else []
    actual_action_ids = [row.get("id") for row in action_rows if isinstance(row, dict)]
    checks.append(
        _check(
            "action_case_id",
            action_payload.get("case_id") == case_id,
            case_id,
            action_payload.get("case_id"),
        )
    )
    checks.append(
        _check(
            "action_coverage",
            expected_action_ids == actual_action_ids,
            expected_action_ids,
            actual_action_ids,
        )
    )

    target_events = action_payload.get("target_events", [])
    if target_events:
        if not isinstance(target_events, list):
            raise CaptureVerificationError("action target_events must be an array")
        action_positions = {
            row.get("id"): index
            for index, row in enumerate(action_rows)
            if isinstance(row, dict)
        }
        duration_seconds = float(capture.get("capture_policy", {}).get("duration_seconds"))
        target_windows = []
        for target in target_events:
            if not isinstance(target, dict) or not isinstance(target.get("action_id"), str):
                raise CaptureVerificationError("target events must bind action ids")
            action_id = target["action_id"]
            position = action_positions.get(action_id)
            row = action_rows[position] if position is not None else None
            completed = row.get("completed_at_seconds") if isinstance(row, dict) else None
            next_started = (
                action_rows[position + 1].get("started_at_seconds")
                if position is not None and position + 1 < len(action_rows)
                else duration_seconds
            )
            evidence_frames = (
                [timestamp for timestamp in timestamps if completed <= timestamp < next_started]
                if isinstance(completed, (int, float))
                and isinstance(next_started, (int, float))
                and next_started > completed
                else []
            )
            target_windows.append(
                {
                    "action_id": action_id,
                    "completed_at_seconds": completed,
                    "window_end_seconds": next_started,
                    "evidence_frame_count": len(evidence_frames),
                    "first_evidence_frame_seconds": evidence_frames[0] if evidence_frames else None,
                    "valid": bool(evidence_frames),
                }
            )
        checks.append(
            _check(
                "target_event_frame_coverage",
                all(row["valid"] for row in target_windows),
                "at least one post-completion frame before the following action",
                target_windows,
            )
        )

    recomputed = capture_statistics(frames)
    reported = capture.get("frame_statistics")
    stats_match = isinstance(reported, dict) and _close_tree(recomputed, reported)
    checks.append(_check("frame_statistics", stats_match, recomputed, reported))
    policy = capture.get("capture_policy")
    if not isinstance(policy, dict):
        raise CaptureVerificationError("capture is missing capture_policy")
    minimum_fps = float(policy.get("minimum_average_fps"))
    maximum_gap = float(policy.get("maximum_gap_seconds"))
    required_failures = [
        row.get("id")
        for row in action_rows
        if isinstance(row, dict)
        and row.get("required") is True
        and row.get("status") != "completed"
    ]
    policy_reasons = []
    policy_warnings = []
    if capture.get("frame_errors"):
        policy_warnings.append(
            "one or more screenshot attempts failed but temporal bounds remain independently enforced"
        )
    if (recomputed["effective_average_fps"] or 0) < minimum_fps:
        policy_reasons.append("effective average frame rate is below the frozen minimum")
    if (recomputed["interval_seconds"]["maximum"] or math.inf) > maximum_gap:
        policy_reasons.append("maximum frame gap exceeds the frozen capture limit")
    if len(frames) < 2:
        policy_reasons.append("capture contains fewer than two frames")
    duration_seconds = policy.get("duration_seconds")
    first_timestamp = recomputed["timestamp_range_seconds"]["first"]
    last_timestamp = recomputed["timestamp_range_seconds"]["last"]
    if isinstance(duration_seconds, (int, float)) and first_timestamp is not None:
        if first_timestamp > maximum_gap:
            policy_reasons.append("capture starts after the frozen coverage limit")
        if float(duration_seconds) - last_timestamp > maximum_gap:
            policy_reasons.append("capture ends before the frozen coverage limit")
    if required_failures:
        policy_reasons.append("one or more required actions failed")
    reported_reasons = capture.get("invalid_reasons")
    checks.append(
        _check(
            "policy_assessment",
            policy_reasons == reported_reasons,
            policy_reasons,
            reported_reasons,
        )
    )
    integrity_valid = all(check["valid"] for check in checks)
    policy_valid = not policy_reasons
    return {
        "schema_version": 1,
        "capture": str(source),
        "case_id": case_id,
        "capture_reported_valid": capture.get("valid"),
        "integrity_valid": integrity_valid,
        "policy_valid": policy_valid,
        "valid": (
            integrity_valid
            and policy_valid
            and capture.get("valid") is True
        ),
        "recomputed_statistics": recomputed,
        "policy_reasons": policy_reasons,
        "policy_warnings": policy_warnings,
        "required_action_failures": required_failures,
        "checks": checks,
    }


def _check(kind: str, valid: bool, expected: Any, actual: Any) -> dict[str, Any]:
    return {
        "kind": kind,
        "expected": expected,
        "actual": actual,
        "valid": valid,
    }


def _inside(root: Path, relative: Any, kind: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise CaptureVerificationError(f"{kind} path must be a string")
    path = (root / relative).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise CaptureVerificationError(
            f"{kind} path must remain inside the capture directory"
        ) from error
    return path


def _positive_integer(value: Any, kind: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise CaptureVerificationError(f"{kind} must be a positive integer")
    return value


def _quantile(values: list[float], probability: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _close_tree(left: Any, right: Any) -> bool:
    if isinstance(left, dict) and isinstance(right, dict):
        return left.keys() == right.keys() and all(
            _close_tree(left[key], right[key]) for key in left
        )
    if isinstance(left, (int, float)) and not isinstance(left, bool):
        return (
            isinstance(right, (int, float))
            and not isinstance(right, bool)
            and math.isclose(float(left), float(right), rel_tol=1e-9, abs_tol=1e-9)
        )
    return left == right


def _read_object(path: Path, kind: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise CaptureVerificationError(f"{kind} file was not found: {path}") from error
    except json.JSONDecodeError as error:
        raise CaptureVerificationError(f"{kind} file is invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise CaptureVerificationError(f"{kind} file must contain an object")
    return payload


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    args = parse_args()
    report = verify_capture(args.capture, expected_case_id=args.case_id)
    if args.output:
        if args.output.exists():
            raise CaptureVerificationError("refusing to overwrite verification output")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "valid": report["valid"],
                "integrity_valid": report["integrity_valid"],
                "policy_valid": report["policy_valid"],
                "case_id": report["case_id"],
                "frames": report["recomputed_statistics"]["frame_count"],
            },
            sort_keys=True,
        )
    )
    if not report["valid"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
