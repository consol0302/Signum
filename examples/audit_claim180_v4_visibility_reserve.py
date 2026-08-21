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


def build_audit(summary_path: Path, plan_path: Path, root: Path) -> dict[str, Any]:
    summary = read_object(summary_path)
    plan = read_object(plan_path)
    selected = summary.get("selection", {}).get("selected_case_ids")
    if summary.get("claim180_collection_complete") is not True or len(selected or []) != 2:
        raise RuntimeError("visibility reserve must select exactly two cases")
    target_by_id = {row["case_id"]: row for row in plan["target_events"]}
    settle = float(plan["anchor_policy"]["post_action_settle_seconds"])
    rows = []
    for case_id in selected:
        case_root = root / case_id
        capture = read_object(case_root / "capture.json")
        target = target_by_id[case_id]["events"][0]
        actions = capture["actions"]
        action_index = next(
            index for index, action in enumerate(actions) if action["id"] == target["action_id"]
        )
        action = actions[action_index]
        frames = capture["frames"]
        before = [
            frame
            for frame in frames
            if float(frame["timestamp_seconds"]) <= float(action["started_at_seconds"])
        ][-1]
        after = next(
            frame
            for frame in frames
            if float(frame["timestamp_seconds"])
            >= float(action["completed_at_seconds"]) + settle
        )
        crossing = False
        if action_index + 1 < len(actions):
            crossing = float(after["timestamp_seconds"]) >= float(
                actions[action_index + 1]["started_at_seconds"]
            )
        before_hash = sha256_file(case_root / before["file"])
        after_hash = sha256_file(case_root / after["file"])
        rows.append(
            {
                "case_id": case_id,
                "action_id": action["id"],
                "category": target["category"],
                "before_sequence": before["sequence"],
                "after_sequence": after["sequence"],
                "before_sha256": before_hash,
                "after_sha256": after_hash,
                "identical": before_hash == after_hash,
                "crossed_next_action": crossing,
            }
        )
    payload = {
        "schema_version": 1,
        "kind": "signum_claim180_v4_visibility_reserve_anchor_audit",
        "collection_id": summary["collection_id"],
        "summary_sha256": sha256_file(summary_path),
        "plan_sha256": sha256_file(plan_path),
        "post_action_settle_seconds": settle,
        "rows": rows,
        "mechanical_anchor_gate_passed": all(
            not row["identical"] and not row["crossed_next_action"] for row in rows
        ),
        "human_activation_confirmed": False,
        "method_outputs_seen": False,
    }
    payload["audit_id"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit selected V4 reserve anchors.")
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--collection-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite reserve audit: {args.output}")
    payload = build_audit(
        args.summary.resolve(), args.plan.resolve(), args.collection_root.resolve()
    )
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"audit_id": payload["audit_id"], "passed": payload["mechanical_anchor_gate_passed"]}))


if __name__ == "__main__":
    main()
