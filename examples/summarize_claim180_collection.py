from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_identity(path: Path, relative_to: Path) -> dict[str, Any]:
    return {
        "path": path.resolve().relative_to(relative_to.resolve()).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def read_object(path: Path, kind: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise RuntimeError(f"{kind} is missing: {path}") from error
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{kind} is invalid JSON: {path}: {error}") from error
    if not isinstance(payload, dict):
        raise RuntimeError(f"{kind} must contain an object: {path}")
    return payload


def summarize_case(case_id: str, root: Path) -> dict[str, Any]:
    case_root = root / case_id
    capture_path = case_root / "capture.json"
    failure_path = case_root / "failure.json"
    if failure_path.is_file() and not capture_path.is_file():
        failure = read_object(failure_path, f"failure for {case_id}")
        return {
            "case_id": case_id,
            "collection_status": "startup_failed",
            "eligible_for_claim": False,
            "failure_type": failure.get("failure_type"),
            "failure": failure.get("failure"),
            "failure_artifact": file_identity(failure_path, root),
        }
    if not capture_path.is_file():
        return {
            "case_id": case_id,
            "collection_status": "missing",
            "eligible_for_claim": False,
            "failure": "neither capture.json nor failure.json exists",
        }
    verification_path = case_root / "verification.json"
    capture = read_object(capture_path, f"capture for {case_id}")
    verification = read_object(verification_path, f"verification for {case_id}")
    if capture.get("case_id") != case_id or verification.get("case_id") != case_id:
        raise RuntimeError(f"case identity mismatch for {case_id}")
    actions = capture.get("actions")
    if not isinstance(actions, list):
        raise RuntimeError(f"capture actions must be an array for {case_id}")
    failed_actions = [
        {
            "id": action.get("id"),
            "required": action.get("required", True),
            "expected_outcome": action.get("expected_outcome"),
            "failure_type": action.get("failure_type"),
            "failure": action.get("failure"),
        }
        for action in actions
        if isinstance(action, dict) and action.get("status") == "failed"
    ]
    statistics = verification.get("recomputed_statistics")
    if not isinstance(statistics, dict):
        raise RuntimeError(f"verification has no recomputed statistics for {case_id}")
    valid = verification.get("valid") is True
    action_spec = capture.get("action_spec", {})
    browser = capture.get("browser", {})
    return {
        "case_id": case_id,
        "collection_status": "valid" if valid else "invalid",
        "eligible_for_claim": valid,
        "captured_at_utc": capture.get("captured_at_utc"),
        "source_url": capture.get("source_url"),
        "final_url": capture.get("navigation", {}).get("final_url"),
        "capture_artifact": file_identity(capture_path, root),
        "verification_artifact": file_identity(verification_path, root),
        "action_spec": {
            key: action_spec.get(key) for key in ("path", "bytes", "sha256")
        },
        "browser": {
            key: browser.get(key)
            for key in (
                "executable_bytes",
                "executable_sha256",
                "version",
                "playwright_version",
                "node_version",
                "platform",
                "architecture",
                "headless",
            )
        },
        "statistics": statistics,
        "integrity_valid": verification.get("integrity_valid") is True,
        "policy_valid": verification.get("policy_valid") is True,
        "policy_reasons": verification.get("policy_reasons", []),
        "required_action_failures": verification.get(
            "required_action_failures", []
        ),
        "failed_actions": failed_actions,
    }


def build_summary(
    root: Path,
    plan_path: Path,
    preregistration_path: Path,
) -> dict[str, Any]:
    plan = read_object(plan_path, "Claim 180 plan")
    preregistration = read_object(preregistration_path, "Claim 180 preregistration")
    case_ids = plan.get("case_ids")
    if not isinstance(case_ids, list) or any(
        not isinstance(case_id, str) for case_id in case_ids
    ):
        raise RuntimeError("plan case_ids must be strings")
    if preregistration.get("case_ids") != case_ids:
        raise RuntimeError("preregistration case ids differ from the plan")
    cases = [summarize_case(case_id, root) for case_id in case_ids]
    counts = {
        status: sum(row["collection_status"] == status for row in cases)
        for status in ("valid", "invalid", "startup_failed", "missing")
    }
    unexpected = sorted(
        path.name for path in root.iterdir() if path.is_dir() and path.name not in case_ids
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "kind": "signum_claim180_collection_summary",
        "generated_at_utc": datetime.now(UTC).isoformat(),
        "preregistration_id": preregistration.get("preregistration_id"),
        "plan": {
            "path": plan_path.name,
            "bytes": plan_path.stat().st_size,
            "sha256": sha256_file(plan_path),
        },
        "preregistration": {
            "path": preregistration_path.name,
            "bytes": preregistration_path.stat().st_size,
            "sha256": sha256_file(preregistration_path),
        },
        "counts": counts,
        "claim180_collection_complete": counts == {
            "valid": len(case_ids),
            "invalid": 0,
            "startup_failed": 0,
            "missing": 0,
        },
        "unexpected_case_directories": unexpected,
        "cases": cases,
    }
    canonical = json.dumps(
        {key: value for key, value in payload.items() if key != "generated_at_utc"},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    payload["collection_id"] = hashlib.sha256(canonical).hexdigest()
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Summarize a one-shot Claim 180 browser collection without replacing failures."
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--preregistration", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise RuntimeError(f"refusing to overwrite collection summary: {args.output}")
    payload = build_summary(
        args.root.resolve(),
        args.plan.resolve(),
        args.preregistration.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "counts": payload["counts"],
                "collection_complete": payload["claim180_collection_complete"],
                "collection_id": payload["collection_id"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
