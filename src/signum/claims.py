from __future__ import annotations

import hashlib
import json
import math
import random
from collections import defaultdict
from pathlib import Path
from statistics import median
from typing import Any

from .evaluation import EvaluationError
from .freeze import verify_freeze


DEFAULT_REQUIREMENTS = {
    "min_events": 180,
    "min_workflows": 30,
    "min_action_failures": 20,
    "min_reviewers": 2,
    "min_cost_runs": 3,
    "accuracy_noninferiority_margin": 0.03,
    "false_confirmation_noninferiority_margin": 0.01,
    "min_cost_reduction": 0.30,
    "bootstrap_samples": 20_000,
    "bootstrap_seed": 20260821,
}
ACCEPTED_COST_BASES = frozenset({"provider_invoice", "published_api_price"})


def assess_claim(comparison_path: Path | str) -> dict[str, Any]:
    path = Path(comparison_path).resolve()
    comparison = _read_object(path, "comparison")
    if comparison.get("schema_version") != 1:
        raise EvaluationError("comparison schema_version must be 1")
    requirements = _requirements(comparison.get("requirements"))
    freeze_path = (path.parent / _required_string(comparison, "freeze")).resolve()
    freeze = verify_freeze(freeze_path)
    freeze_lock = _read_object(freeze_path, "freeze")
    frozen_events, frozen_stats = _frozen_event_contract(freeze_lock)
    freeze_id = comparison.get("freeze_id")
    freeze_identity_matches = freeze_id == freeze.get("freeze_id")
    review = _review_contract(comparison.get("review"), path.parent)
    systems = _systems(comparison.get("systems"), path.parent)
    _validate_systems_against_freeze(systems, frozen_events)
    candidates = [row for row in systems if row["kind"] == "candidate"]
    baselines = [row for row in systems if row["kind"] == "baseline"]
    if len(candidates) != 1:
        raise EvaluationError("comparison must contain exactly one candidate system")
    if not baselines:
        raise EvaluationError("comparison must contain at least one baseline system")
    candidate = candidates[0]
    comparisons = [
        _compare_systems(candidate, baseline, requirements)
        for baseline in baselines
    ]
    global_reasons = []
    if not freeze["valid"]:
        global_reasons.append("frozen manifest or video integrity check failed")
    if freeze["role"] != "held_out":
        global_reasons.append("freeze role is not held_out")
    if freeze_lock.get("audit", {}).get("profile") != "claim180":
        global_reasons.append("frozen manifest was not audited with claim180")
    if not isinstance(freeze_lock.get("preregistration"), dict):
        global_reasons.append("held-out collection was not preregistered")
    if not freeze_lock.get("audit", {}).get("profile_complete", False):
        global_reasons.append("frozen manifest does not pass its profile audit")
    if frozen_stats["unique_video_count"] < requirements["min_workflows"]:
        global_reasons.append("too few distinct frozen workflow recordings")
    if frozen_stats["duplicate_transition_count"]:
        global_reasons.append("eligible frozen events reuse source transitions")
    if not freeze_identity_matches:
        global_reasons.append("comparison freeze_id does not match the freeze file")
    if review["method"] != "human_blind":
        global_reasons.append("review method is not human_blind")
    if len(review["reviewers"]) < requirements["min_reviewers"]:
        global_reasons.append("too few independent reviewers")
    if not review["adjudicated"]:
        global_reasons.append("review disagreements are not adjudicated")
    if not review["artifact_integrity_valid"]:
        global_reasons.append("review or adjudication artifact integrity failed")
    if any(not system["artifact_integrity_valid"] for system in systems):
        global_reasons.append("one or more system run artifacts failed integrity checks")
    claimable_baselines = [
        row["baseline"]
        for row in comparisons
        if row["claim_supported"] and not global_reasons
    ]
    return {
        "schema_version": 1,
        "comparison": str(path),
        "freeze": freeze,
        "freeze_identity_matches": freeze_identity_matches,
        "frozen_evidence": frozen_stats,
        "requirements": requirements,
        "review": review,
        "system_artifacts": {
            system["id"]: {
                "valid": system["artifact_integrity_valid"],
                "artifacts": system["run_artifacts"],
            }
            for system in systems
        },
        "candidate": candidate["id"],
        "comparisons": comparisons,
        "global_reasons": global_reasons,
        "claim_supported": bool(claimable_baselines),
        "claimable_baselines": claimable_baselines,
        "claim_text": (
            _claim_text(candidate["id"], claimable_baselines)
            if claimable_baselines
            else None
        ),
    }


