from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from build_ground_truth_review_packet import (
    EXACT_REVIEW_EQUIVALENCE_FIELDS,
    exact_duplicate_review_groups,
    packet_id,
)


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def file_reference(path: Path) -> dict[str, Any]:
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build_lock(
    packet_root: Path,
    source_lock_path: Path,
    *,
    expected_decisions: int,
) -> dict[str, Any]:
    packet_path = packet_root / "packet.json"
    packet = read_object(packet_path)
    source_lock = read_object(source_lock_path)
    if packet.get("packet_id") != source_lock.get("packet_id"):
        raise RuntimeError("source lock belongs to a different review packet")
    if packet.get("method_outputs_included") is not False:
        raise RuntimeError("exact-duplicate review must remain method blind")
    groups = exact_duplicate_review_groups(packet)
    if len(groups) != expected_decisions:
        raise RuntimeError(
            f"expected {expected_decisions} exact review groups, found {len(groups)}"
        )
    member_ids = [
        blinded_id
        for group in groups
        for blinded_id in group["member_blinded_ids"]
    ]
    packet_ids = [item["blinded_id"] for item in packet["items"]]
    if sorted(member_ids) != sorted(packet_ids) or len(member_ids) != len(set(member_ids)):
        raise RuntimeError("exact review groups do not cover the packet exactly once")
    interfaces = []
    for reviewer in ("reviewer-a", "reviewer-b"):
        html_path = packet_root / f"{reviewer}.unique.ko.html"
        review_path = packet_root / f"{reviewer}.json"
        if not html_path.is_file() or not review_path.is_file():
            raise RuntimeError(f"missing exact-duplicate interface for {reviewer}")
        interfaces.append(
            {
                "reviewer_slot": reviewer,
                "html": file_reference(html_path),
                "review_template": file_reference(review_path),
            }
        )
    payload = {
        "schema_version": 1,
        "kind": "signum_exact_duplicate_ground_truth_review_lock",
        "packet_id": packet["packet_id"],
        "source_review_packet_lock": {
            **file_reference(source_lock_path),
            "lock_id": source_lock.get("lock_id"),
        },
        "packet": file_reference(packet_path),
        "method_outputs_included": False,
        "review_method": "independent_blind_before_after_exact_duplicate_propagation",
        "equivalence_fields": list(EXACT_REVIEW_EQUIVALENCE_FIELDS),
        "original_item_count": packet["item_count"],
        "unique_decision_count": len(groups),
        "propagated_item_count": packet["item_count"] - len(groups),
        "groups": groups,
        "reviewer_interfaces": interfaces,
        "analysis_policy": {
            "propagated_rows_are_not_independent_human_judgments": True,
            "provider_comparisons_must_preserve_case_and_repetition_clustering": True,
            "do_not_report_original_item_count_as_independent_review_count": True,
        },
        "superseded_incomplete_review": {
            "completed_artifact_exists": False,
            "user_reported_approximate_completed_items": 60,
            "recovered": False,
            "excluded_from_analysis": True,
            "reason": (
                "The legacy local-file UI had no partial export or autosave, and the "
                "browser security boundary prevented read-only recovery."
            ),
        },
    }
    payload["lock_id"] = packet_id(payload)
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Lock an exact-duplicate-propagating ground-truth review UI."
    )
    parser.add_argument("--packet-root", type=Path, required=True)
    parser.add_argument("--source-lock", type=Path, required=True)
    parser.add_argument("--expected-decisions", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    payload = build_lock(
        args.packet_root.resolve(),
        args.source_lock.resolve(),
        expected_decisions=args.expected_decisions,
    )
    args.output.resolve().write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "lock_id": payload["lock_id"],
                "unique_decisions": payload["unique_decision_count"],
                "propagated_items": payload["propagated_item_count"],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
