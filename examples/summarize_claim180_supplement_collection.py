from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def read_object(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must contain an object")
    return payload


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_reference(path: Path, relative_to: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(relative_to.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def summarize_case(
    root: Path,
    case_id: str,
    target: dict[str, Any],
) -> dict[str, Any]:
    case_root = root / case_id
    capture_path = case_root / "capture.json"
    failure_path = case_root / "failure.json"
    if failure_path.is_file() and not capture_path.is_file():
        failure = read_object(failure_path, f"failure for {case_id}")
        return {
            "case_id": case_id,
            "category": target["category"],
            "target_action_id": target["action_id"],
            "collection_status": "startup_failed",
            "eligible_for_selection": False,
            "failure": failure.get("failure"),
            "failure_artifact": file_reference(failure_path, root),
        }
    if not capture_path.is_file():
        return {
            "case_id": case_id,
            "category": target["category"],
            "target_action_id": target["action_id"],
            "collection_status": "missing",
            "eligible_for_selection": False,
            "failure": "neither capture.json nor failure.json exists",
        }
    verification_path = case_root / "verification.json"
    capture = read_object(capture_path, f"capture for {case_id}")
    if not verification_path.is_file():
        return {
            "case_id": case_id,
            "category": target["category"],
            "target_action_id": target["action_id"],
            "collection_status": "unverified",
            "eligible_for_selection": False,
            "capture_artifact": file_reference(capture_path, root),
            "failure": "independent verification artifact is missing",
        }
    verification = read_object(verification_path, f"verification for {case_id}")
    if capture.get("case_id") != case_id or verification.get("case_id") != case_id:
        raise RuntimeError(f"case identity mismatch for {case_id}")
    actions = capture.get("actions")
    if not isinstance(actions, list):
        raise RuntimeError(f"capture actions must be an array for {case_id}")
    target_actions = [
        row
        for row in actions
        if isinstance(row, dict) and row.get("id") == target["action_id"]
    ]
    target_action = target_actions[0] if len(target_actions) == 1 else None
    anchor_valid = (
        target_action is not None
        and target_action.get("status") == "completed"
        and isinstance(target_action.get("started_at_seconds"), (int, float))
        and isinstance(target_action.get("completed_at_seconds"), (int, float))
    )
    valid = verification.get("valid") is True and anchor_valid
    return {
        "case_id": case_id,
        "category": target["category"],
        "target_action_id": target["action_id"],
        "expected_result": target["expected_result"],
        "collection_status": "valid" if valid else "invalid",
        "eligible_for_selection": valid,
        "capture_artifact": file_reference(capture_path, root),
        "verification_artifact": file_reference(verification_path, root),
        "integrity_valid": verification.get("integrity_valid") is True,
        "policy_valid": verification.get("policy_valid") is True,
        "policy_reasons": verification.get("policy_reasons", []),
        "target_anchor_valid": anchor_valid,
        "target_anchor": (
            {
                key: target_action.get(key)
                for key in (
                    "expected_outcome",
                    "scheduled_at_seconds",
                    "started_at_seconds",
                    "completed_at_seconds",
                )
            }
            if target_action is not None
            else None
        ),
    }


def build_summary(
    root: Path,
    plan_path: Path,
    preregistration_path: Path,
) -> dict[str, Any]:
    plan = read_object(plan_path, "supplement plan")
    preregistration = read_object(preregistration_path, "supplement preregistration")
    if plan.get("kind") != "signum_claim180_supplement_plan":
        raise RuntimeError("plan has the wrong kind")
    if preregistration.get("kind") != "signum_claim180_supplement_preregistration":
        raise RuntimeError("preregistration has the wrong kind")
    if (
        preregistration.get("plan_sha256") != sha256_file(plan_path)
        or preregistration.get("plan_bytes") != plan_path.stat().st_size
        or preregistration.get("case_ids") != plan.get("case_ids")
        or preregistration.get("target_events") != plan.get("target_events")
        or preregistration.get("collection_selection")
        != plan.get("collection_selection")
    ):
        raise RuntimeError("supplement preregistration does not bind this plan")
    case_ids = plan["case_ids"]
    targets = plan["target_events"]
    if not root.is_dir():
        raise RuntimeError(f"collection root is missing: {root}")
    cases = [
        summarize_case(root, case_id, target)
        for case_id, target in zip(case_ids, targets, strict=True)
    ]
    statuses = ("valid", "invalid", "startup_failed", "missing", "unverified")
    counts = {
        status: sum(row["collection_status"] == status for row in cases)
        for status in statuses
    }
    selected_by_category: dict[str, list[str]] = {}
    selected_ids: set[str] = set()
    for category, required in plan["category_targets"].items():
        eligible = [
            row["case_id"]
            for row in cases
            if row["category"] == category and row["eligible_for_selection"]
        ]
        selected_by_category[category] = eligible[:required]
        selected_ids.update(selected_by_category[category])
    unexpected = sorted(
        path.name
        for path in root.iterdir()
        if path.is_dir() and path.name not in case_ids
    )
    complete = (
        counts["missing"] == 0
        and counts["unverified"] == 0
        and not unexpected
        and all(
            len(selected_by_category[category]) == required
            for category, required in plan["category_targets"].items()
        )
    )
    selected_target_events = [
        {
            "case_id": row["case_id"],
            "category": row["category"],
            "target_action_id": row["target_action_id"],
            "expected_result": row["expected_result"],
            "target_anchor": row["target_anchor"],
        }
        for row in cases
        if row["case_id"] in selected_ids
    ] if complete else []
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": "signum_claim180_supplement_collection_summary",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "preregistration_id": preregistration.get("preregistration_id"),
        "plan": file_reference(plan_path, plan_path.parent),
        "preregistration": file_reference(
            preregistration_path, preregistration_path.parent
        ),
        "counts": counts,
        "selection": {
            "mode": "first_valid_target_event_by_category_in_plan_order",
            "category_targets": plan["category_targets"],
            "selected_case_ids_by_category": selected_by_category if complete else {},
            "selected_target_events": selected_target_events,
        },
        "claim180_supplement_complete": complete,
        "unexpected_case_directories": unexpected,
        "model_outputs_seen": False,
        "cases": cases,
    }
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != "generated_at_utc"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    payload["collection_id"] = hashlib.sha256(canonical).hexdigest()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize and select a one-shot Claim 180 supplement collection."
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite collection summary: {args.output}")
    payload = build_summary(
        args.root.resolve(), args.plan.resolve(), args.preregistration.resolve()
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "counts": payload["counts"],
                "complete": payload["claim180_supplement_complete"],
                "collection_id": payload["collection_id"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
