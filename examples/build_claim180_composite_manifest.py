from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_manifest(
    inventory_path: Path,
    v3_root: Path,
    supplement_root: Path,
    output_path: Path,
) -> dict[str, Any]:
    inventory = read_object(inventory_path)
    if inventory.get("kind") != "signum_claim180_composite_event_inventory":
        raise RuntimeError("input is not the Claim 180 composite inventory")
    if inventory.get("eligible_events") != 180:
        raise RuntimeError("composite inventory does not contain 180 events")
    roots = {"v3": v3_root.resolve(), "supplement": supplement_root.resolve()}
    cases = []
    for case in inventory.get("cases", []):
        origin = case.get("evidence_collection")
        if origin not in roots:
            raise RuntimeError(f"case has an unknown evidence collection: {case.get('id')}")
        video_path = roots[origin] / case["video"]
        if (
            not video_path.is_file()
            or video_path.stat().st_size != case["video_bytes"]
            or sha256_file(video_path) != case["video_sha256"]
        ):
            raise RuntimeError(f"case video integrity check failed: {case['id']}")
        video_relative = Path(
            os.path.relpath(video_path, output_path.parent.resolve())
        ).as_posix()
        events = []
        for event in case["events"]:
            row = {
                "id": event["id"],
                "start": event["start"],
                "end": event["end"],
                "tolerance": 0.05,
                "acceptable_states": event["acceptable_states"],
                "category": event["category"],
                "risk": event["risk"],
                "source_transition_id": event["source_transition_id"],
                "real_world_eligible": True,
                "notes": (
                    "Mechanically anchored to the frozen action transition; "
                    "pending two-reviewer human validation."
                ),
            }
            if event["category"] in {"action_success", "action_failure"}:
                row.update(
                    {
                        "before_timestamp": event["before_timestamp"],
                        "after_timestamp": event["after_timestamp"],
                        "action": event["action"],
                        "expected_result": event["expected_result"],
                    }
                )
            events.append(row)
        cases.append(
            {
                "id": case["id"],
                "video": video_relative,
                "goal": case["goal"],
                "events": events,
            }
        )
    payload = {
        "schema_version": 2,
        "labeling_status": inventory["labeling_status"],
        "model_outputs_seen": inventory["model_outputs_seen"],
        "inventory": {
            "path": inventory_path.name,
            "bytes": inventory_path.stat().st_size,
            "sha256": sha256_file(inventory_path),
            "inventory_id": inventory["inventory_id"],
        },
        "cases": cases,
    }
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build a local schema-v2 manifest from the frozen Claim 180 inventory."
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--v3-root", type=Path, required=True)
    parser.add_argument("--supplement-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite manifest: {args.output}")
    payload = build_manifest(
        args.inventory.resolve(),
        args.v3_root.resolve(),
        args.supplement_root.resolve(),
        args.output.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "cases": len(payload["cases"]),
                "events": sum(len(case["events"]) for case in payload["cases"]),
                "labeling_status": payload["labeling_status"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
