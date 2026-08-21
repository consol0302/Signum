from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


EXPECTED_DOMAINS = {
    "playwrightlab.github.io": 20,
    "qapracticehub.com": 20,
    "testpages.eviltester.com": 20,
}


def read_object(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must contain a JSON object")
    return payload


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_reference(path: Path, output: Path) -> dict[str, Any]:
    return {
        "path": Path(
            os.path.relpath(path.resolve(), output.parent.resolve())
        ).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def immutable_revision(value: str, label: str) -> str:
    if len(value) not in {40, 64} or any(
        character not in "0123456789abcdefABCDEF" for character in value
    ):
        raise RuntimeError(f"{label} must be a full immutable hash")
    return value.lower()


def build_plan(
    template_path: Path,
    sources_path: Path,
    actions_manifest_path: Path,
    output_path: Path,
    protocol_revision: str,
) -> dict[str, Any]:
    template = read_object(template_path, "Claim 180 template")
    sources = read_object(sources_path, "v4 candidate sources")
    actions_manifest = read_object(actions_manifest_path, "v4 actions manifest")
    protocol_revision = immutable_revision(protocol_revision, "protocol revision")

    if sources.get("kind") != "signum_claim180_v4_candidate_sources":
        raise RuntimeError("v4 sources have the wrong kind")
    if actions_manifest.get("kind") != "signum_claim180_browser_actions":
        raise RuntimeError("v4 actions manifest has the wrong kind")
    collector_revision = immutable_revision(
        str(actions_manifest.get("collector_revision", "")),
        "collector revision",
    )
    case_ids = sources.get("case_ids")
    slots = sources.get("slots")
    workflow_sources = sources.get("workflow_sources")
    target_events = sources.get("target_events")
    if (
        not isinstance(case_ids, list)
        or len(case_ids) != 60
        or len(case_ids) != len(set(case_ids))
        or not isinstance(slots, list)
        or len(slots) != 30
        or not isinstance(workflow_sources, list)
        or [row.get("case_id") for row in workflow_sources] != case_ids
        or not isinstance(target_events, list)
        or [row.get("case_id") for row in target_events] != case_ids
    ):
        raise RuntimeError("v4 sources must contain 60 ordered candidates in 30 slots")
    flattened = []
    slot_ids = []
    target_by_id = {row.get("case_id"): row for row in target_events}
    category_totals: Counter[str] = Counter()
    for slot in slots:
        if not isinstance(slot, dict):
            raise RuntimeError("v4 slots must be objects")
        slot_id = slot.get("slot_id")
        candidates = slot.get("candidate_ids")
        if (
            not isinstance(slot_id, str)
            or not slot_id
            or slot_id in slot_ids
            or not isinstance(candidates, list)
            or len(candidates) != 2
            or len(set(candidates)) != 2
        ):
            raise RuntimeError("each v4 slot must bind two unique candidates")
        slot_ids.append(slot_id)
        flattened.extend(candidates)
        rows = [target_by_id.get(case_id) for case_id in candidates]
        if any(not isinstance(row, dict) for row in rows):
            raise RuntimeError("v4 slot candidate is missing target events")
        templates = [
            [event.get("category") for event in row.get("events", [])]
            for row in rows
        ]
        if (
            any(row.get("slot_id") != slot_id for row in rows)
            or len(templates[0]) != 6
            or templates[0] != templates[1]
        ):
            raise RuntimeError("v4 slot candidates must share one six-event template")
        category_totals.update(templates[0])
    if flattened != case_ids:
        raise RuntimeError("v4 flattened slot order must match case_ids")
    if dict(category_totals) != template.get("category_targets"):
        raise RuntimeError("v4 slot templates do not exactly equal CLAIM180 targets")

    domains = Counter(urlparse(row.get("url", "")).netloc for row in workflow_sources)
    if dict(domains) != EXPECTED_DOMAINS:
        raise RuntimeError("v4 sources do not preserve the frozen fresh-domain balance")
    manifest_ids = [
        row.get("case_id")
        for row in actions_manifest.get("cases", [])
        if isinstance(row, dict)
    ]
    if (
        manifest_ids != case_ids
        or actions_manifest.get("candidate_count") != 60
        or actions_manifest.get("slot_count") != 30
    ):
        raise RuntimeError("v4 actions manifest differs from the source catalog")
    source_reference = actions_manifest.get("source_catalog")
    if not isinstance(source_reference, dict):
        raise RuntimeError("v4 actions manifest is missing its source catalog lock")
    referenced_source = (
        actions_manifest_path.parent / str(source_reference.get("path", ""))
    ).resolve()
    if (
        referenced_source != sources_path.resolve()
        or source_reference.get("bytes") != sources_path.stat().st_size
        or source_reference.get("sha256") != sha256_file(sources_path)
    ):
        raise RuntimeError("v4 actions manifest source catalog lock does not match")

    evidence_policy = json.loads(json.dumps(template.get("evidence_policy")))
    observation_budget = json.loads(json.dumps(template.get("observation_budget")))
    if not isinstance(evidence_policy, dict) or not evidence_policy:
        raise RuntimeError("template has no evidence policy")
    if not isinstance(observation_budget, dict) or not observation_budget:
        raise RuntimeError("template has no observation budget")
    capture_policy = evidence_policy.get("capture")
    if not isinstance(capture_policy, dict):
        raise RuntimeError("template evidence policy has no capture policy")
    capture_policy.update(
        {
            "maximum_retained_frame_gap_seconds": 0.75,
            "per_screenshot_timeout_ms": 200,
            "screenshot_attempt_errors_preserved": True,
            "full_duration_endpoint_coverage_required": True,
            "target_post_action_frame_required": True,
        }
    )

    return {
        "schema_version": 1,
        "protocol_id": "signum-claim180-public-web-v4",
        "protocol_repository": template["protocol_repository"],
        "protocol_revision": protocol_revision,
        "collector_revision": collector_revision,
        "supersedes_preregistration_id": (
            "bef6d49c3090daab2f06278875ecbee68508b767d7ffaa5e390b7416ea760470"
        ),
        "development_only_predecessors": [
            "claim180-v3",
            "claim180-deficit-supplement-v1",
            "claim180-composite-v1",
        ],
        "candidate_source_catalog": relative_reference(sources_path, output_path),
        "actions_manifest": relative_reference(actions_manifest_path, output_path),
        "case_ids": case_ids,
        "category_targets": template["category_targets"],
        "workflow_sources": workflow_sources,
        "target_events": target_events,
        "collection_selection": {
            "mode": "first_valid_per_slot_in_plan_order",
            "validity_source": "independent_capture_verification",
            "retain_all_attempts": True,
            "model_outputs_forbidden_before_selection": True,
            "required_valid_cases": 30,
            "candidate_count": 60,
            "slots": slots,
        },
        "evidence_policy": evidence_policy,
        "observation_budget": observation_budget,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the balanced, action-bound Claim 180 v4 plan."
    )
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--actions-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--protocol-revision", required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    plan = build_plan(
        args.template,
        args.sources,
        args.actions_manifest,
        args.output,
        args.protocol_revision,
    )
    content = json_text(plan)
    if args.check:
        if not args.output.is_file() or args.output.read_text(encoding="utf-8") != content:
            raise RuntimeError("v4 plan is stale or missing")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(content, encoding="utf-8")
    print(
        json.dumps(
            {
                "candidates": len(plan["case_ids"]),
                "slots": len(plan["collection_selection"]["slots"]),
                "collector_revision": plan["collector_revision"],
                "protocol_revision": plan["protocol_revision"],
                "check": args.check,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
