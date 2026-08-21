from __future__ import annotations

import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .evaluation import (
    CLAIM180_TARGETS,
    EvaluationError,
    audit_manifest,
    load_manifest,
)
from .video import VideoError, probe_video


FREEZE_ROLES = frozenset({"development", "held_out"})
PREREGISTRATION_KIND = "signum_heldout_preregistration"


def preregister_heldout(
    plan_path: Path | str,
    output_path: Path | str,
) -> dict[str, Any]:
    """Hash-lock a collection plan before held-out recordings are created."""

    plan = _read_object(Path(plan_path).resolve(), "held-out plan")
    if plan.get("schema_version") != 1:
        raise EvaluationError("held-out plan must use schema_version 1")
    protocol_id = _required_nonempty(plan, "protocol_id", "held-out plan")
    protocol_repository = _required_nonempty(
        plan, "protocol_repository", "held-out plan"
    )
    protocol_revision = _required_nonempty(
        plan, "protocol_revision", "held-out plan"
    )
    if not protocol_repository.startswith("https://"):
        raise EvaluationError("held-out plan protocol_repository must use https")
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", protocol_revision):
        raise EvaluationError(
            "held-out plan protocol_revision must be a full immutable commit hash"
        )
    case_ids = plan.get("case_ids")
    if (
        not isinstance(case_ids, list)
        or len(case_ids) < 30
        or any(not isinstance(value, str) or not value for value in case_ids)
        or len(case_ids) != len(set(case_ids))
    ):
        raise EvaluationError(
            "held-out plan case_ids must contain at least 30 unique non-empty strings"
        )
    category_targets = plan.get("category_targets")
    if category_targets != CLAIM180_TARGETS:
        raise EvaluationError(
            "held-out plan category_targets must exactly match CLAIM180_TARGETS"
        )
    workflow_sources = plan.get("workflow_sources")
    if not isinstance(workflow_sources, list) or len(workflow_sources) != len(
        case_ids
    ):
        raise EvaluationError(
            "held-out plan workflow_sources must contain one entry per case id"
        )
    source_case_ids = []
    for source in workflow_sources:
        if not isinstance(source, dict):
            raise EvaluationError("held-out workflow sources must be objects")
        source_case_ids.append(
            _required_nonempty(source, "case_id", "held-out workflow source")
        )
        url = _required_nonempty(source, "url", "held-out workflow source")
        _required_nonempty(source, "goal", "held-out workflow source")
        if not url.startswith("https://"):
            raise EvaluationError("held-out workflow source URLs must use https")
    if source_case_ids != case_ids:
        raise EvaluationError(
            "held-out workflow source case ids and order must match case_ids"
        )
    evidence_policy = plan.get("evidence_policy")
    observation_budget = plan.get("observation_budget")
    if not isinstance(evidence_policy, dict) or not evidence_policy:
        raise EvaluationError(
            "held-out plan evidence_policy must be a non-empty object"
        )
    if not isinstance(observation_budget, dict) or not observation_budget:
        raise EvaluationError(
            "held-out plan observation_budget must be a non-empty object"
        )

    source = Path(plan_path).resolve()
    actions_manifest = _validate_actions_manifest(
        source,
        plan.get("actions_manifest"),
        case_ids,
    )

    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": PREREGISTRATION_KIND,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "plan": _relative_to_lock(source, destination),
        "plan_bytes": source.stat().st_size,
        "plan_sha256": _sha256_file(source),
        "protocol_id": protocol_id,
        "protocol_repository": protocol_repository,
        "protocol_revision": protocol_revision,
        "case_ids": case_ids,
        "category_targets": category_targets,
        "evidence_policy": evidence_policy,
        "observation_budget": observation_budget,
        "workflow_sources": workflow_sources,
    }
    if actions_manifest is not None:
        payload["actions_manifest"] = {
            "path": _relative_to_lock(actions_manifest["path"], destination),
            "bytes": actions_manifest["bytes"],
            "sha256": actions_manifest["sha256"],
            "collector_revision": actions_manifest["collector_revision"],
            "case_count": actions_manifest["case_count"],
        }
    payload["preregistration_id"] = _fingerprint(
        {key: value for key, value in payload.items() if key != "created_at_utc"}
    )
    destination.write_text(_json_text(payload), encoding="utf-8")
    return payload


