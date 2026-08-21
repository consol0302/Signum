from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .evaluation import EvaluationError, audit_manifest, load_manifest
from .video import VideoError, probe_video


FREEZE_ROLES = frozenset({"development", "held_out"})


def freeze_manifest(
    manifest_path: Path | str,
    output_path: Path | str,
    *,
    role: str,
) -> dict[str, Any]:
    if role not in FREEZE_ROLES:
        raise EvaluationError(f"freeze role must be one of {sorted(FREEZE_ROLES)}")
    manifest = load_manifest(manifest_path)
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    cases = []
    for case in manifest.cases:
        if not case.video.is_file():
            raise EvaluationError(f"case {case.id!r} video was not found: {case.video}")
        try:
            metadata = probe_video(case.video)
        except VideoError as error:
            raise EvaluationError(
                f"case {case.id!r} video could not be probed: {error}"
            ) from error
        cases.append(
            {
                "case_id": case.id,
                "video": _relative_to_lock(case.video, destination),
                "video_bytes": case.video.stat().st_size,
                "video_sha256": _sha256_file(case.video),
                "video_metadata": {
                    "width": metadata.width,
                    "height": metadata.height,
                    "fps": metadata.fps,
                    "frame_count": metadata.frame_count,
                    "duration_seconds": metadata.duration_seconds,
                },
                "event_ids": [event.id for event in case.events],
                "events": [
                    {
                        "event_id": event.id,
                        "category": event.category,
                        "real_world_eligible": event.real_world_eligible,
                        "source_transition_id": (
                            event.source_transition_id or f"{case.id}/{event.id}"
                        ),
                    }
                    for event in case.events
                ],
                "source_transition_ids": [
                    event.source_transition_id or f"{case.id}/{event.id}"
                    for event in case.events
                ],
            }
        )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "role": role,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "manifest": _relative_to_lock(manifest.path, destination),
        "manifest_bytes": manifest.path.stat().st_size,
        "manifest_sha256": _sha256_file(manifest.path),
        "audit": audit_manifest(manifest.path),
        "cases": cases,
    }
    payload["freeze_id"] = _fingerprint(
        {key: value for key, value in payload.items() if key != "created_at_utc"}
    )
    destination.write_text(_json_text(payload), encoding="utf-8")
    return payload


def verify_freeze(lock_path: Path | str) -> dict[str, Any]:
    path = Path(lock_path).resolve()
    try:
        lock = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EvaluationError(f"freeze file was not found: {path}") from error
    except json.JSONDecodeError as error:
        raise EvaluationError(f"freeze file is invalid JSON: {error}") from error
    if not isinstance(lock, dict) or lock.get("schema_version") != 1:
        raise EvaluationError("freeze file must use schema_version 1")
    if lock.get("role") not in FREEZE_ROLES:
        raise EvaluationError("freeze file has an invalid role")

    checks = []
    manifest_path = (path.parent / _required_string(lock, "manifest")).resolve()
    checks.append(
        _file_check(
            "manifest",
            manifest_path,
            _required_string(lock, "manifest_sha256"),
            _required_integer(lock, "manifest_bytes"),
        )
    )
    raw_cases = lock.get("cases")
    if not isinstance(raw_cases, list):
        raise EvaluationError("freeze file must contain a cases array")
    for raw in raw_cases:
        if not isinstance(raw, dict):
            raise EvaluationError("freeze cases must be objects")
        case_id = _required_string(raw, "case_id")
        video_path = (path.parent / _required_string(raw, "video")).resolve()
        checks.append(
            _file_check(
                f"video:{case_id}",
                video_path,
                _required_string(raw, "video_sha256"),
                _required_integer(raw, "video_bytes"),
            )
        )
    return {
        "schema_version": 1,
        "freeze": str(path),
        "freeze_id": lock.get("freeze_id"),
        "role": lock["role"],
        "valid": all(check["valid"] for check in checks),
        "checks": checks,
    }


def _file_check(kind: str, path: Path, expected_hash: str, expected_bytes: int) -> dict[str, Any]:
    exists = path.is_file()
    actual_bytes = path.stat().st_size if exists else None
    actual_hash = _sha256_file(path) if exists else None
    return {
        "kind": kind,
        "path": str(path),
        "exists": exists,
        "expected_bytes": expected_bytes,
        "actual_bytes": actual_bytes,
        "expected_sha256": expected_hash,
        "actual_sha256": actual_hash,
        "valid": (
            exists
            and actual_bytes == expected_bytes
            and actual_hash == expected_hash
        ),
    }


def _relative_to_lock(target: Path, lock_path: Path) -> str:
    return Path(os.path.relpath(target.resolve(), lock_path.parent)).as_posix()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(payload: object) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise EvaluationError(f"freeze field {key!r} must be a non-empty string")
    return value


def _required_integer(payload: dict[str, Any], key: str) -> int:
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise EvaluationError(f"freeze field {key!r} must be a non-negative integer")
    return value


def _json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
