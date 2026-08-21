from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import subprocess
from typing import Any


def read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def run_collection(
    manifest_path: Path,
    output_root: Path,
    collector_path: Path,
    node_path: Path,
    node_modules: Path,
    browser_path: Path,
    requested_case_ids: list[str],
) -> dict[str, Any]:
    manifest = read_object(manifest_path)
    rows = manifest.get("cases")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("actions manifest must contain cases")
    planned_ids = [row.get("case_id") for row in rows if isinstance(row, dict)]
    if len(planned_ids) != len(rows) or len(planned_ids) != len(set(planned_ids)):
        raise RuntimeError("actions manifest case ids are invalid")
    selected_ids = requested_case_ids or planned_ids
    if len(selected_ids) != len(set(selected_ids)):
        raise RuntimeError("requested case ids must be unique")
    unknown = [case_id for case_id in selected_ids if case_id not in planned_ids]
    if unknown:
        raise RuntimeError(f"requested case ids are not in the manifest: {unknown}")
    if output_root.exists() and any(output_root.iterdir()):
        raise RuntimeError(f"refusing to overwrite non-empty collection root: {output_root}")
    output_root.mkdir(parents=True, exist_ok=True)
    by_id = {row["case_id"]: row for row in rows}
    environment = os.environ.copy()
    environment["SIGNUM_NODE_MODULES"] = str(node_modules.resolve())
    results = []
    started_at = datetime.now(UTC).isoformat()
    for case_id in selected_ids:
        row = by_id[case_id]
        action_path = (manifest_path.parent / row["action_file"]).resolve()
        action_spec = read_object(action_path)
        policy = action_spec["capture_policy"]
        case_root = output_root / case_id
        command = [
            str(node_path.resolve()),
            str(collector_path.resolve()),
            "--url",
            action_spec["source_url"],
            "--case-id",
            case_id,
            "--goal",
            action_spec["goal"],
            "--output",
            str(case_root.resolve()),
            "--actions",
            str(action_path),
            "--browser-executable",
            str(browser_path.resolve()),
            "--fps",
            str(policy["requested_fps"]),
            "--duration",
            str(action_spec["duration_seconds"]),
            "--width",
            str(policy["width"]),
            "--height",
            str(policy["height"]),
            "--minimum-average-fps",
            str(policy["minimum_average_fps"]),
            "--maximum-gap-seconds",
            str(policy["maximum_gap_seconds"]),
        ]
        completed = subprocess.run(
            command,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        artifact = "capture.json" if (case_root / "capture.json").is_file() else "failure.json"
        if not (case_root / artifact).is_file():
            case_root.mkdir(parents=True, exist_ok=True)
            (case_root / "failure.json").write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "status": "failed",
                        "case_id": case_id,
                        "failed_at_utc": datetime.now(UTC).isoformat(),
                        "failure": "collector exited without a capture or failure artifact",
                        "exit_code": completed.returncode,
                        "stdout": completed.stdout,
                        "stderr": completed.stderr,
                    },
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )
            artifact = "failure.json"
        result = {
            "case_id": case_id,
            "exit_code": completed.returncode,
            "artifact": f"{case_id}/{artifact}",
            "stdout": completed.stdout.strip(),
            "stderr": completed.stderr.strip(),
        }
        results.append(result)
        print(json.dumps(result, sort_keys=True), flush=True)
    payload = {
        "schema_version": 1,
        "kind": "signum_browser_collection_run",
        "started_at_utc": started_at,
        "completed_at_utc": datetime.now(UTC).isoformat(),
        "manifest": str(manifest_path.resolve()),
        "collector": str(collector_path.resolve()),
        "attempted_case_ids": selected_ids,
        "results": results,
    }
    (output_root / "runner-result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run a frozen browser action collection sequentially without retries."
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--collector", type=Path, required=True)
    parser.add_argument("--node", type=Path, required=True)
    parser.add_argument("--node-modules", type=Path, required=True)
    parser.add_argument("--browser", type=Path, required=True)
    parser.add_argument("--case-id", action="append", default=[])
    args = parser.parse_args()
    payload = run_collection(
        args.manifest.resolve(),
        args.output.resolve(),
        args.collector.resolve(),
        args.node.resolve(),
        args.node_modules.resolve(),
        args.browser.resolve(),
        args.case_id,
    )
    failures = sum(row["exit_code"] != 0 for row in payload["results"])
    print(
        json.dumps(
            {"attempted": len(payload["results"]), "collector_failures": failures},
            sort_keys=True,
        )
    )
    raise SystemExit(1 if failures else 0)


if __name__ == "__main__":
    main()
