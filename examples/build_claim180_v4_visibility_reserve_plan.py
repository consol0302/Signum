from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


DEFICIT_EVENT_KEYS = [
    "v4-09a-testpages/15-hover-calculation-control",
    "v4-27a-testpages/15-hover-calculation-control",
]


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def reference(path: Path, identity_field: str) -> dict[str, Any]:
    payload = read_object(path)
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "identity": payload[identity_field],
    }


def build_plan(protocol_root: Path, protocol_revision: str) -> dict[str, Any]:
    if not protocol_revision or not all(
        character in "0123456789abcdef" for character in protocol_revision.lower()
    ) or len(protocol_revision) != 40:
        raise RuntimeError("protocol revision must be a full immutable Git revision")
    sources_path = protocol_root / "claim180-v4-visibility-reserve-sources.json"
    manifest_path = protocol_root / "claim180-v4-visibility-reserve-actions-manifest.json"
    sources = read_object(sources_path)
    manifest = read_object(manifest_path)
    case_ids = sources["case_ids"]
    slots = sources["slots"]
    if manifest.get("candidate_count") != 8 or manifest.get("slot_count") != 2:
        raise RuntimeError("visibility reserve manifest must contain eight candidates")
    return {
        "schema_version": 1,
        "kind": "signum_claim180_v4_visibility_reserve_plan",
        "protocol_id": "signum-claim180-v4-visibility-reserve-2026-08-22",
        "protocol_repository": "https://github.com/consol0302/Signum",
        "protocol_revision": protocol_revision,
        "collector_revision": manifest["collector_revision"],
        "case_ids": case_ids,
        "category_targets": {"cursor_hover_focus": 2},
        "activation": {
            "status": "conditional_ineligible_reserve",
            "required_v4_event_keys": DEFICIT_EVENT_KEYS,
            "criterion": "both independent reviews and adjudication mark transition_visible false",
            "reviewer_count": 2,
            "adjudication_required": True,
            "reserve_use_forbidden_before_confirmation": True,
            "method_outputs_forbidden_before_activation": True,
            "review_packet_id": read_object(
                protocol_root / "claim180-v4-review-packet-lock.json"
            )["packet_id"],
        },
        "base_evidence": {
            "collection": reference(
                protocol_root / "claim180-v4-collection-result.json", "collection_id"
            ),
            "inventory": reference(
                protocol_root / "claim180-v4-event-inventory.json", "inventory_id"
            ),
            "anchor_audit": reference(
                protocol_root / "claim180-v4-anchor-audit.json", "audit_id"
            ),
            "review_packet_lock": reference(
                protocol_root / "claim180-v4-review-packet-lock.json", "lock_id"
            ),
        },
        "actions_manifest": {
            "path": manifest_path.name,
            "bytes": manifest_path.stat().st_size,
            "sha256": sha256_file(manifest_path),
            "collector_revision": manifest["collector_revision"],
            "case_count": len(case_ids),
        },
        "collection_selection": {
            "mode": "first_valid_per_slot_in_plan_order",
            "validity_source": "independent_capture_verification",
            "retain_all_attempts": True,
            "model_outputs_forbidden_before_selection": True,
            "required_valid_cases": 2,
            "candidate_count": 8,
            "slots": slots,
        },
        "target_events": sources["target_events"],
        "workflow_sources": sources["workflow_sources"],
        "anchor_policy": {
            "post_action_settle_seconds": 0.3,
            "next_action_crossing_allowed": False,
            "exact_before_after_png_identity_allowed": False,
        },
        "evidence_policy": {
            "all_attempts_retained": True,
            "fresh_post_lock_captures_required": True,
            "existing_v4_captures_forbidden": True,
            "human_review_required_before_activation": True,
            "model_outputs_forbidden_before_selection": True,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Build the conditional V4 reserve plan.")
    parser.add_argument("--protocol-root", type=Path, required=True)
    parser.add_argument("--protocol-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = build_plan(args.protocol_root.resolve(), args.protocol_revision)
    text = json.dumps(payload, indent=2, sort_keys=True) + "\n"
    if args.check:
        if args.output.read_text(encoding="utf-8") != text:
            raise RuntimeError("published visibility reserve plan differs from builder")
    else:
        if args.output.exists():
            raise RuntimeError(f"refusing to overwrite reserve plan: {args.output}")
        args.output.write_text(text, encoding="utf-8")
    print(json.dumps({"cases": len(payload["case_ids"]), "check": args.check}))


if __name__ == "__main__":
    main()
