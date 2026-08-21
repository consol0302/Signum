from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any


BASE_SPECS = {
    "preregistration": (
        "signum_heldout_preregistration",
        "preregistration_id",
    ),
    "collection_summary": (
        "signum_claim180_collection_summary",
        "collection_id",
    ),
    "event_inventory": (
        "signum_claim180_v3_event_inventory",
        "inventory_id",
    ),
}


def read_object(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must contain a JSON object")
    return payload


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_reference(
    path: Path,
    output: Path,
    *,
    identity: str | None = None,
) -> dict[str, Any]:
    reference = {
        "path": Path(
            os.path.relpath(path.resolve(), output.parent.resolve())
        ).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }
    if identity is not None:
        reference["identity"] = identity
    return reference


def build_plan(
    *,
    base_preregistration_path: Path,
    base_collection_path: Path,
    base_inventory_path: Path,
    sources_path: Path,
    targets_path: Path,
    actions_manifest_path: Path,
    output_path: Path,
    protocol_repository: str,
    protocol_revision: str,
) -> dict[str, Any]:
    if not protocol_repository.startswith("https://"):
        raise RuntimeError("protocol repository must use https")
    if len(protocol_revision) not in {40, 64} or any(
        character not in "0123456789abcdefABCDEF"
        for character in protocol_revision
    ):
        raise RuntimeError("protocol revision must be a full immutable hash")

    base_paths = {
        "preregistration": base_preregistration_path.resolve(),
        "collection_summary": base_collection_path.resolve(),
        "event_inventory": base_inventory_path.resolve(),
    }
    base_payloads = {
        name: read_object(path, f"base {name}")
        for name, path in base_paths.items()
    }
    base_evidence = {}
    for name, (expected_kind, identity_field) in BASE_SPECS.items():
        payload = base_payloads[name]
        if payload.get("schema_version") != 1 or payload.get("kind") != expected_kind:
            raise RuntimeError(f"base {name} has the wrong schema or kind")
        identity = payload.get(identity_field)
        if not isinstance(identity, str) or not identity:
            raise RuntimeError(f"base {name} has no {identity_field}")
        base_evidence[name] = relative_reference(
            base_paths[name], output_path, identity=identity
        )

    inventory = base_payloads["event_inventory"]
    category_targets = inventory.get("supplement_deficits")
    if category_targets != {"action_failure": 19, "loading_completion": 18}:
        raise RuntimeError("base inventory does not have the expected exact deficit")
    base_preregistration = base_payloads["preregistration"]
    evidence_policy = base_preregistration.get("evidence_policy")
    observation_budget = base_preregistration.get("observation_budget")
    if not isinstance(evidence_policy, dict) or not evidence_policy:
        raise RuntimeError("base preregistration has no evidence policy")
    if not isinstance(observation_budget, dict) or not observation_budget:
        raise RuntimeError("base preregistration has no observation budget")

    sources = read_object(sources_path, "supplement sources")
    targets = read_object(targets_path, "supplement targets")
    actions_manifest = read_object(actions_manifest_path, "actions manifest")
    if sources.get("kind") != "signum_claim180_supplement_candidate_sources":
        raise RuntimeError("supplement sources have the wrong kind")
    if targets.get("kind") != "signum_claim180_supplement_target_events":
        raise RuntimeError("supplement targets have the wrong kind")
    if actions_manifest.get("kind") != "signum_claim180_browser_actions":
        raise RuntimeError("supplement actions manifest has the wrong kind")
    case_ids = sources.get("case_ids")
    workflow_sources = sources.get("workflow_sources")
    target_events = targets.get("target_events")
    action_case_ids = [
        row.get("case_id")
        for row in actions_manifest.get("cases", [])
        if isinstance(row, dict)
    ]
    if (
        not isinstance(case_ids, list)
        or len(case_ids) != 52
        or len(case_ids) != len(set(case_ids))
        or [row.get("case_id") for row in workflow_sources or []] != case_ids
        or [row.get("case_id") for row in target_events or []] != case_ids
        or action_case_ids != case_ids
    ):
        raise RuntimeError("supplement catalogs and manifest do not share one order")
    candidate_counts = {
        category: sum(
            isinstance(row, dict) and row.get("category") == category
            for row in target_events
        )
        for category in category_targets
    }
    if candidate_counts != {"action_failure": 26, "loading_completion": 26}:
        raise RuntimeError("supplement candidate category counts changed")

    return {
        "schema_version": 1,
        "kind": "signum_claim180_supplement_plan",
        "protocol_id": "signum-claim180-deficit-supplement-v1",
        "protocol_repository": protocol_repository,
        "protocol_revision": protocol_revision.lower(),
        "base_evidence": base_evidence,
        "category_targets": category_targets,
        "case_ids": case_ids,
        "workflow_sources": workflow_sources,
        "target_events": target_events,
        "actions_manifest": relative_reference(
            actions_manifest_path.resolve(), output_path
        ),
        "collection_selection": {
            "mode": "first_valid_target_event_by_category_in_plan_order",
            "validity_source": "independent_capture_verification",
            "retain_all_attempts": True,
            "model_outputs_forbidden_before_selection": True,
            "candidate_count": len(case_ids),
            "category_targets": category_targets,
        },
        "evidence_policy": evidence_policy,
        "observation_budget": observation_budget,
    }


def json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the hash-lockable Claim 180 deficit supplement plan."
    )
    parser.add_argument("--base-preregistration", type=Path, required=True)
    parser.add_argument("--base-collection", type=Path, required=True)
    parser.add_argument("--base-inventory", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--targets", type=Path, required=True)
    parser.add_argument("--actions-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol-repository", required=True)
    parser.add_argument("--protocol-revision", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    payload = build_plan(
        base_preregistration_path=args.base_preregistration,
        base_collection_path=args.base_collection,
        base_inventory_path=args.base_inventory,
        sources_path=args.sources,
        targets_path=args.targets,
        actions_manifest_path=args.actions_manifest,
        output_path=args.output,
        protocol_repository=args.protocol_repository,
        protocol_revision=args.protocol_revision,
    )
    content = json_text(payload)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != content:
            raise RuntimeError("supplement plan is stale or missing")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    print(
        json.dumps(
            {
                "candidate_count": len(payload["case_ids"]),
                "category_targets": payload["category_targets"],
                "protocol_revision": payload["protocol_revision"],
                "check": args.check,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
