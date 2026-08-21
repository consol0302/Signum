from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any


FINAL_TARGETS = {
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


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference(path: Path, inventory: dict[str, Any]) -> dict[str, Any]:
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "inventory_id": inventory["inventory_id"],
    }


def build_composite(
    v3_path: Path,
    supplement_path: Path,
) -> dict[str, Any]:
    v3 = read_object(v3_path)
    supplement = read_object(supplement_path)
    if v3.get("kind") != "signum_claim180_v3_event_inventory":
        raise RuntimeError("v3 inventory has the wrong kind")
    if supplement.get("kind") != "signum_claim180_supplement_event_inventory":
        raise RuntimeError("supplement inventory has the wrong kind")
    if v3.get("eligible_events") != 143 or supplement.get("eligible_events") != 37:
        raise RuntimeError("composite inputs do not contain 143 plus 37 events")
    if v3.get("model_outputs_seen") is not False or supplement.get(
        "model_outputs_seen"
    ) is not False:
        raise RuntimeError("composite inputs were exposed to model output")

    cases = []
    for origin, inventory in (("v3", v3), ("supplement", supplement)):
        for case in inventory.get("cases", []):
            events = [
                event
                for event in case.get("events", [])
                if event.get("real_world_eligible") is True
            ]
            if not events:
                continue
            cases.append(
                {
                    **{key: value for key, value in case.items() if key != "events"},
                    "evidence_collection": origin,
                    "events": events,
                }
            )
    events = [event for case in cases for event in case["events"]]
    counts = Counter(event["category"] for event in events)
    if len(events) != 180 or dict(counts) != FINAL_TARGETS:
        raise RuntimeError(
            f"composite category distribution differs from Claim 180: {dict(counts)}"
        )
    transition_ids = [event["source_transition_id"] for event in events]
    if len(transition_ids) != len(set(transition_ids)):
        raise RuntimeError("composite inventory reuses a source transition")
    case_ids = [case["id"] for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise RuntimeError("composite inventory has duplicate case ids")

    payload = {
        "schema_version": 1,
        "kind": "signum_claim180_composite_event_inventory",
        "labeling_status": "mechanically_anchored_pending_human_review",
        "model_outputs_seen": False,
        "component_inventories": {
            "v3": reference(v3_path, v3),
            "supplement": reference(supplement_path, supplement),
        },
        "component_collection_ids": {
            "v3": v3["collection_id"],
            "supplement": supplement["collection_id"],
        },
        "category_targets": FINAL_TARGETS,
        "eligible_events": len(events),
        "ineligible_events": 0,
        "case_count": len(cases),
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
        description="Combine the frozen 143-event v3 and 37-event supplement inventories."
    )
    parser.add_argument("--v3", type=Path, required=True)
    parser.add_argument("--supplement", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite composite inventory: {args.output}")
    payload = build_composite(args.v3.resolve(), args.supplement.resolve())
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "eligible_events": payload["eligible_events"],
                "case_count": payload["case_count"],
                "category_targets": payload["category_targets"],
                "inventory_id": payload["inventory_id"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
