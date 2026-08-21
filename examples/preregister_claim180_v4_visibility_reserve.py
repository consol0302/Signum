from __future__ import annotations

import argparse
from datetime import UTC, datetime
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


def fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode("utf-8")
    ).hexdigest()


def preregister(plan_path: Path) -> dict[str, Any]:
    plan = read_object(plan_path)
    if plan.get("kind") != "signum_claim180_v4_visibility_reserve_plan":
        raise RuntimeError("invalid visibility reserve plan kind")
    case_ids = plan.get("case_ids")
    selection = plan.get("collection_selection")
    activation = plan.get("activation")
    if not isinstance(case_ids, list) or len(case_ids) != 8:
        raise RuntimeError("visibility reserve must contain eight candidates")
    if (
        not isinstance(selection, dict)
        or selection.get("required_valid_cases") != 2
        or selection.get("candidate_count") != 8
        or len(selection.get("slots", [])) != 2
    ):
        raise RuntimeError("visibility reserve must freeze two four-candidate slots")
    flattened = [
        case_id
        for slot in selection["slots"]
        for case_id in slot.get("candidate_ids", [])
    ]
    if flattened != case_ids or len(set(flattened)) != 8:
        raise RuntimeError("reserve slot order differs from case ids")
    if (
        not isinstance(activation, dict)
        or activation.get("reserve_use_forbidden_before_confirmation") is not True
        or activation.get("method_outputs_forbidden_before_activation") is not True
        or activation.get("reviewer_count") != 2
        or activation.get("adjudication_required") is not True
    ):
        raise RuntimeError("reserve activation is not safely conditional")
    base = plan.get("base_evidence")
    if not isinstance(base, dict):
        raise RuntimeError("reserve base evidence is missing")
    for reference in base.values():
        path = (plan_path.parent / reference["path"]).resolve()
        if (
            path.stat().st_size != reference["bytes"]
            or sha256_file(path) != reference["sha256"]
        ):
            raise RuntimeError("reserve base evidence integrity check failed")
    audit = read_object(
        (plan_path.parent / base["anchor_audit"]["path"]).resolve()
    )
    report = next(
        row for row in audit["reports"] if row["delay_seconds"] == 0.3
    )
    if report["identical_event_keys"] != activation["required_v4_event_keys"]:
        raise RuntimeError("reserve activation deficits differ from the anchor audit")
    manifest_ref = plan["actions_manifest"]
    manifest_path = (plan_path.parent / manifest_ref["path"]).resolve()
    if (
        manifest_path.stat().st_size != manifest_ref["bytes"]
        or sha256_file(manifest_path) != manifest_ref["sha256"]
    ):
        raise RuntimeError("reserve actions manifest integrity check failed")
    manifest = read_object(manifest_path)
    if [row["case_id"] for row in manifest["cases"]] != case_ids:
        raise RuntimeError("reserve action cases differ from plan")
    target_rows = plan.get("target_events")
    if not isinstance(target_rows, list) or len(target_rows) != 8:
        raise RuntimeError("reserve target events are incomplete")
    for target, manifest_row in zip(target_rows, manifest["cases"], strict=True):
        events = target.get("events")
        action_path = (manifest_path.parent / manifest_row["action_file"]).resolve()
        action_spec = read_object(action_path)
        actions = {row["id"]: row for row in action_spec["actions"]}
        if (
            target.get("case_id") != manifest_row["case_id"]
            or not isinstance(events, list)
            or len(events) != 1
            or events[0].get("category") != "cursor_hover_focus"
            or actions[events[0]["action_id"]].get("type") != "hover"
        ):
            raise RuntimeError("reserve target is not one frozen hover action")
    payload = {
        "schema_version": 1,
        "kind": "signum_claim180_v4_visibility_reserve_preregistration",
        "created_at_utc": datetime.now(UTC).isoformat(),
        "plan": plan_path.name,
        "plan_bytes": plan_path.stat().st_size,
        "plan_sha256": sha256_file(plan_path),
        "protocol_id": plan["protocol_id"],
        "protocol_repository": plan["protocol_repository"],
        "protocol_revision": plan["protocol_revision"],
        "case_ids": case_ids,
        "category_targets": plan["category_targets"],
        "activation": activation,
        "collection_selection": selection,
        "anchor_policy": plan["anchor_policy"],
        "actions_manifest": manifest_ref,
    }
    payload["preregistration_id"] = fingerprint(
        {key: value for key, value in payload.items() if key != "created_at_utc"}
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(description="Preregister the conditional V4 reserve.")
    parser.add_argument("plan", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite reserve lock: {args.output}")
    payload = preregister(args.plan.resolve())
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"preregistration_id": payload["preregistration_id"]}))


if __name__ == "__main__":
    main()
