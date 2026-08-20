from __future__ import annotations

import json
import subprocess
import tempfile
import time
from collections.abc import Callable, Sequence
from pathlib import Path

from .gateway import PerceptionEvent, SemanticResult


class InterpreterError(RuntimeError):
    pass


CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


class CodexExecInterpreter:
    """Interpret gated screen events with an authenticated local Codex CLI."""

    def __init__(
        self,
        *,
        command: str = "codex",
        model: str | None = None,
        timeout_seconds: float = 120.0,
        runner: CommandRunner | None = None,
    ) -> None:
        if not command.strip():
            raise ValueError("command cannot be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self.command = command
        self.model = model
        self.timeout_seconds = timeout_seconds
        self._runner = runner or subprocess.run

    def interpret(
        self,
        event: PerceptionEvent,
        goal: str,
        previous: SemanticResult | None,
    ) -> SemanticResult:
        prompt = _build_prompt(event, goal, previous)
        started = time.perf_counter()
        with tempfile.TemporaryDirectory(prefix="signum-codex-") as temp_name:
            temp_dir = Path(temp_name)
            image_paths = _write_images(event, temp_dir)
            schema_path = temp_dir / "observation.schema.json"
            output_path = temp_dir / "observation.json"
            schema_path.write_text(
                json.dumps(_observation_schema(), indent=2, sort_keys=True),
                encoding="utf-8",
            )
            command = self.build_command(image_paths, schema_path, output_path)
            try:
                completed = self._runner(
                    command,
                    input=prompt,
                    cwd=temp_dir,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                    check=False,
                )
            except FileNotFoundError as error:
                raise InterpreterError(
                    f"Codex CLI was not found: {self.command!r}. Install it and run "
                    "`codex login` before using `signum observe`."
                ) from error
            except subprocess.TimeoutExpired as error:
                raise InterpreterError(
                    f"Codex did not finish within {self.timeout_seconds:g} seconds"
                ) from error
            except OSError as error:
                raise InterpreterError(f"Codex CLI could not start: {error}") from error

            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "no error output").strip()
                raise InterpreterError(
                    f"Codex exited with status {completed.returncode}: {detail[:800]}"
                )
            try:
                output_text = output_path.read_text(encoding="utf-8")
            except FileNotFoundError as error:
                raise InterpreterError(
                    "Codex completed without writing the structured observation"
                ) from error

        parsed = _parse_observation(output_text)
        return SemanticResult(
            **parsed,
            latency_seconds=time.perf_counter() - started,
        )

    def build_command(
        self,
        image_paths: Sequence[Path],
        schema_path: Path,
        output_path: Path,
    ) -> list[str]:
        command = [
            self.command,
            "exec",
            "--ephemeral",
            "--ignore-user-config",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--output-schema",
            str(schema_path),
            "--output-last-message",
            str(output_path),
        ]
        if self.model:
            command.extend(("--model", self.model))
        for image_path in image_paths:
            command.extend(("--image", str(image_path)))
        command.append("-")
        return command


def _write_images(event: PerceptionEvent, output: Path) -> list[Path]:
    paths: list[Path] = []
    for index, image in enumerate(event.images):
        path = output / f"{index:02d}-{image.role}.jpg"
        path.write_bytes(image.jpeg)
        paths.append(path)
    return paths


