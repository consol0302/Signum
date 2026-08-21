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


def build_inventory(
    summary_path: Path,
    plan_path: Path,
    audit_path: Path,
    collection_root: Path,
) -> dict[str, Any]:
    summary = read_object(summary_path)
    plan = read_object(plan_path)
    audit = read_object(audit_path)
    if (
        summary.get("claim180_collection_complete") is not True
        or audit.get("mechanical_anchor_gate_passed") is not True
        or audit.get("human_activation_confirmed") is not False
        or audit.get("method_outputs_seen") is not False
    ):
        raise RuntimeError("reserve evidence is not a complete inactive mechanical reserve")
    selected = summary["selection"]["selected_case_ids"]
    audit_by_id = {row["case_id"]: row for row in audit["rows"]}
    target_by_id = {row["case_id"]: row for row in plan["target_events"]}
    source_by_id = {row["case_id"]: row for row in plan["workflow_sources"]}
    cases = []
    for case_id in selected:
        capture_path = collection_root / case_id / "capture.json"
        capture = read_object(capture_path)
        action_id = target_by_id[case_id]["events"][0]["action_id"]
        action = next(row for row in capture["actions"] if row["id"] == action_id)
        anchor = audit_by_id[case_id]
        cases.append(
            {
                "id": case_id,
                "evidence_collection": "v4_visibility_reserve_v2",
                "source_url": source_by_id[case_id]["url"],
                "goal": source_by_id[case_id]["goal"],
                "capture_sha256": sha256_file(capture_path),
                "events": [
                    {
                        "id": action_id,
                        "category": "cursor_hover_focus",
                        "real_world_eligible": False,
                        "conditional_reserve": True,
                        "source_transition_id": f"{summary['collection_id']}/{case_id}/{action_id}",
                        "before_source_sequence": anchor["before_sequence"],
                        "after_source_sequence": anchor["after_sequence"],
                        "action": f"{action['type']}:{action_id}",
                        "expected_result": action["expected_result"],
                        "expected_outcome": action["expected_outcome"],
                        "acceptable_states": [action["expected_result"]],
                        "activation_status": "pending_main_v4_review_and_reserve_review",
                    }
                ],
            }
        )
    payload = {
        "schema_version": 1,
        "kind": "signum_claim180_v4_visibility_reserve_inventory",
        "collection_id": summary["collection_id"],
        "anchor_audit_id": audit["audit_id"],
        "labeling_status": "conditional_reserve_pending_human_review",
        "model_outputs_seen": False,
        "eligible_events": 2,
        "currently_active_events": 0,
        "category_targets": {"cursor_hover_focus": 2},
        "required_replaced_event_keys": plan["activation"]["required_v4_event_keys"],
        "activation": plan["activation"],
        "cases": cases,
    }
    payload["inventory_id"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the inactive V4 reserve inventory.")
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--collection-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite reserve inventory: {args.output}")
    payload = build_inventory(
        args.summary.resolve(), args.plan.resolve(), args.audit.resolve(), args.collection_root.resolve()
    )
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"inventory_id": payload["inventory_id"], "events": payload["eligible_events"]}))


if __name__ == "__main__":
    main()
