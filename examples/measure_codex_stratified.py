from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
import time
from collections import defaultdict
from pathlib import Path
from typing import Any


CATEGORIES = (
    "small_ui",
    "action_success",
    "action_failure",
    "popup_notification",
    "loading_completion",
    "scroll_navigation",
    "cursor_hover_focus",
    "animation_game_hud",
    "transient_event",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a stratified saved-evidence sample through one Codex batch."
    )
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--codex-command", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--method", choices=("signum", "uniform"), default="signum")
    parser.add_argument("--per-category", type=int, default=2)
    parser.add_argument("--timeout", type=float, default=240.0)
    return parser.parse_args()


def output_schema(count: int) -> dict[str, Any]:
    properties = {
        "sample_id": {"type": "string"},
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


def choose_samples(evaluation: dict[str, Any], method: str, per_category: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    counts: defaultdict[str, int] = defaultdict(int)
    used_transitions: set[str] = set()
    for category in CATEGORIES:
        for case in evaluation["cases"]:
            events = {event["id"]: event for event in case["events"]}
            matches = case["methods"][method]["matches"]
            for match in matches:
                event = events[match["event_id"]]
                if counts[category] >= per_category:
                    break
                if event["category"] != category or not match["triggered"]:
                    continue
                if not event.get("real_world_eligible", True):
                    continue
                transition = event.get("source_transition_id") or (
                    f"{case['id']}/{event['id']}"
                )
                if transition in used_transitions:
                    continue
                selected.append(
                    {
                        "sample_id": f"{case['id']}::{event['id']}",
                        "case": case,
                        "event": event,
                        "match": match,
                    }
                )
                used_transitions.add(transition)
                counts[category] += 1
            if counts[category] >= per_category:
                break
    deficits = {
        category: per_category - counts[category]
        for category in CATEGORIES
        if counts[category] < per_category
    }
    if deficits:
        raise RuntimeError(f"could not create stratified sample: {deficits}")
    return selected


def load_observation(root: Path, sample: dict[str, Any], method: str) -> dict[str, Any]:
    case = sample["case"]
    observation_path = root / case["methods"][method]["observation_file"]
    payload = json.loads(observation_path.read_text(encoding="utf-8"))
    sequence = sample["match"]["matched_sequence"]
    for observation in payload["observations"]:
        if observation["event"]["sequence"] == sequence:
            return observation
    raise RuntimeError(f"matched observation was not found: {sample['sample_id']}")


def build_prompt(samples: list[dict[str, Any]], attachments: list[tuple[str, str]]) -> str:
    mapped: defaultdict[str, list[str]] = defaultdict(list)
    for index, (sample_id, role) in enumerate(attachments):
        mapped[sample_id].append(f"attachment {index}: {role}")
    rows = []
    for sample in samples:
        sample_id = sample["sample_id"]
        event = sample["observation"]["event"]
        action = event.get("action")
        action_text = (
            "Set verification to not_applicable."
            if action is None
            else (
                f"Action performed: {action}. Expected visible result: {event.get('expected_result')}. "
                "Use confirmed only with visible support, not_confirmed when contradicted "
                "or unchanged, and uncertain when evidence is insufficient."
            )
        )
        rows.append(
            "\n".join(
                [
                    f"Sample id: {sample_id}",
                    f"Goal: {sample['case']['goal']}",
                    f"Images: {', '.join(mapped[sample_id])}",
                    f"Reason: {event['reason']}; discovery: {event['discovery']}",
                    f"Changed fraction: {float(event['change_fraction']):.8f}",
                    f"Changed region: {json.dumps(event.get('region'), sort_keys=True)}",
                    action_text,
                ]
            )
        )
    return (
        "Act only as a visual observer for a computer-use agent. Do not use tools or "
        "perform the task. Each sample is independent. Inspect only its mapped images, "
        "report visible facts, and never infer action success from the requested goal. "
        "A before_action image precedes an action, context is the current screen, detail "
        "is the changed region, and change_peak preserves a brief transition. Return one "
        "observation per sample in the listed order and copy sample_id exactly.\n\n"
        + "\n\n".join(rows)
    )


def parse_usage(stdout: str) -> dict[str, int | None]:
    result: dict[str, int | None] = {
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
            usage = event.get("usage")
            if isinstance(usage, dict):
                result = {key: usage.get(key) for key in result}
    return result


def main() -> None:
    args = parse_args()
    evaluation_path = args.evaluation.resolve()
    root = evaluation_path.parent
    evaluation = json.loads(evaluation_path.read_text(encoding="utf-8"))
    samples = choose_samples(evaluation, args.method, args.per_category)
    attachments: list[tuple[str, str]] = []
    image_paths: list[Path] = []
    for sample in samples:
        observation = load_observation(root, sample, args.method)
        sample["observation"] = observation
        event = observation["event"]
        observation_root = root / sample["case"]["methods"][args.method]["observation_file"]
        observation_root = observation_root.parent
        for image, relative in zip(event["images"], event["image_files"], strict=True):
            image_path = observation_root / relative
            if not image_path.is_file():
                raise RuntimeError(f"missing saved evidence: {image_path}")
            attachments.append((sample["sample_id"], image["role"]))
            image_paths.append(image_path.resolve())

    args.output.mkdir(parents=True, exist_ok=True)
    wall_started = time.perf_counter()
    with tempfile.TemporaryDirectory(prefix="signum-stratified-") as temp_name:
        temp = Path(temp_name)
        schema_path = temp / "schema.json"
        output_path = temp / "observations.json"
        schema_path.write_text(json.dumps(output_schema(len(samples))), encoding="utf-8")
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
        for image_path in image_paths:
            command.extend(["--image", str(image_path)])
        command.append("-")
        started = time.perf_counter()
        completed = subprocess.run(
            command,
            input=build_prompt(samples, attachments),
            cwd=temp,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            check=False,
        )
        latency = time.perf_counter() - started
        if completed.returncode != 0:
            raise RuntimeError((completed.stderr or completed.stdout)[:1200])
        observations = json.loads(output_path.read_text(encoding="utf-8"))["observations"]
        usage = parse_usage(completed.stdout)

    expected_ids = [sample["sample_id"] for sample in samples]
    actual_ids = [row.get("sample_id") for row in observations]
    if actual_ids != expected_ids:
        raise RuntimeError("Codex did not preserve the stratified sample order")
    labels = {
        sample["sample_id"]: {
            "category": sample["event"]["category"],
            "risk": sample["event"]["risk"],
            "acceptable_states": sample["event"]["acceptable_states"],
            "notes": sample["event"]["notes"],
        }
        for sample in samples
    }
    report = {
        "schema_version": 1,
        "evaluation": str(evaluation_path),
        "method": args.method,
        "selection": "two eligible independent transitions per Pilot60 category",
        "model": args.model,
        "calls": 1,
        "events": len(samples),
        "latency_seconds": latency,
        "wall_seconds": time.perf_counter() - wall_started,
        "usage": usage,
        "reported_total_tokens": int(usage["input_tokens"] or 0) + int(usage["output_tokens"] or 0),
        "observations": observations,
    }
    (args.output / "measurement.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    review = {
        "schema_version": 1,
        "reviewer": "",
        "review_method": "human_blind",
        "instructions": "Judge the observation against the saved evidence without changing the model output.",
        "reviews": [
            {
                "sample_id": row["sample_id"],
                "label": labels[row["sample_id"]],
                "observation": row,
                "evidence_visible": None,
                "semantic_correct": None,
                "task_state_correct": None,
                "false_confirmation": None if labels[row["sample_id"]]["category"] == "action_failure" else False,
                "review_notes": "",
            }
            for row in observations
        ],
    }
    (args.output / "review-template.json").write_text(
        json.dumps(review, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"calls": 1, "events": len(samples), "latency_seconds": latency, "reported_total_tokens": report["reported_total_tokens"], "usage": usage}, sort_keys=True))


if __name__ == "__main__":
    main()