def _build_prompt(
    event: PerceptionEvent,
    goal: str,
    previous: SemanticResult | None,
) -> str:
    previous_text = (
        "No previous semantic observation."
        if previous is None
        else f"Previous state: {previous.state}\nPrevious summary: {previous.summary}"
    )
    region_text = (
        "No changed region was detected."
        if event.region is None
        else f"Changed region: {json.dumps(event.region.to_dict(), sort_keys=True)}"
    )
    action_text = (
        "This is not an action-verification event. Set verification to "
        "not_applicable."
        if event.action is None
        else (
            f"Action performed: {event.action}\n"
            f"Expected visible result: {event.expected_result}\n"
            "Set verification to confirmed only when the expected result is visibly "
            "supported, not_confirmed when visible evidence contradicts it or the "
            "screen did not change as expected, and uncertain when the images are "
            "insufficient."
        )
    )
    image_roles = ", ".join(image.role for image in event.images)
    return (
        "Act only as a visual observer for a computer-use agent. Do not use tools, "
        "inspect files other than the attached images, or perform the task. Report "
        "only facts visible in the images. A before_action image shows the screen "
        "immediately before an action; a context image shows the current screen; "
        "a detail image is the current changed region; a change_peak image preserves "
        "the strongest earlier frame of a short transition. Do not claim success, "
        "failure, or completion without visible evidence. Return only the JSON object "
        "required by the supplied output schema.\n\n"
        f"Goal: {goal}\n"
        f"Event reason: {event.reason}\n"
        f"Event discovery: {event.discovery}\n"
        f"Measured changed fraction: {event.change_fraction:.8f}\n"
        f"Event timestamp: {event.timestamp:.3f}\n"
        f"Peak timestamp: {event.peak_timestamp}\n"
        f"Image roles in attachment order: {image_roles}\n"
        f"{region_text}\n"
        f"{action_text}\n"
        f"{previous_text}"
    )


def _parse_observation(output_text: str) -> dict[str, object]:
    try:
        parsed = json.loads(output_text)
    except json.JSONDecodeError as error:
        raise InterpreterError("Codex returned invalid structured JSON") from error
    if not isinstance(parsed, dict):
        raise InterpreterError("Codex observation must be a JSON object")
    required = (
        "state",
        "summary",
        "relevant",
        "confidence",
        "verification",
        "recommended_action",
        "evidence",
    )
    missing = [key for key in required if key not in parsed]
    if missing:
        raise InterpreterError(
            f"Codex observation is missing fields: {', '.join(missing)}"
        )
    evidence = parsed["evidence"]
    if not isinstance(evidence, list):
        raise InterpreterError("Codex observation evidence must be an array")
    string_fields = ("state", "summary", "verification", "recommended_action")
    invalid_strings = [
        key for key in string_fields if not isinstance(parsed[key], str)
    ]
    if invalid_strings:
        raise InterpreterError(
            "Codex observation fields must be strings: "
            + ", ".join(invalid_strings)
        )
    if not isinstance(parsed["relevant"], bool):
        raise InterpreterError("Codex observation relevant must be boolean")
    if not all(isinstance(item, str) for item in evidence):
        raise InterpreterError("Codex observation evidence items must be strings")
    try:
        confidence = float(parsed["confidence"])
    except (TypeError, ValueError) as error:
        raise InterpreterError("Codex observation confidence must be numeric") from error
    if not 0 <= confidence <= 1:
        raise InterpreterError("Codex observation confidence must be between 0 and 1")
    verification = parsed["verification"]
    allowed_verifications = {
        "confirmed",
        "not_confirmed",
        "uncertain",
        "not_applicable",
    }
    if verification not in allowed_verifications:
        raise InterpreterError(f"unknown Codex verification result: {verification}")
    return {
        "state": parsed["state"],
        "summary": parsed["summary"],
        "relevant": parsed["relevant"],
        "confidence": confidence,
        "verification": verification,
        "recommended_action": parsed["recommended_action"],
        "evidence": tuple(evidence),
        "input_tokens": None,
        "output_tokens": None,
    }


def _observation_schema() -> dict[str, object]:
    return {
        "type": "object",
        "properties": {
            "state": {"type": "string"},
            "summary": {"type": "string"},
            "relevant": {"type": "boolean"},
            "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            "verification": {
                "type": "string",
                "enum": [
                    "confirmed",
                    "not_confirmed",
                    "uncertain",
                    "not_applicable",
                ],
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