def _compare_systems(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    requirements: dict[str, Any],
) -> dict[str, Any]:
    candidate_events = {row["event_id"]: row for row in candidate["events"]}
    baseline_events = {row["event_id"]: row for row in baseline["events"]}
    if candidate_events.keys() != baseline_events.keys():
        raise EvaluationError(
            f"candidate and baseline {baseline['id']!r} must contain identical event ids"
        )
    paired = []
    for event_id in sorted(candidate_events):
        left = candidate_events[event_id]
        right = baseline_events[event_id]
        for field in ("workflow_id", "category"):
            if left[field] != right[field]:
                raise EvaluationError(
                    f"event {event_id!r} has mismatched {field} across systems"
                )
        paired.append((left, right))
    workflows = {left["workflow_id"] for left, _ in paired}
    failures = [pair for pair in paired if pair[0]["category"] == "action_failure"]
    accuracy_differences = _cluster_bootstrap_difference(
        paired,
        value=lambda pair: float(pair[0]["success"]) - float(pair[1]["success"]),
        samples=requirements["bootstrap_samples"],
        seed=requirements["bootstrap_seed"],
    )
    false_confirmation_differences = _cluster_bootstrap_difference(
        failures,
        value=lambda pair: float(pair[0]["false_confirmation"])
        - float(pair[1]["false_confirmation"]),
        samples=requirements["bootstrap_samples"],
        seed=requirements["bootstrap_seed"] + 1,
    )
    accuracy_interval = _percentile_interval(accuracy_differences)
    false_confirmation_interval = _percentile_interval(
        false_confirmation_differences
    )
    candidate_accuracy = _mean(float(left["success"]) for left, _ in paired)
    baseline_accuracy = _mean(float(right["success"]) for _, right in paired)
    candidate_false_confirmation = _mean(
        float(left["false_confirmation"]) for left, _ in failures
    )
    baseline_false_confirmation = _mean(
        float(right["false_confirmation"]) for _, right in failures
    )
    cost = _cost_comparison(candidate, baseline, requirements)
    sample_reasons = []
    if len(paired) < requirements["min_events"]:
        sample_reasons.append("too few paired events")
    if len(workflows) < requirements["min_workflows"]:
        sample_reasons.append("too few independent workflows")
    if len(failures) < requirements["min_action_failures"]:
        sample_reasons.append("too few failed-action events")
    false_confirmation_noninferior = (
        false_confirmation_interval[1]
        <= requirements["false_confirmation_noninferiority_margin"]
    )
    accuracy_superior = accuracy_interval[0] > 0.0
    accuracy_noninferior = (
        accuracy_interval[0]
        >= -requirements["accuracy_noninferiority_margin"]
    )
    superiority_claim = accuracy_superior and false_confirmation_noninferior
    cost_claim = (
        accuracy_noninferior
        and false_confirmation_noninferior
        and cost["material_reduction"]
    )
    reasons = list(sample_reasons)
    if not superiority_claim:
        reasons.append("accuracy superiority was not established")
    if not cost_claim:
        reasons.append("cost advantage at non-inferior accuracy was not established")
    return {
        "baseline": baseline["id"],
        "events": len(paired),
        "workflows": len(workflows),
        "action_failures": len(failures),
        "candidate_accuracy": candidate_accuracy,
        "baseline_accuracy": baseline_accuracy,
        "accuracy_difference": candidate_accuracy - baseline_accuracy,
        "accuracy_difference_ci95_cluster_bootstrap": accuracy_interval,
        "candidate_false_confirmation_rate": candidate_false_confirmation,
        "baseline_false_confirmation_rate": baseline_false_confirmation,
        "false_confirmation_difference_ci95_cluster_bootstrap": (
            false_confirmation_interval
        ),
        "accuracy_superiority": accuracy_superior,
        "accuracy_noninferiority": accuracy_noninferior,
        "false_confirmation_noninferiority": false_confirmation_noninferior,
        "cost": cost,
        "superiority_claim_supported": superiority_claim and not sample_reasons,
        "cost_claim_supported": cost_claim and not sample_reasons,
        "claim_supported": (
            (superiority_claim or cost_claim) and not sample_reasons
        ),
        "reasons": reasons,
    }