def freeze_manifest(
    manifest_path: Path | str,
    output_path: Path | str,
    *,
    role: str,
    preregistration_path: Path | str | None = None,
) -> dict[str, Any]:
    if role not in FREEZE_ROLES:
        raise EvaluationError(f"freeze role must be one of {sorted(FREEZE_ROLES)}")
    if role == "held_out" and preregistration_path is None:
        raise EvaluationError("held_out freezes require a preregistration lock")
    if role == "development" and preregistration_path is not None:
        raise EvaluationError(
            "development freezes cannot use a held-out preregistration"
        )
    manifest = load_manifest(manifest_path)
    destination = Path(output_path).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    preregistration = None
    preregistration_source = None
    if preregistration_path is not None:
        preregistration_source = Path(preregistration_path).resolve()
        preregistration = _verify_preregistration(preregistration_source)
        manifest_case_ids = [case.id for case in manifest.cases]
        if manifest_case_ids != preregistration["case_ids"]:
            raise EvaluationError(
                "held-out manifest case ids or order differ from the preregistered plan"
            )
        preregistration_mtime = preregistration_source.stat().st_mtime_ns
        if preregistration_mtime > manifest.path.stat().st_mtime_ns:
            raise EvaluationError(
                "held-out manifest predates its preregistration lock"
            )
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
        if (
            preregistration_source is not None
            and preregistration_source.stat().st_mtime_ns
            > case.video.stat().st_mtime_ns
        ):
            raise EvaluationError(
                f"held-out video for case {case.id!r} predates its preregistration lock"
            )
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
    profile = "claim180" if role == "held_out" else "pilot60"
    audit = audit_manifest(manifest.path, profile=profile)
    if role == "held_out" and not audit["profile_complete"]:
        raise EvaluationError("held-out manifest does not satisfy the claim180 profile")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "role": role,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "manifest": _relative_to_lock(manifest.path, destination),
        "manifest_bytes": manifest.path.stat().st_size,
        "manifest_sha256": _sha256_file(manifest.path),
        "audit": audit,
        "cases": cases,
    }
    if preregistration is not None and preregistration_source is not None:
        payload["preregistration"] = {
            "path": _relative_to_lock(preregistration_source, destination),
            "bytes": preregistration_source.stat().st_size,
            "sha256": _sha256_file(preregistration_source),
            "preregistration_id": preregistration["preregistration_id"],
            "protocol_id": preregistration["protocol_id"],
            "protocol_repository": preregistration["protocol_repository"],
            "protocol_revision": preregistration["protocol_revision"],
        }
        if isinstance(preregistration.get("actions_manifest"), dict):
            payload["preregistration"]["actions_manifest"] = preregistration[
                "actions_manifest"
            ]
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
    if lock["role"] == "held_out":
        raw_preregistration = lock.get("preregistration")
        if not isinstance(raw_preregistration, dict):
            raise EvaluationError(
                "held_out freeze is missing its preregistration; create a new freeze"
            )
        preregistration_path = (
            path.parent / _required_string(raw_preregistration, "path")
        ).resolve()
        preregistration_check = _file_check(
            "preregistration",
            preregistration_path,
            _required_string(raw_preregistration, "sha256"),
            _required_integer(raw_preregistration, "bytes"),
        )
        checks.append(preregistration_check)
        if preregistration_check["valid"]:
            preregistration = _verify_preregistration(preregistration_path)
            if preregistration["preregistration_id"] != raw_preregistration.get(
                "preregistration_id"
            ):
                raise EvaluationError("held-out preregistration id does not match")
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


