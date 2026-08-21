from __future__ import annotations

import argparse
from collections import deque
import hashlib
import json
from pathlib import Path
from typing import Any


V3_TARGETS = {
    "small_ui": 30,
    "action_success": 24,
    "action_failure": 5,
    "popup_notification": 18,
    "loading_completion": 0,
    "scroll_navigation": 15,
    "cursor_hover_focus": 15,
    "animation_game_hud": 18,
    "transient_event": 18,
}
EXCLUDED_ACTIONS = frozenset(
    {
        "v3-17-expand-scrollbars/click-again",
        "v3-29-practice-iframes/hover-frame-1",
        "v3-29-practice-iframes/hover-frame-2",
    }
)


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def category_preferences(case_id: str, action: dict[str, Any]) -> list[str]:
    action_id = action["id"]
    if action.get("expected_outcome") == "failure":
        return ["action_failure"]
    if any(token in case_id for token in ("hovers", "tooltips", "accordion", "modals", "practice-hover")):
        return [
            "popup_notification",
            "cursor_hover_focus",
            "animation_game_hud",
            "transient_event",
            "action_success",
        ]
    if any(token in case_id for token in ("infinite-scroll", "floating-menu", "scrollbars", "iframes")):
        if action["type"] == "scroll" or "scroll" in action_id:
            return [
                "scroll_navigation",
                "animation_game_hud",
                "action_success",
            ]
        if "scrollbars" in case_id and action_id == "hover-hidden":
            return [
                "scroll_navigation",
                "cursor_hover_focus",
                "action_success",
            ]
        return [
            "cursor_hover_focus",
            "action_success",
            "small_ui",
        ]
    if "todo" in case_id and action_id in {"active", "completed", "all"}:
        return [
            "scroll_navigation",
            "transient_event",
            "small_ui",
            "action_success",
        ]
    if "slider" in case_id:
        return [
            "cursor_hover_focus",
            "small_ui",
            "action_success",
            "transient_event",
        ]
    if "keypress" in case_id or "click-events" in case_id:
        return [
            "transient_event",
            "small_ui",
            "cursor_hover_focus",
            "action_success",
        ]
    if "add-remove" in case_id:
        return [
            "animation_game_hud",
            "action_success",
            "small_ui",
            "transient_event",
        ]
    if "todo" in case_id:
        if action["type"] == "fill":
            return [
                "transient_event",
                "small_ui",
                "action_success",
                "cursor_hover_focus",
            ]
        if any(token in action_id for token in ("edit", "delete", "toggle", "complete", "clear")):
            return [
                "animation_game_hud",
                "small_ui",
                "action_success",
                "transient_event",
            ]
        return [
            "small_ui",
            "action_success",
            "animation_game_hud",
            "transient_event",
        ]
    return [
        "small_ui",
        "action_success",
        "cursor_hover_focus",
        "transient_event",
        "animation_game_hud",
    ]