def _cost_comparison(
    candidate: dict[str, Any],
    baseline: dict[str, Any],
    requirements: dict[str, Any],
) -> dict[str, Any]:
    candidate_runs = candidate["billed_cost_usd_runs"]
    baseline_runs = baseline["billed_cost_usd_runs"]
    accepted_basis = (
        candidate["cost_basis"] in ACCEPTED_COST_BASES
        and baseline["cost_basis"] in ACCEPTED_COST_BASES
    )
    enough_runs = (
        len(candidate_runs) >= requirements["min_cost_runs"]
        and len(baseline_runs) >= requirements["min_cost_runs"]
        and len(candidate["run_artifacts"]) >= requirements["min_cost_runs"]
        and len(baseline["run_artifacts"]) >= requirements["min_cost_runs"]
    )
    paired_count = min(len(candidate_runs), len(baseline_runs))
    ratios = [
        candidate_runs[index] / baseline_runs[index]
        for index in range(paired_count)
        if baseline_runs[index] > 0
    ]
    threshold = 1.0 - requirements["min_cost_reduction"]
    material = (
        accepted_basis
        and enough_runs
        and len(ratios) >= requirements["min_cost_runs"]
        and max(ratios) <= threshold
    )
    return {
        "candidate_basis": candidate["cost_basis"],
        "baseline_basis": baseline["cost_basis"],
        "candidate_runs_usd": candidate_runs,
        "baseline_runs_usd": baseline_runs,
        "paired_cost_ratios": ratios,
        "median_cost_ratio": median(ratios) if ratios else None,
        "required_max_ratio": threshold,
        "accepted_basis": accepted_basis,
        "enough_runs": enough_runs,
        "material_reduction": material,
    }


def _cluster_bootstrap_difference(
    pairs: list[tuple[dict[str, Any], dict[str, Any]]],
    *,
    value: Any,
    samples: int,
    seed: int,
) -> list[float]:
    if not pairs:
        return [0.0]
    grouped: defaultdict[str, list[tuple[dict[str, Any], dict[str, Any]]]] = defaultdict(list)
    for pair in pairs:
        grouped[pair[0]["workflow_id"]].append(pair)
    workflow_ids = sorted(grouped)
    generator = random.Random(seed)
    results = []
    for _ in range(samples):
        selected = [generator.choice(workflow_ids) for _ in workflow_ids]
        values = [value(pair) for workflow in selected for pair in grouped[workflow]]
        results.append(_mean(values))
    return results


def _percentile_interval(values: list[float]) -> list[float]:
    ordered = sorted(values)
    return [
        _quantile(ordered, 0.025),
        _quantile(ordered, 0.975),
    ]


def _quantile(ordered: list[float], probability: float) -> float:
    if not ordered:
        return math.nan
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _systems(raw: object, root: Path) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        raise EvaluationError("comparison systems must be an array")
    systems = []
    ids = set()
    for item in raw:
        if not isinstance(item, dict):
            raise EvaluationError("comparison systems must be objects")
        system_id = _required_string(item, "id")
        if system_id in ids:
            raise EvaluationError(f"duplicate system id {system_id!r}")
        ids.add(system_id)
        kind = _required_string(item, "kind")
        if kind not in {"candidate", "baseline"}:
            raise EvaluationError("system kind must be candidate or baseline")
        raw_events = item.get("events")
        if not isinstance(raw_events, list) or not raw_events:
            raise EvaluationError(f"system {system_id!r} must contain events")
        events = [_event(row, system_id) for row in raw_events]
        event_ids = [row["event_id"] for row in events]
        if len(event_ids) != len(set(event_ids)):
            raise EvaluationError(f"system {system_id!r} has duplicate event ids")
        costs = item.get("billed_cost_usd_runs", [])
        if not isinstance(costs, list) or any(
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
            or value < 0
            for value in costs
        ):
            raise EvaluationError("billed_cost_usd_runs must contain non-negative numbers")
        raw_artifacts = item.get("run_artifacts")
        if not isinstance(raw_artifacts, list) or not raw_artifacts:
            raise EvaluationError(
                f"system {system_id!r} must contain at least one run artifact"
            )
        run_artifacts = [
            _artifact_contract(value, root, f"system {system_id!r} run")
            for value in raw_artifacts
        ]
        artifact_paths = [artifact["resolved_path"] for artifact in run_artifacts]
        if len(artifact_paths) != len(set(artifact_paths)):
            raise EvaluationError(
                f"system {system_id!r} run artifacts must be distinct files"
            )
        systems.append(
            {
                "id": system_id,
                "kind": kind,
                "provider": _required_string(item, "provider"),
                "model": _required_string(item, "model"),
                "cost_basis": _required_string(item, "cost_basis"),
                "cost_evidence": _required_string(item, "cost_evidence"),
                "billed_cost_usd_runs": [float(value) for value in costs],
                "run_artifacts": run_artifacts,
                "artifact_integrity_valid": all(
                    artifact["valid"] for artifact in run_artifacts
                ),
                "events": events,
            }
        )
    return systems


