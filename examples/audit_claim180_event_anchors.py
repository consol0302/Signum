from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def audit_delay(
    inventory: dict[str, Any],
    collection_root: Path,
    delay_seconds: float,
) -> dict[str, Any]:
    identical: Counter[str] = Counter()
    identical_event_keys = []
    crossed_next_action = 0
    missing_after = 0
    file_hashes: dict[Path, str] = {}

    def digest(path: Path) -> str:
        if path not in file_hashes:
            file_hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
        return file_hashes[path]

    for case in inventory.get("cases", []):
        case_id = case["id"]
        case_root = collection_root / case_id
        capture = read_object(case_root / "capture.json")
        frames = capture["frames"]
        actions = capture["actions"]
        action_positions = {
            action["id"]: index for index, action in enumerate(actions)
        }
        actions_by_id = {action["id"]: action for action in actions}
        frames_by_sequence = {int(frame["sequence"]): frame for frame in frames}
        for event in case["events"]:
            action = actions_by_id[event["id"]]
            target = float(action["completed_at_seconds"]) + delay_seconds
            after = next(
                (
                    frame
                    for frame in frames
                    if float(frame["timestamp_seconds"]) >= target
                ),
                None,
            )
            if after is None:
                missing_after += 1
                continue
            position = action_positions[event["id"]]
            if position + 1 < len(actions):
                next_started = float(actions[position + 1]["started_at_seconds"])
                if float(after["timestamp_seconds"]) >= next_started:
                    crossed_next_action += 1
            before = frames_by_sequence[int(event["before_source_sequence"])]
            before_path = case_root / before["file"]
            after_path = case_root / after["file"]
            if digest(before_path) == digest(after_path):
                identical[event["category"]] += 1
                identical_event_keys.append(f"{case_id}/{event['id']}")
    identical_count = sum(identical.values())
    return {
        "delay_seconds": delay_seconds,
        "identical_pairs": identical_count,
        "identical_rate": identical_count / int(inventory["eligible_events"]),
        "identical_by_category": dict(sorted(identical.items())),
        "identical_event_keys": identical_event_keys,
        "crossed_next_action": crossed_next_action,
        "missing_after": missing_after,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Audit fixed post-action anchor delays without changing evidence."
    )
    parser.add_argument("--inventory", type=Path, required=True)
    parser.add_argument("--collection-root", type=Path, required=True)
    parser.add_argument(
        "--delays",
        type=float,
        nargs="+",
        default=[0.0, 0.1, 0.2, 0.3, 0.4, 0.5],
    )
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    inventory_path = args.inventory.resolve()
    inventory = read_object(inventory_path)
    reports = [
        audit_delay(inventory, args.collection_root.resolve(), delay)
        for delay in args.delays
    ]
    payload = {
        "schema_version": 1,
        "kind": "signum_claim180_event_anchor_audit",
        "inventory": {
            "path": inventory_path.name,
            "bytes": inventory_path.stat().st_size,
            "sha256": hashlib.sha256(inventory_path.read_bytes()).hexdigest(),
            "inventory_id": inventory.get("inventory_id"),
        },
        "metric": "exact_before_after_png_identity",
        "ground_truth_established": False,
        "reports": reports,
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    payload["audit_id"] = hashlib.sha256(canonical).hexdigest()
    output = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.output is not None:
        destination = args.output.resolve()
        if destination.exists():
            raise RuntimeError(f"refusing to overwrite anchor audit: {destination}")
        destination.write_text(output, encoding="utf-8")
    print(output, end="")


if __name__ == "__main__":
    main()
