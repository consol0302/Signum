from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
from typing import Any


COLLECTOR_REVISION = "b6025b84d4498c682a76273e8540c63032d8e83e"
TEMPLATES = (
    ("v4-reserve-slot-01", "v4r-01a-qah", "v4-07b-qah", "22-hover-feedback-button"),
    ("v4-reserve-slot-01", "v4r-01b-playlab", "v4-07a-playlab", "15-hover-tooltip"),
    ("v4-reserve-slot-01", "v4r-01c-qah", "v4-17a-qah", "21-hover-feedback-button"),
    ("v4-reserve-slot-01", "v4r-01d-playlab", "v4-18b-playlab", "12-hover-tooltip"),
    ("v4-reserve-slot-02", "v4r-02a-qah", "v4-08a-qah", "22-hover-feedback-button"),
    ("v4-reserve-slot-02", "v4r-02b-playlab", "v4-10a-playlab", "15-hover-tooltip"),
    ("v4-reserve-slot-02", "v4r-02c-qah", "v4-20a-qah", "21-hover-feedback-button"),
    ("v4-reserve-slot-02", "v4r-02d-playlab", "v4-19a-playlab", "12-hover-tooltip"),
)


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(
    source_actions: Path,
    actions_output: Path,
    sources_output: Path,
    manifest_output: Path,
    *,
    check: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, str]]:
    actions: dict[str, str] = {}
    slots: dict[str, list[str]] = {}
    targets = []
    workflows = []
    source_templates = []
    for slot_id, case_id, template_id, target_action_id in TEMPLATES:
        template_path = source_actions / f"{template_id}.json"
        payload = deepcopy(read_object(template_path))
        action = next(
            (
                row
                for row in payload.get("actions", [])
                if row.get("id") == target_action_id
            ),
            None,
        )
        if not isinstance(action, dict) or action.get("type") != "hover":
            raise RuntimeError(f"reserve target is not a hover action: {template_id}")
        payload["case_id"] = case_id
        payload["slot_id"] = slot_id
        payload["goal"] = (
            f"Collect one fresh visible hover/focus reserve event for {slot_id}."
        )
        payload["target_events"] = [
            {"action_id": target_action_id, "category": "cursor_hover_focus"}
        ]
        text = json_text(payload)
        actions[case_id] = text
        slots.setdefault(slot_id, []).append(case_id)
        targets.append(
            {
                "case_id": case_id,
                "slot_id": slot_id,
                "events": payload["target_events"],
            }
        )
        workflows.append(
            {
                "case_id": case_id,
                "slot_id": slot_id,
                "url": payload["source_url"],
                "goal": payload["goal"],
            }
        )
        source_templates.append(
            {
                "case_id": case_id,
                "development_template": template_id,
                "target_action_id": target_action_id,
            }
        )
    case_ids = [case_id for _, case_id, _, _ in TEMPLATES]
    source_catalog = {
        "schema_version": 1,
        "kind": "signum_claim180_v4_visibility_reserve_sources",
        "case_ids": case_ids,
        "slots": [
            {"slot_id": slot_id, "candidate_ids": candidate_ids}
            for slot_id, candidate_ids in slots.items()
        ],
        "target_events": targets,
        "workflow_sources": workflows,
        "development_templates": source_templates,
        "activation_deficit": {
            "category": "cursor_hover_focus",
            "count": 2,
            "v4_event_keys": [
                "v4-09a-testpages/15-hover-calculation-control",
                "v4-27a-testpages/15-hover-calculation-control",
            ],
        },
    }
    source_text = json_text(source_catalog)
    if check:
        if sources_output.read_text(encoding="utf-8") != source_text:
            raise RuntimeError("published reserve source catalog differs from builder")
    else:
        sources_output.parent.mkdir(parents=True, exist_ok=True)
        sources_output.write_text(source_text, encoding="utf-8")
        actions_output.mkdir(parents=True, exist_ok=True)
        for case_id, text in actions.items():
            (actions_output / f"{case_id}.json").write_text(text, encoding="utf-8")
    source_bytes = sources_output.stat().st_size
    source_sha256 = sha256_file(sources_output)
    cases = []
    for case_id in case_ids:
        action_path = actions_output / f"{case_id}.json"
        if check and action_path.read_text(encoding="utf-8") != actions[case_id]:
            raise RuntimeError(f"published reserve action differs: {case_id}")
        cases.append(
            {
                "case_id": case_id,
                "action_file": f"{actions_output.name}/{case_id}.json",
                "bytes": action_path.stat().st_size,
                "sha256": sha256_file(action_path),
            }
        )
    first = read_object(actions_output / f"{case_ids[0]}.json")
    manifest = {
        "schema_version": 1,
        "kind": "signum_claim180_browser_actions",
        "collector_revision": COLLECTOR_REVISION,
        "candidate_count": len(case_ids),
        "slot_count": len(slots),
        "capture_policy": first["capture_policy"],
        "source_catalog": {
            "path": sources_output.name,
            "bytes": source_bytes,
            "sha256": source_sha256,
        },
        "cases": cases,
    }
    manifest_text = json_text(manifest)
    if check:
        if manifest_output.read_text(encoding="utf-8") != manifest_text:
            raise RuntimeError("published reserve manifest differs from builder")
    else:
        manifest_output.write_text(manifest_text, encoding="utf-8")
    return source_catalog, manifest, actions


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build the fresh conditional V4 hover-visibility reserve."
    )
    parser.add_argument("--source-actions", type=Path, required=True)
    parser.add_argument("--actions", type=Path, required=True)
    parser.add_argument("--sources", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    sources, manifest, _ = build(
        args.source_actions.resolve(),
        args.actions.resolve(),
        args.sources.resolve(),
        args.manifest.resolve(),
        check=args.check,
    )
    print(
        json.dumps(
            {
                "candidates": manifest["candidate_count"],
                "slots": manifest["slot_count"],
                "deficit": sources["activation_deficit"],
                "check": args.check,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
