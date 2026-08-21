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


def identity(path: Path) -> dict[str, Any]:
    return {
        "path": path.name,
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def build_lock(packet_root: Path) -> dict[str, Any]:
    packet_path = packet_root / "packet.json"
    mapping_path = packet_root / "mapping.json"
    packet = read_object(packet_path)
    mapping = read_object(mapping_path)
    if (
        packet.get("kind") != "signum_ground_truth_review_packet"
        or packet.get("method_outputs_included") is not False
        or packet.get("item_count") != 180
    ):
        raise RuntimeError("review packet is not a method-blind Claim 180 packet")
    if mapping.get("packet_id") != packet.get("packet_id"):
        raise RuntimeError("coordinator mapping belongs to a different packet")
    evidence_root = packet_root / "evidence"
    evidence_paths = sorted(evidence_root.glob("*.png"), key=lambda path: path.name)
    if len(evidence_paths) != 360:
        raise RuntimeError("review packet must contain 360 evidence images")
    expected_evidence = {
        item[key]
        for item in packet.get("items", [])
        for key in ("before_image", "after_image")
    }
    actual_evidence = {f"evidence/{path.name}" for path in evidence_paths}
    if expected_evidence != actual_evidence:
        raise RuntimeError("review packet evidence set differs from packet.json")
    evidence_manifest = [
        {
            "path": f"evidence/{path.name}",
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for path in evidence_paths
    ]
    evidence_digest = hashlib.sha256(
        json.dumps(
            evidence_manifest,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()
    reviewer_artifacts = []
    for reviewer in ("reviewer-a", "reviewer-b"):
        json_path = packet_root / f"{reviewer}.json"
        html_path = packet_root / f"{reviewer}.html"
        review = read_object(json_path)
        if review.get("packet_id") != packet.get("packet_id"):
            raise RuntimeError(f"{reviewer} template belongs to a different packet")
        reviewer_artifacts.append(
            {
                "reviewer_slot": reviewer,
                "json": identity(json_path),
                "html": identity(html_path),
            }
        )
    payload = {
        "schema_version": 1,
        "kind": "signum_ground_truth_review_packet_lock",
        "packet_id": packet["packet_id"],
        "method_outputs_included": False,
        "item_count": packet["item_count"],
        "packet": identity(packet_path),
        "coordinator_mapping": identity(mapping_path),
        "evidence": {
            "file_count": len(evidence_manifest),
            "manifest_sha256": evidence_digest,
            "total_bytes": sum(row["bytes"] for row in evidence_manifest),
        },
        "reviewer_templates": reviewer_artifacts,
    }
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    payload["lock_id"] = hashlib.sha256(canonical).hexdigest()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hash-lock a method-blind ground-truth review packet."
    )
    parser.add_argument("--packet-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite packet lock: {args.output}")
    payload = build_lock(args.packet_root.resolve())
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "lock_id": payload["lock_id"],
                "packet_id": payload["packet_id"],
                "evidence_files": payload["evidence"]["file_count"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