def _verify_preregistration(path: Path) -> dict[str, Any]:
    lock = _read_object(path, "held-out preregistration")
    if lock.get("schema_version") != 1 or lock.get("kind") != PREREGISTRATION_KIND:
        raise EvaluationError("invalid held-out preregistration lock")
    plan_path = (path.parent / _required_string(lock, "plan")).resolve()
    check = _file_check(
        "preregistration-plan",
        plan_path,
        _required_string(lock, "plan_sha256"),
        _required_integer(lock, "plan_bytes"),
    )
    if not check["valid"]:
        raise EvaluationError("held-out preregistration plan integrity check failed")
    plan = _read_object(plan_path, "held-out preregistration plan")
    actions_manifest = _validate_actions_manifest(
        plan_path,
        plan.get("actions_manifest"),
        lock.get("case_ids"),
    )
    locked_actions = lock.get("actions_manifest")
    if actions_manifest is None:
        if locked_actions is not None:
            raise EvaluationError(
                "held-out preregistration has an unexpected actions manifest"
            )
    elif not isinstance(locked_actions, dict) or any(
        locked_actions.get(key) != value
        for key, value in {
            "bytes": actions_manifest["bytes"],
            "sha256": actions_manifest["sha256"],
            "collector_revision": actions_manifest["collector_revision"],
            "case_count": actions_manifest["case_count"],
        }.items()
    ):
        raise EvaluationError("held-out actions manifest lock does not match")
    expected_id = _fingerprint(
        {
            key: value
            for key, value in lock.items()
            if key not in {"created_at_utc", "preregistration_id"}
        }
    )
    if lock.get("preregistration_id") != expected_id:
        raise EvaluationError("held-out preregistration fingerprint is invalid")
    case_ids = lock.get("case_ids")
    if not isinstance(case_ids, list) or any(
        not isinstance(value, str) for value in case_ids
    ):
        raise EvaluationError("held-out preregistration has invalid case_ids")
    return lock


def _validate_actions_manifest(
    plan_path: Path,
    raw_reference: object,
    case_ids: object,
) -> dict[str, Any] | None:
    if raw_reference is None:
        return None
    if not isinstance(raw_reference, dict):
        raise EvaluationError("held-out plan actions_manifest must be an object")
    if not isinstance(case_ids, list) or any(
        not isinstance(value, str) for value in case_ids
    ):
        raise EvaluationError("held-out plan has invalid case_ids")
    relative_path = _required_string(raw_reference, "path")
    manifest_path = (plan_path.parent / relative_path).resolve()
    expected_hash = _required_string(raw_reference, "sha256")
    expected_bytes = _required_integer(raw_reference, "bytes")
    check = _file_check(
        "held-out-actions-manifest",
        manifest_path,
        expected_hash,
        expected_bytes,
    )
    if not check["valid"]:
        raise EvaluationError("held-out actions manifest integrity check failed")
    manifest = _read_object(manifest_path, "held-out actions manifest")
    if (
        manifest.get("schema_version") != 1
        or manifest.get("kind") != "signum_claim180_browser_actions"
    ):
        raise EvaluationError("invalid held-out actions manifest")
    collector_revision = _required_nonempty(
        manifest,
        "collector_revision",
        "held-out actions manifest",
    )
    if not re.fullmatch(r"[0-9a-fA-F]{40,64}", collector_revision):
        raise EvaluationError(
            "held-out actions manifest collector_revision must be immutable"
        )
    rows = manifest.get("cases")
    if not isinstance(rows, list) or len(rows) != len(case_ids):
        raise EvaluationError(
            "held-out actions manifest must contain one row per case id"
        )
    manifest_case_ids = []
    for row in rows:
        if not isinstance(row, dict):
            raise EvaluationError("held-out action manifest rows must be objects")
        case_id = _required_string(row, "case_id")
        manifest_case_ids.append(case_id)
        action_path = (
            manifest_path.parent / _required_string(row, "action_file")
        ).resolve()
        action_check = _file_check(
            f"held-out-actions:{case_id}",
            action_path,
            _required_string(row, "sha256"),
            _required_integer(row, "bytes"),
        )
        if not action_check["valid"]:
            raise EvaluationError(
                f"held-out action file integrity check failed for {case_id!r}"
            )
        action = _read_object(action_path, f"held-out action file {case_id!r}")
        if action.get("schema_version") != 1 or action.get("case_id") != case_id:
            raise EvaluationError(f"invalid held-out action file for {case_id!r}")
    if manifest_case_ids != case_ids:
        raise EvaluationError(
            "held-out actions manifest case ids and order must match the plan"
        )
    return {
        "path": manifest_path,
        "bytes": expected_bytes,
        "sha256": expected_hash,
        "collector_revision": collector_revision,
        "case_count": len(rows),
    }


def _file_check(
    kind: str,
    path: Path,
    expected_hash: str,
    expected_bytes: int,
) -> dict[str, Any]:
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


def _required_nonempty(payload: dict[str, Any], key: str, kind: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(f"{kind} field {key!r} must be a non-empty string")
    return value


def _read_object(path: Path, kind: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EvaluationError(f"{kind} file was not found: {path}") from error
    except json.JSONDecodeError as error:
        raise EvaluationError(f"{kind} file is invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise EvaluationError(f"{kind} file must contain a JSON object")
    return payload


def _json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