def assign_categories(rows: list[dict[str, Any]]) -> dict[str, str]:
    eligible = [row for row in rows if row["event_key"] not in EXCLUDED_ACTIONS]
    if len(eligible) != sum(V3_TARGETS.values()):
        raise RuntimeError(
            f"eligible v3 action count {len(eligible)} differs from target {sum(V3_TARGETS.values())}"
        )
    source = "source"
    sink = "sink"
    # Each edge is [destination, reverse edge index, remaining capacity, cost].
    graph: dict[str, list[list[Any]]] = {}

    def edge(left: str, right: str, value: int, cost: int) -> int:
        graph.setdefault(left, [])
        graph.setdefault(right, [])
        forward_index = len(graph[left])
        reverse_index = len(graph[right])
        graph[left].append([right, reverse_index, value, cost])
        graph[right].append([left, forward_index, 0, -cost])
        return forward_index

    assignment_edges: dict[tuple[int, str], int] = {}
    for index, row in enumerate(eligible):
        node = f"event:{index}"
        edge(source, node, 1, 0)
        preferences = category_preferences(row["case_id"], row["action"])
        row["category_preferences"] = preferences
        for preference_index, category in enumerate(preferences):
            assignment_edges[(index, category)] = edge(
                node,
                f"category:{category}",
                1,
                preference_index,
            )
    for category, count in V3_TARGETS.items():
        edge(f"category:{category}", sink, count, 0)

    flow = 0
    total_cost = 0
    while flow < len(eligible):
        distance = {node: float("inf") for node in graph}
        distance[source] = 0
        parent: dict[str, tuple[str, int]] = {}
        queue = deque([source])
        queued = {source}
        while queue:
            left = queue.popleft()
            queued.remove(left)
            for edge_index, candidate in enumerate(graph[left]):
                right, _, capacity, cost = candidate
                proposed = distance[left] + cost
                if capacity > 0 and proposed < distance[right]:
                    distance[right] = proposed
                    parent[right] = (left, edge_index)
                    if right not in queued:
                        queue.append(right)
                        queued.add(right)
        if sink not in parent:
            break
        node = sink
        while node != source:
            previous, edge_index = parent[node]
            candidate = graph[previous][edge_index]
            reverse_index = candidate[1]
            candidate[2] -= 1
            graph[node][reverse_index][2] += 1
            node = previous
        flow += 1
        total_cost += int(distance[sink])
    if flow != len(eligible):
        unassigned = [
            row["event_key"]
            for index, row in enumerate(eligible)
            if graph[source][index][2] > 0
        ]
        raise RuntimeError(
            f"could not assign all v3 event categories: flow={flow}, unassigned={unassigned}"
        )
    assignments = {}
    for index, row in enumerate(eligible):
        node = f"event:{index}"
        assigned = [
            category
            for category in row["category_preferences"]
            if graph[node][assignment_edges[(index, category)]][2] == 0
        ]
        if len(assigned) != 1:
            raise RuntimeError(f"invalid category assignment for {row['event_key']}")
        assignments[row["event_key"]] = assigned[0]
    assignments["__total_cost__"] = str(total_cost)
    return assignments


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
    selected = summary.get("selection", {}).get("selected_case_ids")
    if not isinstance(selected, list) or len(selected) != 30:
        raise RuntimeError("v3 collection must contain 30 selected cases")
    rows = []
    captures = {}
    for case_id in selected:
        capture_path = collection_root / case_id / "capture.json"
        capture = read_object(capture_path)
        captures[case_id] = capture
        actions = capture.get("actions")
        if not isinstance(actions, list):
            raise RuntimeError(f"capture has no actions: {case_id}")
        for action in actions:
            if not isinstance(action, dict):
                raise RuntimeError(f"invalid action in {case_id}")
            rows.append(
                {
                    "event_key": f"{case_id}/{action['id']}",
                    "case_id": case_id,
                    "action": action,
                }
            )
    assignments = assign_categories(rows)
    source_by_id = {
        row["case_id"]: row for row in plan.get("workflow_sources", [])
    }
    cases = []
    observed_targets = {category: 0 for category in V3_TARGETS}
    excluded = []
    for case_id in selected:
        capture = captures[case_id]
        frames = capture["frames"]
        events = []
        for action in capture["actions"]:
            event_key = f"{case_id}/{action['id']}"
            before, after = frame_bounds(
                frames,
                float(action["started_at_seconds"]),
                float(action["completed_at_seconds"]),
            )
            eligible = event_key not in EXCLUDED_ACTIONS
            category = assignments.get(event_key)
            if eligible:
                if category is None:
                    raise RuntimeError(f"eligible event has no category: {event_key}")
                observed_targets[category] += 1
            else:
                excluded.append(event_key)
            events.append(
                {
                    "id": action["id"],
                    "category": category,
                    "category_preferences": (
                        category_preferences(case_id, action) if eligible else []
                    ),
                    "real_world_eligible": eligible,
                    "source_transition_id": (
                        f"{summary['collection_id']}/{event_key}"
                    ),
                    "start": before["timestamp_seconds"],
                    "end": after["timestamp_seconds"],
                    "before_timestamp": before["timestamp_seconds"],
                    "after_timestamp": after["timestamp_seconds"],
                    "before_source_sequence": before["sequence"],
                    "after_source_sequence": after["sequence"],
                    "action": f"{action['type']}:{action['id']}",
                    "expected_result": action["expected_result"],
                    "expected_outcome": action["expected_outcome"],
                    "acceptable_states": [action["expected_result"]],
                    "risk": (
                        "high" if category == "action_failure" else "normal"
                    ),
                    "exclusion_reason": (
                        None
                        if eligible
                        else "no independently visible state transition was preregistered for this pointer-only or repeated action"
                    ),
                }
            )
        video_path = collection_root / case_id / "capture.avi"
        encoding_path = collection_root / case_id / "capture.encoding.json"
        if not video_path.is_file() or not encoding_path.is_file():
            raise RuntimeError(f"encoded evidence is missing for {case_id}")
        cases.append(
            {
                "id": case_id,
                "source_url": source_by_id[case_id]["url"],
                "goal": source_by_id[case_id]["goal"],
                "capture_sha256": sha256_file(collection_root / case_id / "capture.json"),
                "video": f"{case_id}/capture.avi",
                "video_bytes": video_path.stat().st_size,
                "video_sha256": sha256_file(video_path),
                "encoding_sha256": sha256_file(encoding_path),
                "events": events,
            }
        )
    if observed_targets != V3_TARGETS:
        raise RuntimeError(
            f"v3 category assignment differs from target: {observed_targets}"
        )
    payload = {
        "schema_version": 1,
        "kind": "signum_claim180_v3_event_inventory",
        "collection_id": summary["collection_id"],
        "labeling_status": "mechanically_anchored_pending_human_review",
        "model_outputs_seen": False,
        "category_assignment": {
            "method": "deterministic_minimum_preference_cost_flow",
            "total_cost": int(assignments.pop("__total_cost__")),
        },
        "category_targets": V3_TARGETS,
        "eligible_events": sum(V3_TARGETS.values()),
        "ineligible_events": len(excluded),
        "excluded_event_keys": excluded,
        "supplement_deficits": {
            "loading_completion": 18,
            "action_failure": 19,
        },
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
        description="Build a conservative action-anchored event inventory for the v3 collection."
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
                "ineligible_events": payload["ineligible_events"],
                "category_targets": payload["category_targets"],
                "inventory_id": payload["inventory_id"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
