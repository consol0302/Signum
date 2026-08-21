from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any


CLAIM180_TARGETS = {
    "small_ui": 30,
    "action_success": 24,
    "action_failure": 24,
    "popup_notification": 18,
    "loading_completion": 18,
    "scroll_navigation": 15,
    "cursor_hover_focus": 15,
    "animation_game_hud": 18,
    "transient_event": 18,
}
POST_ACTION_SETTLE_SECONDS = 0.3


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
    *,
    settle_seconds: float,
) -> tuple[dict[str, Any], dict[str, Any]]:
    before_candidates = [
        frame for frame in frames if float(frame["timestamp_seconds"]) <= started
    ]
    after_candidates = [
        frame
        for frame in frames
        if float(frame["timestamp_seconds"]) >= completed + settle_seconds
    ]
    before = before_candidates[-1] if before_candidates else frames[0]
    after = after_candidates[0] if after_candidates else frames[-1]
    if before["sequence"] == after["sequence"]:
        index = frames.index(before)
        if index > 0:
            before = frames[index - 1]
        elif index + 1 < len(frames):
            after = frames[index + 1]
    if before["sequence"] == after["sequence"]:
        raise RuntimeError("event does not have two distinct source frames")
    return before, after


def build_inventory(
    summary_path: Path,
    collection_root: Path,
    plan_path: Path,
) -> dict[str, Any]:
    summary = read_object(summary_path)
    plan = read_object(plan_path)
    if summary.get("claim180_collection_complete") is not True:
        raise RuntimeError("V4 collection is not complete")
    selected = summary.get("selection", {}).get("selected_case_ids")
    selected_by_slot = summary.get("selection", {}).get("selected_by_slot")
    if (
        not isinstance(selected, list)
        or len(selected) != 30
        or len(selected) != len(set(selected))
        or not isinstance(selected_by_slot, list)
        or [row.get("case_id") for row in selected_by_slot] != selected
    ):
        raise RuntimeError("V4 collection must select one unique case for each slot")
    if plan.get("category_targets") != CLAIM180_TARGETS:
        raise RuntimeError("V4 plan category targets differ from Claim 180")

    targets_by_id = {
        row["case_id"]: row for row in plan.get("target_events", [])
    }
    sources_by_id = {
        row["case_id"]: row for row in plan.get("workflow_sources", [])
    }
    cases = []
    observed_categories: Counter[str] = Counter()
    transition_ids = set()
    for selected_slot in selected_by_slot:
        case_id = selected_slot["case_id"]
        slot_id = selected_slot["slot_id"]
        target_row = targets_by_id.get(case_id)
        source = sources_by_id.get(case_id)
        if (
            not isinstance(target_row, dict)
            or target_row.get("slot_id") != slot_id
            or not isinstance(source, dict)
            or source.get("slot_id") != slot_id
        ):
            raise RuntimeError(f"V4 plan binding is missing for {case_id}")
        capture_path = collection_root / case_id / "capture.json"
        capture = read_object(capture_path)
        if capture.get("case_id") != case_id or capture.get("valid") is not True:
            raise RuntimeError(f"selected capture is invalid: {case_id}")
        frames = capture.get("frames")
        actions = capture.get("actions")
        if not isinstance(frames, list) or not frames or not isinstance(actions, list):
            raise RuntimeError(f"selected capture has incomplete evidence: {case_id}")
        actions_by_id = {
            action["id"]: action
            for action in actions
            if isinstance(action, dict) and isinstance(action.get("id"), str)
        }
        action_positions = {
            action["id"]: index
            for index, action in enumerate(actions)
            if isinstance(action, dict) and isinstance(action.get("id"), str)
        }
        events = []
        target_events = target_row.get("events")
        if not isinstance(target_events, list) or len(target_events) != 6:
            raise RuntimeError(f"V4 target row must contain six events: {case_id}")
        for target in target_events:
            action_id = target.get("action_id")
            category = target.get("category")
            action = actions_by_id.get(action_id)
            if not isinstance(action, dict) or category not in CLAIM180_TARGETS:
                raise RuntimeError(f"V4 target action is missing: {case_id}/{action_id}")
            if action.get("status") != "completed":
                raise RuntimeError(f"V4 target action did not complete: {case_id}/{action_id}")
            expected_outcome = action.get("expected_outcome", "success")
            if (category == "action_failure") != (expected_outcome == "failure"):
                raise RuntimeError(
                    f"V4 action-failure label is inconsistent: {case_id}/{action_id}"
                )
            before, after = frame_bounds(
                frames,
                float(action["started_at_seconds"]),
                float(action["completed_at_seconds"]),
                settle_seconds=POST_ACTION_SETTLE_SECONDS,
            )
            action_position = action_positions[action_id]
            if action_position + 1 < len(actions):
                next_started = float(
                    actions[action_position + 1]["started_at_seconds"]
                )
                if float(after["timestamp_seconds"]) >= next_started:
                    raise RuntimeError(
                        f"V4 settled anchor crosses the next action: {case_id}/{action_id}"
                    )
            transition_id = f"{summary['collection_id']}/{case_id}/{action_id}"
            if transition_id in transition_ids:
                raise RuntimeError(f"duplicate V4 transition id: {transition_id}")
            transition_ids.add(transition_id)
            observed_categories[category] += 1
            events.append(
                {
                    "id": action_id,
                    "category": category,
                    "real_world_eligible": True,
                    "source_transition_id": transition_id,
                    "start": before["timestamp_seconds"],
                    "end": after["timestamp_seconds"],
                    "before_timestamp": before["timestamp_seconds"],
                    "after_timestamp": after["timestamp_seconds"],
                    "before_source_sequence": before["sequence"],
                    "after_source_sequence": after["sequence"],
                    "action": f"{action['type']}:{action_id}",
                    "expected_result": action["expected_result"],
                    "expected_outcome": expected_outcome,
                    "acceptable_states": [action["expected_result"]],
                    "risk": "high" if category == "action_failure" else "normal",
                    "exclusion_reason": None,
                }
            )
        video_path = collection_root / case_id / "capture.avi"
        encoding_path = collection_root / case_id / "capture.encoding.json"
        if not video_path.is_file() or not encoding_path.is_file():
            raise RuntimeError(f"encoded evidence is missing for {case_id}")
        cases.append(
            {
                "id": case_id,
                "slot_id": slot_id,
                "evidence_collection": "v4",
                "source_url": source["url"],
                "goal": source["goal"],
                "capture_sha256": sha256_file(capture_path),
                "video": f"{case_id}/capture.avi",
                "video_bytes": video_path.stat().st_size,
                "video_sha256": sha256_file(video_path),
                "encoding_sha256": sha256_file(encoding_path),
                "events": events,
            }
        )
    observed = {category: observed_categories[category] for category in CLAIM180_TARGETS}
    if observed != CLAIM180_TARGETS:
        raise RuntimeError(f"V4 event categories differ from Claim 180: {observed}")
    payload = {
        "schema_version": 1,
        "kind": "signum_claim180_v4_event_inventory",
        "collection_id": summary["collection_id"],
        "collection_summary": {
            "path": summary_path.name,
            "bytes": summary_path.stat().st_size,
            "sha256": sha256_file(summary_path),
        },
        "plan": {
            "path": plan_path.name,
            "bytes": plan_path.stat().st_size,
            "sha256": sha256_file(plan_path),
        },
        "labeling_status": "mechanically_anchored_pending_human_review",
        "model_outputs_seen": False,
        "category_assignment": {"method": "preregistered_slot_target_events"},
        "anchor_policy": {
            "before": "latest source frame at or before action start",
            "after": "first source frame at or after action completion plus fixed settle delay",
            "post_action_settle_seconds": POST_ACTION_SETTLE_SECONDS,
            "next_action_crossing_allowed": False,
        },
        "category_targets": CLAIM180_TARGETS,
        "eligible_events": 180,
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
        description="Build the preregistered 180-event inventory for Claim 180 V4."
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
