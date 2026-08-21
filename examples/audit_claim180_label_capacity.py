from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def audit(
    summary_path: Path,
    collection_root: Path,
    plan_path: Path,
) -> dict[str, Any]:
    summary = read_object(summary_path)
    plan = read_object(plan_path)
    selection = summary.get("selection")
    if not isinstance(selection, dict):
        raise RuntimeError("collection summary has no selection")
    selected = selection.get("selected_case_ids")
    if not isinstance(selected, list) or not selected:
        raise RuntimeError("collection summary has no finalized selected cases")
    case_rows = []
    total_actions = 0
    completed_actions = 0
    failed_actions = 0
    expected_failure_actions = 0
    expected_failure_ids = []
    for case_id in selected:
        capture_path = collection_root / case_id / "capture.json"
        capture = read_object(capture_path)
        actions = capture.get("actions")
        if capture.get("case_id") != case_id or not isinstance(actions, list):
            raise RuntimeError(f"invalid capture actions for {case_id}")
        total_actions += len(actions)
        completed = sum(row.get("status") == "completed" for row in actions)
        failed = sum(row.get("status") == "failed" for row in actions)
        expected_failures = [
            row["id"]
            for row in actions
            if row.get("expected_outcome") == "failure"
        ]
        completed_actions += completed
        failed_actions += failed
        expected_failure_actions += len(expected_failures)
        expected_failure_ids.extend(
            f"{case_id}/{action_id}" for action_id in expected_failures
        )
        case_rows.append(
            {
                "case_id": case_id,
                "capture_sha256": sha256_file(capture_path),
                "planned_actions": len(actions),
                "completed_actions": completed,
                "failed_actions": failed,
                "expected_failure_action_ids": expected_failures,
            }
        )
    category_targets = plan.get("category_targets")
    if not isinstance(category_targets, dict):
        raise RuntimeError("plan has no category targets")
    required_events = sum(category_targets.values())
    required_failures = int(category_targets.get("action_failure", 0))
    payload = {
        "schema_version": 1,
        "kind": "signum_claim180_label_capacity_audit",
        "collection_id": summary.get("collection_id"),
        "selected_workflows": len(selected),
        "required_events": required_events,
        "conservative_action_anchored_transition_capacity": total_actions,
        "completed_actions": completed_actions,
        "failed_actions": failed_actions,
        "required_action_failure_events": required_failures,
        "preregistered_expected_failure_actions": expected_failure_actions,
        "expected_failure_action_ids": expected_failure_ids,
        "event_transition_deficit": max(0, required_events - total_actions),
        "action_failure_deficit": max(
            0, required_failures - expected_failure_actions
        ),
        "capacity_rule": (
            "At most one independent source transition is credited per browser "
            "action unless separately reviewed frame evidence proves additional "
            "temporally distinct state changes. No such extra transitions are "
            "credited by this mechanical audit."
        ),
        "claim180_ready_for_labeling": (
            total_actions >= required_events
            and expected_failure_actions >= required_failures
        ),
        "cases": case_rows,
    }
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != "audit_id"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    payload["audit_id"] = hashlib.sha256(canonical).hexdigest()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Conservatively audit whether a Claim 180 collection has enough independent action transitions to label."
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--collection-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite label-capacity audit: {args.output}")
    result = audit(
        args.summary.resolve(),
        args.collection_root.resolve(),
        args.plan.resolve(),
    )
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "ready": result["claim180_ready_for_labeling"],
                "transition_capacity": result[
                    "conservative_action_anchored_transition_capacity"
                ],
                "event_deficit": result["event_transition_deficit"],
                "failure_deficit": result["action_failure_deficit"],
                "audit_id": result["audit_id"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
