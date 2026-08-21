from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2

from measure_codex_stratified import CATEGORIES, output_schema
from provider_api_probe import estimate_cost


ENDPOINTS = {
    "openai": "https://api.openai.com/v1/responses",
    "anthropic": "https://api.anthropic.com/v1/messages",
}
KEY_ENVIRONMENTS = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


class ReplayError(RuntimeError):
    pass


class ReplayBudgetExceeded(ReplayError):
    pass


class ReplayPolicyViolation(ReplayError):
    pass


@dataclass(frozen=True)
class EvidenceFrame:
    path: Path
    role: str
    source_video: Path
    frame_index: int
    timestamp_seconds: float
    width: int
    height: int
    sha256: str
    encoded_bytes: int


class ReplayEnvironment:
    """A deterministic, non-executing computer screen used for perception replay."""

    def __init__(
        self,
        frames: list[EvidenceFrame],
        *,
        max_screenshots: int,
        max_zooms: int,
        output_dir: Path,
    ) -> None:
        if not frames:
            raise ReplayError("a replay requires at least one source frame")
        if max_screenshots <= 0 or max_zooms < 0:
            raise ReplayError("invalid screenshot or zoom budget")
        self.frames = frames
        self.max_screenshots = max_screenshots
        self.max_zooms = max_zooms
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.screenshot_count = 0
        self.zoom_count = 0
        self.next_frame_index = 0
        self.current_frame: EvidenceFrame | None = None
        self.trace: list[dict[str, Any]] = []

    @property
    def display_size(self) -> tuple[int, int]:
        return self.frames[0].width, self.frames[0].height

    def screenshot(self) -> tuple[bytes, dict[str, Any]]:
        if self.screenshot_count >= self.max_screenshots:
            raise ReplayBudgetExceeded("screenshot budget exhausted")
        repeated = self.next_frame_index >= len(self.frames)
        if not repeated:
            self.current_frame = self.frames[self.next_frame_index]
            self.next_frame_index += 1
        assert self.current_frame is not None
        self.screenshot_count += 1
        data = self.current_frame.path.read_bytes()
        record = {
            "sequence": len(self.trace),
            "action": "screenshot",
            "role": self.current_frame.role,
            "source_frame_index": self.current_frame.frame_index,
            "source_timestamp_seconds": self.current_frame.timestamp_seconds,
            "width": self.current_frame.width,
            "height": self.current_frame.height,
            "sha256": hashlib.sha256(data).hexdigest(),
            "encoded_bytes": len(data),
            "repeated": repeated,
        }
        self.trace.append(record)
        return data, record

    def zoom(self, region: list[int] | tuple[int, int, int, int]) -> tuple[bytes, dict[str, Any]]:
        if self.current_frame is None:
            raise ReplayPolicyViolation("zoom requested before a screenshot")
        if self.zoom_count >= self.max_zooms:
            raise ReplayBudgetExceeded("zoom budget exhausted")
        if not isinstance(region, (list, tuple)) or len(region) != 4:
            raise ReplayPolicyViolation("zoom region must be [x1, y1, x2, y2]")
        try:
            x1, y1, x2, y2 = (int(value) for value in region)
        except (TypeError, ValueError) as error:
            raise ReplayPolicyViolation("zoom coordinates must be integers") from error
        if not (
            0 <= x1 < x2 <= self.current_frame.width
            and 0 <= y1 < y2 <= self.current_frame.height
        ):
            raise ReplayPolicyViolation("zoom region is outside the current source frame")
        image = cv2.imread(str(self.current_frame.path), cv2.IMREAD_COLOR)
        if image is None:
            raise ReplayError(f"could not read source frame: {self.current_frame.path}")
        cropped = image[y1:y2, x1:x2]
        ok, encoded = cv2.imencode(".png", cropped)
        if not ok:
            raise ReplayError("could not encode zoom result")
        self.zoom_count += 1
        data = encoded.tobytes()
        destination = self.output_dir / f"zoom_{self.zoom_count:02d}.png"
        destination.write_bytes(data)
        record = {
            "sequence": len(self.trace),
            "action": "zoom",
            "region": [x1, y1, x2, y2],
            "role": self.current_frame.role,
            "source_frame_index": self.current_frame.frame_index,
            "source_timestamp_seconds": self.current_frame.timestamp_seconds,
            "width": x2 - x1,
            "height": y2 - y1,
            "sha256": hashlib.sha256(data).hexdigest(),
            "encoded_bytes": len(data),
            "artifact": str(destination.resolve()),
        }
        self.trace.append(record)
        return data, record


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay frozen source frames through a provider's native computer-use tool."
    )
    parser.add_argument("--provider", choices=tuple(ENDPOINTS), required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--evaluation", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--per-category", type=int, default=2)
    parser.add_argument("--case-id", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=240.0)
    parser.add_argument("--max-turns", type=int, default=6)
    parser.add_argument("--max-screenshots", type=int, default=3)
    parser.add_argument("--max-zooms", type=int, default=2)
    parser.add_argument("--endpoint")
    parser.add_argument("--input-usd-per-million", type=float)
    parser.add_argument("--output-usd-per-million", type=float)
    parser.add_argument("--cached-input-usd-per-million", type=float)
    parser.add_argument("--cache-write-usd-per-million", type=float)
    parser.add_argument("--pricing-source")
    parser.add_argument("--pricing-accessed-at")
    return parser.parse_args()


