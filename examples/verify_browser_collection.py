from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path
from typing import Any


VERIFY_PATH = Path(__file__).with_name("verify_browser_capture.py")
SPEC = importlib.util.spec_from_file_location("verify_browser_capture", VERIFY_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {VERIFY_PATH}")
VERIFY_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(VERIFY_MODULE)


def read_object(path: Path, label: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{label} must contain an object")
    return payload


def verify_collection(root: Path, plan_path: Path) -> dict[str, Any]:
    plan = read_object(plan_path, "supplement plan")
    case_ids = plan.get("case_ids")
    if not isinstance(case_ids, list) or any(
        not isinstance(case_id, str) or not case_id for case_id in case_ids
    ):
        raise RuntimeError("supplement plan has invalid case ids")
    counts = {"valid": 0, "invalid": 0, "startup_failed": 0, "missing": 0}
    results = []
    for case_id in case_ids:
        case_root = root / case_id
        capture_path = case_root / "capture.json"
        failure_path = case_root / "failure.json"
        verification_path = case_root / "verification.json"
        if verification_path.exists():
            raise RuntimeError(f"refusing to overwrite verification: {verification_path}")
        if failure_path.is_file() and not capture_path.is_file():
            counts["startup_failed"] += 1
            results.append({"case_id": case_id, "status": "startup_failed"})
            continue
        if not capture_path.is_file():
            counts["missing"] += 1
            results.append({"case_id": case_id, "status": "missing"})
            continue
        try:
            report = VERIFY_MODULE.verify_capture(
                capture_path, expected_case_id=case_id
            )
        except Exception as error:  # preserve verifier failures as evidence
            report = {
                "schema_version": 1,
                "case_id": case_id,
                "valid": False,
                "integrity_valid": False,
                "policy_valid": False,
                "verification_error": f"{type(error).__name__}: {error}",
            }
        verification_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        status = "valid" if report.get("valid") is True else "invalid"
        counts[status] += 1
        results.append({"case_id": case_id, "status": status})
        print(json.dumps(results[-1], sort_keys=True), flush=True)
    return {"counts": counts, "results": results}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Independently verify every attempted browser capture in plan order."
    )
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    payload = verify_collection(args.root.resolve(), args.plan.resolve())
    print(json.dumps(payload["counts"], sort_keys=True))
    raise SystemExit(
        1
        if payload["counts"]["invalid"]
        or payload["counts"]["startup_failed"]
        or payload["counts"]["missing"]
        else 0
    )


if __name__ == "__main__":
    main()
