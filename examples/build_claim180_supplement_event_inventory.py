from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


TARGETS = {"action_failure": 19, "loading_completion": 18}


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def frame_bounds(
    frames: list[dict[str, Any]],
    started: float,
    completed: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    before_candidates = [
        frame for frame in frames if float(frame["timestamp_seconds"]) <= started
    ]
    after_candidates = [
        frame for frame in frames if float(frame["timestamp_seconds"]) >= completed
    ]
    before = before_candidates[-1] if before_candidates else frames[0]
    after = after_candidates[0] if after_candidates else frames[-1]
    if before["sequence"] == after["sequence"]:
        index = frames.index(before)
        if index > 0:
            before = frames[index - 1]
        elif index + 1 < len(frames):
            after = frames[index + 1]
    return before, after


def build_inventory(
    summary_path: Path,
    collection_root: Path,
    plan_path: Path,
) -> dict[str, Any]:
    summary = read_object(summary_path)
    plan = read_object(plan_path)
    if summary.get("claim180_supplement_complete") is not True:
        raise RuntimeError("supplement collection is not complete")
    if summary.get("model_outputs_seen") is not False:
        raise RuntimeError("supplement selection was exposed to model output")
    if plan.get("category_targets") != TARGETS:
        raise RuntimeError("supplement category targets changed")
    selected = summary.get("selection", {}).get("selected_target_events")
    if not isinstance(selected, list) or len(selected) != sum(TARGETS.values()):
        raise RuntimeError("supplement summary must select exactly 37 target events")
    target_by_case = {
        row["case_id"]: row for row in plan.get("target_events", [])
    }
    source_by_case = {
        row["case_id"]: row for row in plan.get("workflow_sources", [])
    }
    observed = {category: 0 for category in TARGETS}
    cases = []
    transition_ids = set()
    for selected_row in selected:
        case_id = selected_row["case_id"]
        target = target_by_case.get(case_id)
        source = source_by_case.get(case_id)
        selected_target = {
            "case_id": selected_row.get("case_id"),
            "action_id": selected_row.get("target_action_id"),
            "category": selected_row.get("category"),
            "expected_result": selected_row.get("expected_result"),
        }
        if target is None or source is None or target != selected_target:
            raise RuntimeError(f"selected target differs from plan: {case_id}")
        category = target["category"]
        observed[category] += 1
        case_root = collection_root / case_id
        capture_path = case_root / "capture.json"
        verification_path = case_root / "verification.json"
        video_path = case_root / "capture.avi"
        encoding_path = case_root / "capture.encoding.json"
        capture = read_object(capture_path)
        verification = read_object(verification_path)
        if capture.get("valid") is not True or verification.get("valid") is not True:
            raise RuntimeError(f"selected capture is not independently valid: {case_id}")
        actions = [
            row
            for row in capture.get("actions", [])
            if isinstance(row, dict) and row.get("id") == target["action_id"]
        ]
        if len(actions) != 1 or actions[0].get("status") != "completed":
            raise RuntimeError(f"selected target action is not completed: {case_id}")
        action = actions[0]
        frames = capture.get("frames")
        if not isinstance(frames, list) or not frames:
            raise RuntimeError(f"selected capture has no frames: {case_id}")
        before, after = frame_bounds(
            frames,
            float(action["started_at_seconds"]),
            float(action["completed_at_seconds"]),
        )
        if not video_path.is_file() or not encoding_path.is_file():
            raise RuntimeError(f"encoded supplement evidence is missing: {case_id}")
        transition_id = (
            f"{summary['collection_id']}/{case_id}/{target['action_id']}"
        )
        if transition_id in transition_ids:
            raise RuntimeError(f"duplicate supplement transition: {transition_id}")
        transition_ids.add(transition_id)
        event = {
            "id": target["action_id"],
            "category": category,
            "category_preferences": [category],
            "real_world_eligible": True,
            "source_transition_id": transition_id,
            "start": before["timestamp_seconds"],
            "end": after["timestamp_seconds"],
            "before_timestamp": before["timestamp_seconds"],
            "after_timestamp": after["timestamp_seconds"],
            "before_source_sequence": before["sequence"],
            "after_source_sequence": after["sequence"],
            "action": f"{action['type']}:{action['id']}",
            "expected_result": target["expected_result"],
            "expected_outcome": action["expected_outcome"],
            "acceptable_states": [target["expected_result"]],
            "risk": "high" if category == "action_failure" else "normal",
            "exclusion_reason": None,
        }
        cases.append(
            {
                "id": case_id,
                "source_url": source["url"],
                "goal": source["goal"],
                "capture_sha256": sha256_file(capture_path),
                "verification_sha256": sha256_file(verification_path),
                "video": f"{case_id}/capture.avi",
                "video_bytes": video_path.stat().st_size,
                "video_sha256": sha256_file(video_path),
                "encoding_sha256": sha256_file(encoding_path),
                "events": [event],
            }
        )
    if observed != TARGETS:
        raise RuntimeError(f"supplement selected categories changed: {observed}")
    payload = {
        "schema_version": 1,
        "kind": "signum_claim180_supplement_event_inventory",
        "collection_id": summary["collection_id"],
        "preregistration_id": summary["preregistration_id"],
        "labeling_status": "mechanically_anchored_pending_human_review",
        "model_outputs_seen": False,
        "category_assignment": {
            "method": "preregistered_target_category",
            "selection": "first_independently_valid_by_category_in_plan_order",
        },
        "category_targets": TARGETS,
        "eligible_events": sum(TARGETS.values()),
        "ineligible_events": 0,
        "excluded_event_keys": [],
        "cases": cases,
    }
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != "inventory_id"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    payload["inventory_id"] = hashlib.sha256(canonical).hexdigest()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the 37-event action-anchored supplement inventory."
    )
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--collection-root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite event inventory: {args.output}")
    payload = build_inventory(
        args.summary.resolve(), args.collection_root.resolve(), args.plan.resolve()
    )
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "eligible_events": payload["eligible_events"],
                "category_targets": payload["category_targets"],
                "inventory_id": payload["inventory_id"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