def _safe_name(value: str) -> str:
    return "".join(character if character.isalnum() or character in "-_." else "_" for character in value)


def _frame_requests(event: dict[str, Any]) -> list[tuple[str, float]]:
    if event.get("action") is not None:
        return [
            ("before_action", float(event["before_timestamp"])),
            ("after_action", float(event["after_timestamp"])),
        ]
    return [("labeled_event", (float(event["start"]) + float(event["end"])) / 2)]


def choose_frozen_events(
    evaluation: dict[str, Any],
    per_category: int,
    *,
    case_ids: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Select labels without consulting any candidate or baseline trigger result."""

    cases = evaluation.get("cases")
    if not isinstance(cases, list):
        raise ReplayError("evaluation does not contain cases")
    known = {case.get("id") for case in cases}
    if case_ids:
        missing = sorted(set(case_ids) - known)
        if missing:
            raise ReplayError(f"unknown requested cases: {missing}")
        ordered_cases = [next(case for case in cases if case.get("id") == case_id) for case_id in case_ids]
        categories: tuple[str, ...] | None = None
    else:
        if per_category <= 0:
            raise ReplayError("per-category must be positive")
        ordered_cases = cases
        categories = CATEGORIES

    selected: list[dict[str, Any]] = []
    used_transitions: set[str] = set()
    counts = {category: 0 for category in CATEGORIES}
    for category in categories or (None,):
        for case in ordered_cases:
            for event in case.get("events") or []:
                if event.get("real_world_eligible", True) is not True:
                    continue
                if category is not None and event.get("category") != category:
                    continue
                transition = event.get("source_transition_id") or f"{case['id']}/{event['id']}"
                if transition in used_transitions:
                    continue
                selected.append(
                    {
                        "sample_id": f"{case['id']}::{event['id']}",
                        "case": case,
                        "event": event,
                    }
                )
                used_transitions.add(transition)
                if category is not None:
                    counts[category] += 1
                    if counts[category] >= per_category:
                        break
            if category is not None and counts[category] >= per_category:
                break
    if categories is not None:
        deficits = {
            category: per_category - counts[category]
            for category in CATEGORIES
            if counts[category] < per_category
        }
        if deficits:
            raise ReplayError(f"could not create frozen stratified sample: {deficits}")
    if not selected:
        raise ReplayError("selection contains no eligible frozen events")
    return selected


def extract_source_frames(sample: dict[str, Any], destination: Path) -> list[EvidenceFrame]:
    video = Path(sample["case"]["video"]).resolve()
    capture = cv2.VideoCapture(str(video))
    if not capture.isOpened():
        raise ReplayError(f"could not open source video: {video}")
    try:
        fps = float(capture.get(cv2.CAP_PROP_FPS))
        count = int(capture.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(capture.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(capture.get(cv2.CAP_PROP_FRAME_HEIGHT))
        if fps <= 0 or count <= 0 or width <= 0 or height <= 0:
            raise ReplayError(f"invalid source video metadata: {video}")
        destination.mkdir(parents=True, exist_ok=True)
        frames: list[EvidenceFrame] = []
        for sequence, (role, timestamp) in enumerate(_frame_requests(sample["event"])):
            index = min(count - 1, max(0, int(round(timestamp * fps))))
            capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            ok, frame = capture.read()
            if not ok:
                raise ReplayError(f"could not decode frame {index} from {video}")
            actual_height, actual_width = frame.shape[:2]
            path = destination / f"{sequence:02d}_{role}_{index:09d}.png"
            if not cv2.imwrite(str(path), frame):
                raise ReplayError(f"could not write replay frame: {path}")
            data = path.read_bytes()
            frames.append(
                EvidenceFrame(
                    path=path.resolve(),
                    role=role,
                    source_video=video,
                    frame_index=index,
                    timestamp_seconds=index / fps,
                    width=actual_width,
                    height=actual_height,
                    sha256=hashlib.sha256(data).hexdigest(),
                    encoded_bytes=len(data),
                )
            )
        return frames
    finally:
        capture.release()


def build_prompt(sample: dict[str, Any]) -> str:
    event = sample["event"]
    action = event.get("action")
    verification = (
        "Set verification to not_applicable because no action is being verified."
        if action is None
        else (
            f"The action was: {action}. The expected visible result was: "
            f"{event.get('expected_result')}. Use confirmed only when the after screen visibly "
            "supports it, not_confirmed when it contradicts or is unchanged, and uncertain when "
            "the evidence is insufficient."
        )
    )
    return (
        "You are the perception layer of a computer-use agent in an inspect-only replay. "
        "Do not click, type, scroll, wait, or navigate. Request a screenshot to inspect each "
        "chronological source screen. The first screen is before the action and the second is "
        "after it when an action is present. You may request a documented zoom when the tool "
        "supports it. Do not infer success from the goal. Once evidence is sufficient, return "
        "the required JSON and copy sample_id exactly.\n\n"
        f"Sample id: {sample['sample_id']}\n"
        f"Goal: {sample['case']['goal']}\n"
        f"Label notes are intentionally hidden from you.\n{verification}"
    )


def _schema() -> dict[str, Any]:
    return output_schema(1)


def openai_initial_payload(model: str, prompt: str) -> dict[str, Any]:
    return {
        "model": model,
        "tools": [{"type": "computer"}],
        "input": prompt,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "signum_native_perception",
                "strict": True,
                "schema": _schema(),
            }
        },
    }


def openai_continuation_payload(
    model: str, previous_response_id: str, call_id: str, image: bytes
) -> dict[str, Any]:
    return {
        "model": model,
        "previous_response_id": previous_response_id,
        "tools": [{"type": "computer"}],
        "input": [
            {
                "type": "computer_call_output",
                "call_id": call_id,
                "output": {
                    "type": "computer_screenshot",
                    "image_url": "data:image/png;base64," + base64.b64encode(image).decode("ascii"),
                    "detail": "original",
                },
            }
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "signum_native_perception",
                "strict": True,
                "schema": _schema(),
            }
        },
    }


def anthropic_initial_payload(
    model: str, prompt: str, display_size: tuple[int, int]
) -> dict[str, Any]:
    width, height = display_size
    return {
        "model": model,
        "max_tokens": 8192,
        "messages": [{"role": "user", "content": prompt}],
        "tools": [
            {
                "type": "computer_20251124",
                "name": "computer",
                "display_width_px": width,
                "display_height_px": height,
                "enable_zoom": True,
            }
        ],
        "output_config": {"format": {"type": "json_schema", "schema": _schema()}},
    }


def anthropic_continuation_payload(
    payload: dict[str, Any], assistant_content: list[dict[str, Any]], results: list[dict[str, Any]]
) -> dict[str, Any]:
    next_payload = dict(payload)
    next_payload["messages"] = list(payload["messages"]) + [
        {"role": "assistant", "content": assistant_content},
        {"role": "user", "content": results},
    ]
    return next_payload


def request_json(
    provider: str,
    endpoint: str,
    api_key: str,
    payload: dict[str, Any],
    timeout: float,
) -> dict[str, Any]:
    headers = {"content-type": "application/json"}
    if provider == "openai":
        headers["authorization"] = f"Bearer {api_key}"
    else:
        headers.update(
            {
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "computer-use-2025-11-24",
            }
        )
    request = urllib.request.Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as error:
        detail = error.read().decode("utf-8", errors="replace")
        raise ReplayError(f"{provider} returned HTTP {error.code}: {detail[:1200]}") from error
    except urllib.error.URLError as error:
        raise ReplayError(f"{provider} request failed: {error}") from error


def normalize_usage(provider: str, response: dict[str, Any]) -> dict[str, int]:
    usage = response.get("usage") or {}
    if provider == "openai":
        return {
            "input_tokens": int(usage.get("input_tokens") or 0),
            "cached_input_tokens": int((usage.get("input_tokens_details") or {}).get("cached_tokens") or 0),
            "output_tokens": int(usage.get("output_tokens") or 0),
        }
    return {
        "input_tokens": int(usage.get("input_tokens") or 0),
        "cache_creation_input_tokens": int(usage.get("cache_creation_input_tokens") or 0),
        "cache_read_input_tokens": int(usage.get("cache_read_input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or 0),
    }


def add_usage(total: dict[str, int], current: dict[str, int]) -> None:
    for key, value in current.items():
        total[key] = total.get(key, 0) + value


def _json_text(text: str) -> dict[str, Any]:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as error:
        raise ReplayError(f"provider returned invalid JSON: {error}") from error
    if not isinstance(parsed, dict):
        raise ReplayError("provider output must be a JSON object")
    return parsed


def _openai_text(response: dict[str, Any]) -> str | None:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    for item in response.get("output") or []:
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and isinstance(content.get("text"), str):
                return content["text"]
    return None


def run_openai_replay(
    *, model: str, endpoint: str, api_key: str, prompt: str, environment: ReplayEnvironment,
    timeout: float, max_turns: int, usage: dict[str, int] | None = None,
    transcript: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, int], list[dict[str, Any]]]:
    payload = openai_initial_payload(model, prompt)
    usage = usage if usage is not None else {}
    transcript = transcript if transcript is not None else []
    for turn in range(1, max_turns + 1):
        response = request_json("openai", endpoint, api_key, payload, timeout)
        add_usage(usage, normalize_usage("openai", response))
        calls = [item for item in response.get("output") or [] if item.get("type") == "computer_call"]
        transcript.append({"turn": turn, "response_id": response.get("id"), "computer_calls": calls})
        text = _openai_text(response)
        if text is not None:
            return _json_text(text), usage, transcript
        if len(calls) != 1:
            raise ReplayError("OpenAI returned neither final text nor exactly one computer call")
        call = calls[0]
        actions = call.get("actions") or []
        if len(actions) != 1 or actions[0].get("type") != "screenshot":
            requested = [action.get("type") for action in actions]
            raise ReplayPolicyViolation(f"OpenAI requested disallowed actions: {requested}")
        image, _ = environment.screenshot()
        response_id = response.get("id")
        call_id = call.get("call_id")
        if not isinstance(response_id, str) or not isinstance(call_id, str):
            raise ReplayError("OpenAI computer call omitted response id or call id")
        payload = openai_continuation_payload(model, response_id, call_id, image)
    raise ReplayBudgetExceeded("turn budget exhausted")


def _anthropic_text(response: dict[str, Any]) -> str | None:
    texts = [block.get("text") for block in response.get("content") or [] if block.get("type") == "text"]
    values = [value for value in texts if isinstance(value, str) and value.strip()]
    return values[-1] if values else None


def run_anthropic_replay(
    *, model: str, endpoint: str, api_key: str, prompt: str, environment: ReplayEnvironment,
    timeout: float, max_turns: int, usage: dict[str, int] | None = None,
    transcript: list[dict[str, Any]] | None = None,
) -> tuple[dict[str, Any], dict[str, int], list[dict[str, Any]]]:
    payload = anthropic_initial_payload(model, prompt, environment.display_size)
    usage = usage if usage is not None else {}
    transcript = transcript if transcript is not None else []
    for turn in range(1, max_turns + 1):
        response = request_json("anthropic", endpoint, api_key, payload, timeout)
        add_usage(usage, normalize_usage("anthropic", response))
        content = response.get("content") or []
        calls = [block for block in content if block.get("type") == "tool_use"]
        transcript.append(
            {
                "turn": turn,
                "response_id": response.get("id"),
                "stop_reason": response.get("stop_reason"),
                "tool_calls": calls,
            }
        )
        if not calls:
            text = _anthropic_text(response)
            if text is None:
                raise ReplayError("Anthropic returned neither final text nor a tool call")
            return _json_text(text), usage, transcript
        results: list[dict[str, Any]] = []
        for call in calls:
            if call.get("name") != "computer" or not isinstance(call.get("id"), str):
                raise ReplayPolicyViolation("Anthropic requested an unknown tool")
            action = (call.get("input") or {}).get("action")
            if action == "screenshot":
                image, _ = environment.screenshot()
            elif action == "zoom":
                image, _ = environment.zoom((call.get("input") or {}).get("region"))
            else:
                raise ReplayPolicyViolation(f"Anthropic requested disallowed action: {action!r}")
            results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": call["id"],
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": base64.b64encode(image).decode("ascii"),
                            },
                        }
                    ],
                }
            )
        payload = anthropic_continuation_payload(payload, content, results)
    raise ReplayBudgetExceeded("turn budget exhausted")


def _observation(output: dict[str, Any], sample_id: str) -> dict[str, Any]:
    rows = output.get("observations")
    if not isinstance(rows, list) or len(rows) != 1 or rows[0].get("sample_id") != sample_id:
        raise ReplayError("provider did not return exactly the requested sample_id")
    return rows[0]


def _frame_metadata(frames: list[EvidenceFrame]) -> list[dict[str, Any]]:
    return [
        {
            "role": frame.role,
            "source_video": str(frame.source_video),
            "frame_index": frame.frame_index,
            "timestamp_seconds": frame.timestamp_seconds,
            "width": frame.width,
            "height": frame.height,
            "sha256": frame.sha256,
            "encoded_bytes": frame.encoded_bytes,
            "artifact": str(frame.path),
        }
        for frame in frames
    ]


def _pricing(args: argparse.Namespace) -> dict[str, Any]:
    return {
        "basis": "published_api_price" if args.input_usd_per_million is not None else None,
        "source": args.pricing_source,
        "accessed_at": args.pricing_accessed_at,
        "input_usd_per_million": args.input_usd_per_million,
        "output_usd_per_million": args.output_usd_per_million,
        "cached_input_usd_per_million": args.cached_input_usd_per_million,
        "cache_write_usd_per_million": args.cache_write_usd_per_million,
    }


def main() -> None:
    args = parse_args()
    if args.max_turns <= 0:
        raise ReplayError("max-turns must be positive")
    args.output.mkdir(parents=True, exist_ok=True)
    status_path = args.output / "status.json"
    key_environment = KEY_ENVIRONMENTS[args.provider]
    api_key = os.environ.get(key_environment)
    if not api_key:
        status = {
            "schema_version": 1,
            "status": "not_run",
            "reason": f"{key_environment} is not set",
            "provider": args.provider,
            "model": args.model,
            "comparison_mode": "event_checkpoint_native_replay",
            "evaluation": str(args.evaluation.resolve()),
            "max_turns_per_event": args.max_turns,
            "max_screenshots_per_event": args.max_screenshots,
            "max_zooms_per_event": args.max_zooms,
        }
        status_path.write_text(json.dumps(status, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps(status, sort_keys=True))
        return

    evaluation = json.loads(args.evaluation.resolve().read_text(encoding="utf-8"))
    samples = choose_frozen_events(
        evaluation, args.per_category, case_ids=args.case_id
    )
    all_usage: dict[str, int] = {}
    events: list[dict[str, Any]] = []
    started = time.perf_counter()
    for sample in samples:
        sample_name = _safe_name(sample["sample_id"])
        event_dir = args.output / "events" / sample_name
        event_started = time.perf_counter()
        environment: ReplayEnvironment | None = None
        event_usage: dict[str, int] = {}
        event_transcript: list[dict[str, Any]] = []
        try:
            frames = extract_source_frames(sample, event_dir / "source")
            environment = ReplayEnvironment(
                frames,
                max_screenshots=args.max_screenshots,
                max_zooms=args.max_zooms,
                output_dir=event_dir / "zoom",
            )
            runner = run_openai_replay if args.provider == "openai" else run_anthropic_replay
            output, usage, transcript = runner(
                model=args.model,
                endpoint=args.endpoint or ENDPOINTS[args.provider],
                api_key=api_key,
                prompt=build_prompt(sample),
                environment=environment,
                timeout=args.timeout,
                max_turns=args.max_turns,
                usage=event_usage,
                transcript=event_transcript,
            )
            add_usage(all_usage, event_usage)
            events.append(
                {
                    "sample_id": sample["sample_id"],
                    "status": "completed",
                    "category": sample["event"]["category"],
                    "observation": _observation(output, sample["sample_id"]),
                    "usage": usage,
                    "latency_seconds": time.perf_counter() - event_started,
                    "source_evidence": _frame_metadata(frames),
                    "replay_trace": environment.trace,
                    "transcript": transcript,
                }
            )
        except Exception as error:  # Keep provider and policy failures in the benchmark artifact.
            add_usage(all_usage, event_usage)
            events.append(
                {
                    "sample_id": sample["sample_id"],
                    "status": "failed",
                    "category": sample["event"]["category"],
                    "failure_type": type(error).__name__,
                    "failure": str(error),
                    "usage": event_usage,
                    "latency_seconds": time.perf_counter() - event_started,
                    "source_evidence": _frame_metadata(environment.frames) if environment else [],
                    "replay_trace": environment.trace if environment else [],
                    "transcript": event_transcript,
                }
            )

    estimated_cost = estimate_cost(args, all_usage)
    if estimated_cost is not None and (not args.pricing_source or not args.pricing_accessed_at):
        raise ReplayError("priced runs require --pricing-source and --pricing-accessed-at")
    failures = sum(event["status"] != "completed" for event in events)
    report = {
        "schema_version": 1,
        "status": "completed" if failures == 0 else "completed_with_failures",
        "provider": args.provider,
        "model": args.model,
        "comparison_mode": "event_checkpoint_native_replay",
        "scope": "perception_only_no_action_execution",
        "evaluation": str(args.evaluation.resolve()),
        "selection": {"case_ids": args.case_id} if args.case_id else {"per_category": args.per_category},
        "event_count": len(events),
        "completed_event_count": len(events) - failures,
        "failed_event_count": failures,
        "latency_seconds": time.perf_counter() - started,
        "usage": all_usage,
        "estimated_cost_usd": estimated_cost,
        "pricing": _pricing(args),
        "budgets": {
            "max_turns_per_event": args.max_turns,
            "max_screenshots_per_event": args.max_screenshots,
            "max_zooms_per_event": args.max_zooms,
        },
        "events": events,
    }
    status_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({key: report[key] for key in ("status", "provider", "model", "event_count", "completed_event_count", "failed_event_count", "usage", "estimated_cost_usd")}, sort_keys=True))


if __name__ == "__main__":
    main()