def _frozen_event_contract(
    lock: dict[str, Any],
) -> tuple[dict[str, dict[str, str]], dict[str, int]]:
    raw_cases = lock.get("cases")
    if not isinstance(raw_cases, list):
        raise EvaluationError("freeze file must contain a cases array")
    result = {}
    video_hashes = set()
    transition_counts: defaultdict[str, int] = defaultdict(int)
    for case in raw_cases:
        if not isinstance(case, dict):
            raise EvaluationError("freeze cases must be objects")
        case_id = _required_string(case, "case_id")
        video_hash = _required_string(case, "video_sha256")
        raw_events = case.get("events")
        if not isinstance(raw_events, list):
            raise EvaluationError(
                "freeze file is missing event provenance; create a new freeze"
            )
        for event in raw_events:
            if not isinstance(event, dict):
                raise EvaluationError("freeze events must be objects")
            if event.get("real_world_eligible") is not True:
                continue
            video_hashes.add(video_hash)
            event_id = _required_string(event, "event_id")
            transition_id = _required_string(event, "source_transition_id")
            transition_counts[transition_id] += 1
            key = f"{case_id}/{event_id}"
            if key in result:
                raise EvaluationError(f"duplicate frozen event id {key!r}")
            result[key] = {
                "workflow_id": case_id,
                "category": _required_string(event, "category"),
            }
    return result, {
        "eligible_event_count": len(result),
        "unique_video_count": len(video_hashes),
        "unique_transition_count": len(transition_counts),
        "duplicate_transition_count": sum(
            1 for count in transition_counts.values() if count > 1
        ),
    }


def _validate_systems_against_freeze(
    systems: list[dict[str, Any]],
    frozen_events: dict[str, dict[str, str]],
) -> None:
    expected = set(frozen_events)
    for system in systems:
        actual = {event["event_id"] for event in system["events"]}
        if actual != expected:
            missing = sorted(expected - actual)[:10]
            extra = sorted(actual - expected)[:10]
            raise EvaluationError(
                f"system {system['id']!r} does not cover the eligible frozen events; "
                f"missing={missing}, extra={extra}"
            )
        for event in system["events"]:
            frozen = frozen_events[event["event_id"]]
            for field in ("workflow_id", "category"):
                if event[field] != frozen[field]:
                    raise EvaluationError(
                        f"system {system['id']!r} event {event['event_id']!r} "
                        f"does not match frozen {field}"
                    )


