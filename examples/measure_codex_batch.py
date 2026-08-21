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
        description="Interpret saved Signum evidence in one structured Codex batch."
    )
    parser.add_argument("--probe", type=Path, required=True)
    parser.add_argument("--prepared", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--codex-command", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--timeout", type=float, default=180.0)
    return parser.parse_args()


def observation_properties() -> dict[str, Any]:
    return {
        "sequence": {"type": "integer"},
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
    }


def batch_schema(count: int) -> dict[str, Any]:
    properties = observation_properties()
    return {
        "type": "object",
        "properties": {
            "observations": {
                "type": "array",
                "minItems": count,
                "maxItems": count,
                "items": {
                    "type": "object",
                    "properties": properties,
                    "required": list(properties),
                    "additionalProperties": False,
                },
            }
        },
        "required": ["observations"],
        "additionalProperties": False,
    }


def build_prompt(events: list[dict[str, Any]], attachments: list[tuple[int, str]]) -> str:
    attachment_map: dict[int, list[str]] = {}
    for index, (sequence, role) in enumerate(attachments):
        attachment_map.setdefault(sequence, []).append(f"attachment {index}: {role}")
    rows = []
    for event in events:
        action = event.get("action")
        verification = (
            "Set verification to not_applicable."
            if action is None
            else (
                f"Action: {action}. Expected visible result: {event.get('expected_result')}. "
                "Use confirmed only with visible support, not_confirmed when contradicted "
                "or unchanged, and uncertain when evidence is insufficient."
            )
        )
        rows.append(
            "\n".join(
                [
                    f"Sequence {event['sequence']}",
                    f"Images: {', '.join(attachment_map[event['sequence']])}",
                    f"Reason: {event['reason']}; discovery: {event['discovery']}",
                    f"Changed fraction: {float(event['change_fraction']):.8f}",
                    f"Timestamp: {float(event['timestamp']):.3f}; peak: {event.get('peak_timestamp')}",
                    f"Changed region: {json.dumps(event.get('region'), sort_keys=True)}",
                    verification,
                ]
            )
        )
    return (
        "Act only as a visual observer for a computer-use agent. Do not use tools, "
        "inspect files other than the attached images, or perform the task. The events "
        "below are chronological but must each receive an independent structured verdict. "
        "A before_action image is before an action; context is the current screen; detail "
        "is the changed region. Do not claim success or completion without visible evidence. "
        "Return exactly one observation for every listed sequence in the same order.\n\n"
        f"Goal: {GOAL}\n\n" + "\n\n".join(rows)
    )


def parse_usage(stdout: str) -> dict[str, int | None]:
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
        if isinstance(event, dict) and event.get("type") == "turn.completed":
            raw = event.get("usage")
            if isinstance(raw, dict):
                usage = {key: raw.get(key) for key in usage}
    return usage


def main() -> None:
    args = parse_args()
    probe = json.loads(args.probe.read_text(encoding="utf-8"))
    events = [row["event"] for row in probe["results"]]
    args.output.mkdir(parents=True, exist_ok=True)
    attachments: list[tuple[int, str]] = []
    image_paths: list[Path] = []
    for event in events:
        for image in event["images"]:
            path = args.prepared / f"event-{event['sequence']}-{image['role']}.jpg"
            if not path.is_file():
                raise RuntimeError(f"missing prepared evidence: {path}")
            attachments.append((int(event["sequence"]), str(image["role"])))
            image_paths.append(path.resolve())

    wall_started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="signum-batch-measure-") as temp_name:
        root = Path(temp_name)
        schema_path = root / "schema.json"
        output_path = root / "observations.json"
        schema_path.write_text(json.dumps(batch_schema(len(events))), encoding="utf-8")
        command = [
            args.codex_command,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--json",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
            "--model",
            args.model,
        ]
        for path in image_paths:
            command.extend(["--image", str(path)])
        command.append("-")
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            input=build_prompt(events, attachments),
            cwd=root,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            check=False,
        )
        latency = time.perf_counter() - started
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout)[:1200])
        output = json.loads(output_path.read_text(encoding="utf-8"))
        usage = parse_usage(completed.stdout)

    observations = output.get("observations")
    if not isinstance(observations, list) or len(observations) != len(events):
        raise RuntimeError("Codex batch output did not contain one row per event")
    report = {
        "schema_version": 1,
        "transport": "single_ephemeral_batch",
        "model": args.model,
        "probe": str(args.probe.resolve()),
        "calls": 1,
        "events": len(events),
        "latency_seconds": latency,
        "wall_seconds": time.perf_counter() - wall_started,
        "usage": usage,
        "reported_total_tokens": (
            int(usage["input_tokens"] or 0) + int(usage["output_tokens"] or 0)
        ),
        "observations": observations,
    }
    destination = args.output / "measurement.json"
    destination.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("calls", "events", "latency_seconds", "reported_total_tokens", "usage")}, sort_keys=True))


if __name__ == "__main__":
    main()
