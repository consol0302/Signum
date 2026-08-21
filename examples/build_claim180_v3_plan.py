from __future__ import annotations

import argparse
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


def json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def build_plan(
    template_path: Path,
    sources_path: Path,
    actions_manifest_path: Path,
    protocol_revision: str,
) -> dict[str, Any]:
    template = read_object(template_path)
    sources = read_object(sources_path)
    actions_manifest = read_object(actions_manifest_path)
    case_ids = sources.get("case_ids")
    workflow_sources = sources.get("workflow_sources")
    if (
        not isinstance(case_ids, list)
        or len(case_ids) != 45
        or not isinstance(workflow_sources, list)
        or [row.get("case_id") for row in workflow_sources] != case_ids
    ):
        raise RuntimeError("v3 source catalog must contain 45 ordered candidates")
    if [row.get("case_id") for row in actions_manifest.get("cases", [])] != case_ids:
        raise RuntimeError("v3 action manifest differs from the source catalog")
    return {
        "schema_version": 1,
        "protocol_id": "signum-claim180-public-web-v3",
        "protocol_repository": template["protocol_repository"],
        "protocol_revision": protocol_revision,
        "supersedes_preregistration_id": (
            "db988e9ae6de8bbc90f5c058df00ddc0f1599a7258d3049f7d7bd3a4caf10cab"
        ),
        "failed_predecessor_collection_id": (
            "f6ab76db72c0f8cb565cd84eba79b31f6283acaf05f85c29ba5ee1d103293877"
        ),
        "actions_manifest": {
            "path": actions_manifest_path.name,
            "bytes": actions_manifest_path.stat().st_size,
            "sha256": sha256_file(actions_manifest_path),
        },
        "case_ids": case_ids,
        "category_targets": template["category_targets"],
        "evidence_policy": template["evidence_policy"],
        "observation_budget": template["observation_budget"],
        "workflow_sources": workflow_sources,
        "collection_selection": {
            "mode": "first_valid_in_plan_order",
            "validity_source": "independent_capture_verification",
            "retain_all_attempts": True,
            "model_outputs_forbidden_before_selection": True,
            "required_valid_cases": 30,
            "candidate_count": 45,
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the action-bound ordered Claim 180 v3 plan."
    )
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--actions-manifest", type=Path, required=True)
    parser.add_argument("--protocol-revision", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    if len(args.protocol_revision) not in {40, 64} or any(
        character not in "0123456789abcdefABCDEF"
        for character in args.protocol_revision
    ):
        raise RuntimeError("protocol revision must be a full immutable hash")
    plan = build_plan(
        args.template,
        args.sources,
        args.actions_manifest,
        args.protocol_revision,
    )
    content = json_text(plan)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != content:
            raise RuntimeError("v3 plan is stale or missing")
    else:
        args.output.write_text(content, encoding="utf-8")
    print(
        json.dumps(
            {
                "candidates": len(plan["case_ids"]),
                "required_valid_cases": plan["collection_selection"]["required_valid_cases"],
                "check": args.check,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