def _event(raw: object, system_id: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise EvaluationError(f"system {system_id!r} events must be objects")
    category = _required_string(raw, "category")
    success = raw.get("success")
    if not isinstance(success, bool):
        raise EvaluationError("event success must be boolean")
    false_confirmation = raw.get("false_confirmation")
    if category == "action_failure" and not isinstance(false_confirmation, bool):
        raise EvaluationError("failed actions require a boolean false_confirmation")
    if category != "action_failure":
        false_confirmation = False
    return {
        "event_id": _required_string(raw, "event_id"),
        "workflow_id": _required_string(raw, "workflow_id"),
        "category": category,
        "success": success,
        "false_confirmation": false_confirmation,
    }


def _review_contract(raw: object, root: Path) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise EvaluationError("comparison review must be an object")
    reviewers = raw.get("reviewers")
    if not isinstance(reviewers, list) or any(
        not isinstance(value, str) or not value.strip() for value in reviewers
    ):
        raise EvaluationError("reviewers must be non-empty strings")
    if len(reviewers) != len(set(reviewers)):
        raise EvaluationError("reviewers must be distinct")
    adjudicated = raw.get("adjudicated")
    if not isinstance(adjudicated, bool):
        raise EvaluationError("review adjudicated must be boolean")
    raw_artifacts = raw.get("artifacts")
    if not isinstance(raw_artifacts, list) or len(raw_artifacts) != len(reviewers):
        raise EvaluationError("review must contain one artifact per reviewer")
    artifacts = [
        _artifact_contract(value, root, "review") for value in raw_artifacts
    ]
    if len({artifact["resolved_path"] for artifact in artifacts}) != len(artifacts):
        raise EvaluationError("review artifacts must be distinct files")
    artifact_reviewers = [artifact.get("reviewer") for artifact in artifacts]
    if artifact_reviewers != reviewers:
        raise EvaluationError(
            "review artifact reviewer order must match the reviewers array"
        )
    adjudication_artifact = _artifact_contract(
        raw.get("adjudication_artifact"), root, "adjudication"
    )
    return {
        "method": _required_string(raw, "method"),
        "reviewers": reviewers,
        "adjudicated": adjudicated,
        "artifacts": artifacts,
        "adjudication_artifact": adjudication_artifact,
        "artifact_integrity_valid": (
            all(artifact["valid"] for artifact in artifacts)
            and adjudication_artifact["valid"]
        ),
    }


def _artifact_contract(raw: object, root: Path, kind: str) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise EvaluationError(f"{kind} artifact must be an object")
    relative = _required_string(raw, "path")
    expected_sha256 = _required_string(raw, "sha256").lower()
    expected_bytes = raw.get("bytes")
    if (
        len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise EvaluationError(f"{kind} artifact sha256 must be 64 hex characters")
    if (
        not isinstance(expected_bytes, int)
        or isinstance(expected_bytes, bool)
        or expected_bytes < 0
    ):
        raise EvaluationError(f"{kind} artifact bytes must be a non-negative integer")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as error:
        raise EvaluationError(
            f"{kind} artifact must remain inside the comparison directory"
        ) from error
    exists = path.is_file()
    actual_bytes = path.stat().st_size if exists else None
    actual_sha256 = _sha256_file(path) if exists else None
    result = {
        "path": relative,
        "resolved_path": str(path),
        "expected_sha256": expected_sha256,
        "actual_sha256": actual_sha256,
        "expected_bytes": expected_bytes,
        "actual_bytes": actual_bytes,
        "exists": exists,
        "valid": (
            exists
            and actual_bytes == expected_bytes
            and actual_sha256 == expected_sha256
        ),
    }
    reviewer = raw.get("reviewer")
    if reviewer is not None:
        if not isinstance(reviewer, str) or not reviewer.strip():
            raise EvaluationError(f"{kind} artifact reviewer must be a string")
        result["reviewer"] = reviewer
    return result


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _requirements(raw: object) -> dict[str, Any]:
    result = dict(DEFAULT_REQUIREMENTS)
    if raw is None:
        return result
    if not isinstance(raw, dict):
        raise EvaluationError("comparison requirements must be an object")
    unknown = set(raw) - set(result)
    if unknown:
        raise EvaluationError(f"unknown comparison requirements: {sorted(unknown)}")
    result.update(raw)
    for key in (
        "min_events",
        "min_workflows",
        "min_action_failures",
        "min_reviewers",
        "min_cost_runs",
        "bootstrap_samples",
        "bootstrap_seed",
    ):
        value = result[key]
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise EvaluationError(f"requirement {key!r} must be a positive integer")
    for key in (
        "accuracy_noninferiority_margin",
        "false_confirmation_noninferiority_margin",
        "min_cost_reduction",
    ):
        value = result[key]
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not 0 <= value < 1
        ):
            raise EvaluationError(f"requirement {key!r} must be in [0, 1)")
        result[key] = float(value)
    return result


def _claim_text(candidate: str, baselines: list[str]) -> str:
    joined = ", ".join(baselines)
    return (
        f"{candidate} satisfied the frozen claim protocol against {joined}; "
        "see the paired accuracy, false-confirmation, cost, and review evidence."
    )


def _read_object(path: Path, kind: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EvaluationError(f"{kind} file was not found: {path}") from error
    except json.JSONDecodeError as error:
        raise EvaluationError(f"{kind} file is invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise EvaluationError(f"{kind} file must contain an object")
    return payload


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(f"field {key!r} must be a non-empty string")
    return value


def _mean(values: Any) -> float:
    rows = list(values)
    return sum(rows) / len(rows) if rows else 0.0
