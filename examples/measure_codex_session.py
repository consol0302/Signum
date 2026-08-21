from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any


GOAL = (
    "Observe the dynamic web page. Identify when a red box appears, when a new "
    "text input appears beside the buttons, and verify visible results."
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay saved Signum evidence through one resumable Codex session."
    )
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--codex-command", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "state": {"type": "string"},
            "summary": {"type": "string"},
            "relevant": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "verification": {
                "type": "string",
                "enum": ["confirmed", "not_confirmed", "uncertain", "not_applicable"],
            },
            "recommended_action": {"type": "string"},
            "evidence": {"type": "array", "items": {"type": "string"}},
        },
        "required": [
            "state",
            "summary",
            "relevant",
            "confidence",
            "verification",
            "recommended_action",
            "evidence",
        ],
        "additionalProperties": False,
    }


def prompt(event: dict[str, Any], previous: dict[str, Any] | None) -> str:
    previous_text = (
        "No previous semantic observation."
        if previous is None
        else f"Previous state: {previous['state']}\nPrevious summary: {previous['summary']}"
    )
    region = event.get("region")
    region_text = (
        "No changed region was detected."
        if region is None
        else f"Changed region: {json.dumps(region, sort_keys=True)}"
    )
    action = event.get("action")
    action_text = (
        "This is not an action-verification event. Set verification to not_applicable."
        if action is None
        else (
            f"Action performed: {action}\n"
            f"Expected visible result: {event.get('expected_result')}\n"
            "Set verification to confirmed only when the expected result is visibly "
            "supported, not_confirmed when visible evidence contradicts it or the "
            "screen did not change as expected, and uncertain when the images are insufficient."
        )
    )
    roles = ", ".join(str(image["role"]) for image in event["images"])
    return (
        "Act only as a visual observer for a computer-use agent. Do not use tools, "
        "inspect files other than the attached images, or perform the task. Report "
        "only facts visible in the images. A before_action image shows the screen "
        "immediately before an action; a context image shows the current screen; "
        "a detail image is the current changed region; a change_peak image preserves "
        "the strongest earlier frame of a short transition. Do not claim success, "
        "failure, or completion without visible evidence. Return only the JSON object "
        "required by the supplied output schema.\n\n"
        f"Goal: {GOAL}\n"
        f"Event reason: {event['reason']}\n"
        f"Event discovery: {event['discovery']}\n"
        f"Measured changed fraction: {float(event['change_fraction']):.8f}\n"
        f"Event timestamp: {float(event['timestamp']):.3f}\n"
        f"Peak timestamp: {event.get('peak_timestamp')}\n"
        f"Image roles in attachment order: {roles}\n"
        f"{region_text}\n{action_text}\n{previous_text}"
    )


def parse_jsonl(stdout: str) -> tuple[str | None, dict[str, int | None]]:
    session_id = None
    usage: dict[str, int | None] = {
        "input_tokens": None,
        "cached_input_tokens": None,
        "output_tokens": None,
        "reasoning_output_tokens": None,
    }
    for line in stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, dict):
            continue
        if event.get("type") == "thread.started" and isinstance(event.get("thread_id"), str):
            session_id = event["thread_id"]
        if event.get("type") == "turn.completed" and isinstance(event.get("usage"), dict):
            raw = event["usage"]
            usage = {key: raw.get(key) for key in usage}
    return session_id, usage


def main() -> None:
    args = parse_args()
    probe = json.loads(args.probe.read_text(encoding="utf-8"))
    args.output.mkdir(parents=True, exist_ok=True)
    results: list[dict[str, Any]] = []
    previous = None
    session_id = None
    wall_started = time.perf_counter()

    with tempfile.TemporaryDirectory(prefix="signum-session-measure-") as temp_name:
        root = Path(temp_name)
        for index, source in enumerate(probe["results"]):
            event = source["event"]
            turn_dir = root / f"turn-{index:02d}"
            turn_dir.mkdir()
            schema_path = turn_dir / "schema.json"
            output_path = turn_dir / "observation.json"
            schema_path.write_text(json.dumps(schema()), encoding="utf-8")
            command = [args.codex_command, "exec"]
            if session_id is None:
                command.extend(
                    [
                        "--ignore-user-config",
                        "--sandbox",
                        "read-only",
                        "--skip-git-repo-check",
                        "--color",
                        "never",
                    ]
                )
            else:
                command.extend(
                    [
                        "resume",
                        "--ignore-user-config",
                        "--skip-git-repo-check",
                    ]
                )
            command.extend(
                [
                    "--json",
                    "--output-schema",
                    str(schema_path),
                    "--output-last-message",
                    str(output_path),
                    "--model",
                    args.model,
                ]
            )
            for image in event["images"]:
                image_path = args.prepared / f"event-{event['sequence']}-{image['role']}.jpg"
                if not image_path.is_file():
                    raise RuntimeError(f"missing prepared evidence: {image_path}")
                command.extend(["--image", str(image_path.resolve())])
            if session_id is not None:
                command.append(session_id)
            command.append("-")
            started = time.perf_counter()
            completed = subprocess.run(
                command,
                input=prompt(event, previous),
                cwd=root,
                capture_output=True,
                text=True,
                timeout=args.timeout,
                check=False,
            )
            latency = time.perf_counter() - started
            if completed.returncode != 0:
                raise RuntimeError(
                    f"Codex turn {index} failed: {(completed.stderr or completed.stdout)[:800]}"
                )
            reported_session, usage = parse_jsonl(completed.stdout)
            session_id = session_id or reported_session
            if session_id is None:
                raise RuntimeError("Codex did not report a resumable session id")
            observation = json.loads(output_path.read_text(encoding="utf-8"))
            previous = observation
            results.append(
                {
                    "sequence": event["sequence"],
                    "reason": event["reason"],
                    "latency_seconds": latency,
                    "usage": usage,
                    "observation": observation,
                }
            )

    totals = {
        key: sum(int(row["usage"].get(key) or 0) for row in results)
        for key in (
            "input_tokens",
            "cached_input_tokens",
            "output_tokens",
            "reasoning_output_tokens",
        )
    }
    report = {
        "schema_version": 1,
        "transport": "codex_exec_resume_session",
        "codex_command": args.codex_command,
        "model": args.model,
        "probe": str(args.probe.resolve()),
        "calls": len(results),
        "wall_seconds": time.perf_counter() - wall_started,
        "totals": totals,
        "reported_total_tokens": totals["input_tokens"] + totals["output_tokens"],
        "results": results,
    }
    destination = args.output / "measurement.json"
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("calls", "wall_seconds", "reported_total_tokens", "totals")}, sort_keys=True))


if __name__ == "__main__":
    main()
