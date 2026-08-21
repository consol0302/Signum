from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .gateway import GatewayConfig, PerceptionGateway, SemanticInterpreter
from .observe import observe_video, serialize_observation
from .video import VideoMetadata, iter_frames, probe_video


class EvaluationError(ValueError):
    pass


@dataclass(frozen=True)
class NormalizedRegion:
    x: float
    y: float
    width: float
    height: float

    def validate(self) -> None:
        values = (self.x, self.y, self.width, self.height)
        if not all(math.isfinite(value) for value in values):
            raise EvaluationError("event regions must contain finite numbers")
        if self.x < 0 or self.y < 0 or self.width <= 0 or self.height <= 0:
            raise EvaluationError("event regions must have positive normalized bounds")
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise EvaluationError("event regions must remain inside the video frame")


@dataclass(frozen=True)
class LabeledEvent:
    id: str
    start: float
    end: float
    tolerance: float = 0.0
    region: NormalizedRegion | None = None
    acceptable_states: tuple[str, ...] = ()
    notes: str = ""

    def validate(self) -> None:
        _validate_id(self.id, "event")
        if not math.isfinite(self.start) or not math.isfinite(self.end):
            raise EvaluationError(f"event {self.id!r} has non-finite timestamps")
        if self.start < 0 or self.end < self.start:
            raise EvaluationError(f"event {self.id!r} has an invalid time range")
        if not math.isfinite(self.tolerance) or self.tolerance < 0:
            raise EvaluationError(f"event {self.id!r} has an invalid tolerance")
        if self.region is not None:
            self.region.validate()
        if any(not state.strip() for state in self.acceptable_states):
            raise EvaluationError(f"event {self.id!r} has an empty acceptable state")


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    video: Path
    goal: str
    events: tuple[LabeledEvent, ...]

    def validate(self) -> None:
        _validate_id(self.id, "case")
        if not self.goal.strip():
            raise EvaluationError(f"case {self.id!r} has an empty goal")
        event_ids = [event.id for event in self.events]
        if len(event_ids) != len(set(event_ids)):
            raise EvaluationError(f"case {self.id!r} has duplicate event ids")
        for event in self.events:
            event.validate()


@dataclass(frozen=True)
class EvaluationManifest:
    path: Path
    cases: tuple[EvaluationCase, ...]


def load_manifest(path: Path | str) -> EvaluationManifest:
    manifest_path = Path(path).resolve()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EvaluationError(f"evaluation manifest was not found: {manifest_path}") from error
    except json.JSONDecodeError as error:
        raise EvaluationError(f"evaluation manifest is invalid JSON: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise EvaluationError("evaluation manifest schema_version must be 1")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvaluationError("evaluation manifest must contain at least one case")
    cases = tuple(_parse_case(item, manifest_path.parent) for item in raw_cases)
    case_ids = [case.id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise EvaluationError("evaluation manifest has duplicate case ids")
    for case in cases:
        case.validate()
    return EvaluationManifest(path=manifest_path, cases=cases)


def run_evaluation(
    manifest_path: Path | str,
    output_dir: Path | str,
    *,
    config: GatewayConfig | None = None,
    interpreter: SemanticInterpreter | None = None,
) -> dict[str, Any]:
    manifest = load_manifest(manifest_path)
    gateway_config = config or GatewayConfig()
    gateway_config.validate()
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    case_rows: list[dict[str, Any]] = []
    review_rows: list[dict[str, Any]] = []

    for case in manifest.cases:
        if not case.video.is_file():
            raise EvaluationError(f"case {case.id!r} video was not found: {case.video}")
        metadata = probe_video(case.video)
        _validate_event_times(case, metadata)
        case_output = output / "cases" / case.id
        signum_output = case_output / "signum"
        signum_payload = observe_video(
            case.video,
            signum_output,
            goal=case.goal,
            config=gateway_config,
            interpreter=interpreter,
        )
        observation_budget = len(signum_payload["observations"])
        uniform_payload = _observe_uniform(
            case,
            metadata,
            case_output / "uniform",
            observation_budget,
            gateway_config,
            interpreter,
        )
        methods: dict[str, dict[str, Any]] = {}
        for method, payload in (
            ("signum", signum_payload),
            ("uniform", uniform_payload),
        ):
            scored = _score_method(
                case,
                metadata,
                payload["observations"],
                semantic_attempted=interpreter is not None,
            )
            methods[method] = {
                "observation_file": str(
                    (case_output / method / "observations.json")
                    .relative_to(output)
                    .as_posix()
                ),
                "stats": payload["stats"],
                **scored,
            }
            review_rows.extend(_build_review_rows(case, method, scored["matches"]))
        case_rows.append(
            {
                "id": case.id,
                "video": str(case.video),
                "goal": case.goal,
                "duration_seconds": metadata.duration_seconds,
                "event_count": len(case.events),
                "observation_budget": observation_budget,
                "events": [_event_to_dict(event) for event in case.events],
                "methods": methods,
            }
        )

    aggregate = {
        method: _aggregate_method(case_rows, method) for method in ("signum", "uniform")
    }
    payload = {
        "schema_version": 1,
        "manifest": str(manifest.path),
        "semantic_attempted": interpreter is not None,
        "interpreter": _interpreter_metadata(interpreter),
        "config": gateway_config.to_dict(),
        "aggregate": aggregate,
        "cases": case_rows,
        "notes": [
            "Trigger matching uses current and preserved-peak image timestamps.",
            "Uniform uses the same number of observations as Signum in each case.",
            "Human review is required for visible-evidence, semantic, task-state, "
            "and end-to-end success rates.",
        ],
    }
    payload["evaluation_id"] = _fingerprint(payload)
    evaluation_path = output / "evaluation.json"
    evaluation_path.write_text(_json_text(payload), encoding="utf-8")
    review_payload = {
        "schema_version": 1,
        "evaluation_id": payload["evaluation_id"],
        "evaluation": "evaluation.json",
        "reviewer": "",
        "reviewed_at_utc": "",
        "instructions": (
            "For every triggered row, replace each null verdict with true or false. "
            "Judge only the saved images and structured observation. Untriggered rows "
            "are automatic failures and need no verdict."
        ),
        "reviews": review_rows,
    }
    (output / "review-template.json").write_text(
        _json_text(review_payload), encoding="utf-8"
    )
    return payload


def score_reviews(
    evaluation_path: Path | str,
    reviews_path: Path | str,
    output_path: Path | str | None = None,
) -> dict[str, Any]:
    evaluation_file = Path(evaluation_path)
    reviews_file = Path(reviews_path)
    evaluation = _read_json_object(evaluation_file, "evaluation")
    reviews = _read_json_object(reviews_file, "reviews")
    if evaluation.get("schema_version") != 1:
        raise EvaluationError("evaluation schema_version must be 1")
    if reviews.get("schema_version") != 1:
        raise EvaluationError("review schema_version must be 1")
    if reviews.get("evaluation_id") != evaluation.get("evaluation_id"):
        raise EvaluationError("review file does not belong to this evaluation run")
    raw_reviews = reviews.get("reviews")
    if not isinstance(raw_reviews, list):
        raise EvaluationError("review file must contain a reviews array")
    review_index: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in raw_reviews:
        if not isinstance(row, dict):
            raise EvaluationError("every review row must be an object")
        key = (str(row.get("case_id")), str(row.get("event_id")), str(row.get("method")))
        if key in review_index:
            raise EvaluationError(f"duplicate review row: {key}")
        review_index[key] = row

    method_counts = {
        method: _empty_review_counts() for method in ("signum", "uniform")
    }
    cases = evaluation.get("cases")
    if not isinstance(cases, list):
        raise EvaluationError("evaluation file must contain cases")
    for case in cases:
        if not isinstance(case, dict):
            raise EvaluationError("evaluation case must be an object")
        case_id = str(case.get("id"))
        methods = case.get("methods")
        if not isinstance(methods, dict):
            raise EvaluationError(f"evaluation case {case_id!r} has no methods")
        for method in ("signum", "uniform"):
            method_payload = methods.get(method)
            if not isinstance(method_payload, dict):
                raise EvaluationError(f"evaluation case {case_id!r} is missing {method}")
            matches = method_payload.get("matches")
            if not isinstance(matches, list):
                raise EvaluationError(f"evaluation case {case_id!r} has invalid matches")
            for match in matches:
                if not isinstance(match, dict):
                    raise EvaluationError("evaluation match must be an object")
                event_id = str(match.get("event_id"))
                triggered = bool(match.get("triggered"))
                counts = method_counts[method]
                counts["events"] += 1
                if not triggered:
                    for field in (
                        "evidence_visible",
                        "semantic_correct",
                        "task_state_correct",
                    ):
                        counts[f"{field}_reviewed"] += 1
                    counts["end_to_end_reviewed"] += 1
                    continue
                row = review_index.get((case_id, event_id, method))
                if row is None:
                    continue
                verdicts: list[bool] = []
                for field in (
                    "evidence_visible",
                    "semantic_correct",
                    "task_state_correct",
                ):
                    value = row.get(field)
                    if value is not None and not isinstance(value, bool):
                        raise EvaluationError(f"review field {field!r} must be boolean or null")
                    if isinstance(value, bool):
                        counts[f"{field}_reviewed"] += 1
                        counts[f"{field}_passed"] += int(value)
                        verdicts.append(value)
                if len(verdicts) == 3:
                    counts["end_to_end_reviewed"] += 1
                    counts["end_to_end_passed"] += int(all(verdicts))

    methods_scored = {
        method: _finalize_review_counts(counts)
        for method, counts in method_counts.items()
    }
    payload = {
        "schema_version": 1,
        "evaluation": str(evaluation_file.resolve()),
        "reviews": str(reviews_file.resolve()),
        "methods": methods_scored,
        "complete": all(
            row["review_complete"] for row in methods_scored.values()
        ),
        "notes": [
            "Untriggered labeled events count as failures in all reviewed success rates.",
            "A rate remains null until every triggered event has the required human verdict.",
        ],
    }
    destination = (
        Path(output_path)
        if output_path is not None
        else evaluation_file.parent / "score.json"
    )
    destination.write_text(_json_text(payload), encoding="utf-8")
    return payload


def _parse_case(raw: object, root: Path) -> EvaluationCase:
    if not isinstance(raw, dict):
        raise EvaluationError("every evaluation case must be an object")
    raw_video = raw.get("video")
    if not isinstance(raw_video, str) or not raw_video.strip():
        raise EvaluationError("every evaluation case must provide a video path")
    video = Path(raw_video)
    if not video.is_absolute():
        video = (root / video).resolve()
    raw_events = raw.get("events", [])
    if not isinstance(raw_events, list):
        raise EvaluationError("case events must be an array")
    return EvaluationCase(
        id=_required_string(raw, "id", "case"),
        video=video,
        goal=_required_string(raw, "goal", "case"),
        events=tuple(_parse_event(item) for item in raw_events),
    )


def _parse_event(raw: object) -> LabeledEvent:
    if not isinstance(raw, dict):
        raise EvaluationError("every labeled event must be an object")
    region = raw.get("region")
    parsed_region = None
    if region is not None:
        if not isinstance(region, dict):
            raise EvaluationError("event region must be an object")
        parsed_region = NormalizedRegion(
            x=_required_number(region, "x"),
            y=_required_number(region, "y"),
            width=_required_number(region, "width"),
            height=_required_number(region, "height"),
        )
    states = raw.get("acceptable_states", [])
    if not isinstance(states, list) or not all(isinstance(item, str) for item in states):
        raise EvaluationError("acceptable_states must be an array of strings")
    notes = raw.get("notes", "")
    if not isinstance(notes, str):
        raise EvaluationError("event notes must be a string")
    return LabeledEvent(
        id=_required_string(raw, "id", "event"),
        start=_required_number(raw, "start"),
        end=_required_number(raw, "end"),
        tolerance=_optional_number(raw, "tolerance", 0.0),
        region=parsed_region,
        acceptable_states=tuple(states),
        notes=notes,
    )


def _observe_uniform(
    case: EvaluationCase,
    metadata: VideoMetadata,
    output: Path,
    budget: int,
    config: GatewayConfig,
    interpreter: SemanticInterpreter | None,
) -> dict[str, Any]:
    images_dir = output / "events"
    images_dir.mkdir(parents=True, exist_ok=True)
    observations: list[dict[str, Any]] = []
    gateway = PerceptionGateway(config, interpreter=interpreter)
    target_indices = _uniform_indices(metadata.frame_count, budget)
    targets = set(target_indices)
    for frame_index, frame in iter_frames(metadata):
        if frame_index not in targets:
            continue
        observation = gateway.force_snapshot(
            frame,
            frame_index / metadata.fps,
            goal=case.goal,
            frame_index=frame_index,
        )
        observations.append(serialize_observation(observation, images_dir, output))
    payload = {
        "schema_version": 2,
        "source": metadata.to_dict(),
        "goal": case.goal,
        "config": config.to_dict(),
        "method": "uniform",
        "stats": gateway.stats.to_dict(),
        "observations": observations,
    }
    (output / "observations.json").write_text(_json_text(payload), encoding="utf-8")
    return payload


def _uniform_indices(frame_count: int, budget: int) -> list[int]:
    if frame_count <= 0 or budget <= 0:
        return []
    count = min(frame_count, budget)
    return [
        min(frame_count - 1, int((index + 0.5) * frame_count / count))
        for index in range(count)
    ]


def _score_method(
    case: EvaluationCase,
    metadata: VideoMetadata,
    observations: list[dict[str, Any]],
    *,
    semantic_attempted: bool,
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    matched_sequences: set[int] = set()
    exact_state_total = 0
    exact_state_correct = 0
    for event in case.events:
        match = _best_match(event, observations)
        if match is not None:
            matched_sequences.add(int(match["sequence"]))
        expected_states = {_normalize_state(item) for item in event.acceptable_states}
        state_correct: bool | None = None
        if semantic_attempted and expected_states:
            exact_state_total += 1
            actual = match.get("state") if match is not None else None
            state_correct = (
                isinstance(actual, str) and _normalize_state(actual) in expected_states
            )
            exact_state_correct += int(state_correct)
        matches.append(
            {
                "event_id": event.id,
                "triggered": match is not None,
                "matched_sequence": match.get("sequence") if match else None,
                "matched_timestamp": match.get("timestamp") if match else None,
                "matched_image_role": match.get("image_role") if match else None,
                "matched_image_timestamp": match.get("image_timestamp") if match else None,
                "state": match.get("state") if match else None,
                "image_files": match.get("image_files", []) if match else [],
                "interpretation": match.get("interpretation") if match else None,
                "exact_state_correct": state_correct,
            }
        )
    event_count = len(case.events)
    triggered = sum(int(row["triggered"]) for row in matches)
    false_calls = sum(
        1
        for observation in observations
        if int(observation["event"]["sequence"]) not in matched_sequences
    )
    duration_minutes = (
        metadata.duration_seconds / 60 if metadata.duration_seconds > 0 else 0.0
    )
    return {
        "metrics": {
            "labeled_events": event_count,
            "triggered_events": triggered,
            "trigger_recall": _rate(triggered, event_count, empty=1.0),
            "observations": len(observations),
            "false_observations": false_calls,
            "false_calls_per_minute": (
                false_calls / duration_minutes if duration_minutes else 0.0
            ),
            "calls_per_minute": (
                len(observations) / duration_minutes if duration_minutes else 0.0
            ),
            "exact_state_events": exact_state_total,
            "exact_state_correct": exact_state_correct,
            "exact_state_accuracy": (
                _rate(exact_state_correct, exact_state_total)
                if exact_state_total
                else None
            ),
        },
        "matches": matches,
    }


def _best_match(
    labeled: LabeledEvent, observations: list[dict[str, Any]]
) -> dict[str, Any] | None:
    best: tuple[float, int, dict[str, Any]] | None = None
    for observation in observations:
        event = observation.get("event")
        if not isinstance(event, dict):
            continue
        interpretation = observation.get("interpretation")
        state = interpretation.get("state") if isinstance(interpretation, dict) else None
        roles = [
            image.get("role")
            for image in event.get("images", [])
            if isinstance(image, dict)
        ]
        candidates = [(event.get("timestamp"), "current")]
        if "change_peak" in roles and event.get("peak_timestamp") is not None:
            candidates.append((event.get("peak_timestamp"), "change_peak"))
        for raw_time, role in candidates:
            if not isinstance(raw_time, (int, float)):
                continue
            timestamp = float(raw_time)
            distance = _interval_distance(timestamp, labeled.start, labeled.end)
            if distance > labeled.tolerance:
                continue
            sequence = int(event.get("sequence", 0))
            candidate = {
                "sequence": sequence,
                "timestamp": event.get("timestamp"),
                "image_role": role,
                "image_timestamp": timestamp,
                "state": state,
                "image_files": event.get("image_files", []),
                "interpretation": interpretation,
            }
            rank = (distance, sequence, candidate)
            if best is None or rank[:2] < best[:2]:
                best = rank
    return best[2] if best else None


def _aggregate_method(case_rows: list[dict[str, Any]], method: str) -> dict[str, Any]:
    metrics = [row["methods"][method]["metrics"] for row in case_rows]
    stats = [row["methods"][method]["stats"] for row in case_rows]
    events = sum(int(row["labeled_events"]) for row in metrics)
    triggered = sum(int(row["triggered_events"]) for row in metrics)
    observations = sum(int(row["observations"]) for row in metrics)
    false_observations = sum(int(row["false_observations"]) for row in metrics)
    duration_minutes = sum(float(row["duration_seconds"]) for row in case_rows) / 60
    state_events = sum(int(row["exact_state_events"]) for row in metrics)
    state_correct = sum(int(row["exact_state_correct"]) for row in metrics)
    ai_calls = sum(int(row["ai_calls"]) for row in stats)
    usage_calls = sum(int(row["ai_calls_with_reported_usage"]) for row in stats)
    return {
        "labeled_events": events,
        "triggered_events": triggered,
        "trigger_recall": _rate(triggered, events, empty=1.0),
        "observations": observations,
        "false_observations": false_observations,
        "false_calls_per_minute": (
            false_observations / duration_minutes if duration_minutes else 0.0
        ),
        "calls_per_minute": observations / duration_minutes if duration_minutes else 0.0,
        "exact_state_events": state_events,
        "exact_state_correct": state_correct,
        "exact_state_accuracy": _rate(state_correct, state_events) if state_events else None,
        "ai_calls": ai_calls,
        "ai_calls_with_reported_usage": usage_calls,
        "ai_calls_without_reported_usage": ai_calls - usage_calls,
        "reported_usage_complete": ai_calls > 0 and ai_calls == usage_calls,
        "reported_input_tokens": sum(int(row["reported_input_tokens"]) for row in stats),
        "reported_cached_input_tokens": sum(
            int(row["reported_cached_input_tokens"]) for row in stats
        ),
        "reported_output_tokens": sum(int(row["reported_output_tokens"]) for row in stats),
        "reported_reasoning_output_tokens": sum(
            int(row["reported_reasoning_output_tokens"]) for row in stats
        ),
        "reported_total_tokens": (
            sum(
                int(row["reported_input_tokens"]) + int(row["reported_output_tokens"])
                for row in stats
            )
            if usage_calls
            else None
        ),
        "transmitted_image_bytes": sum(
            int(row["transmitted_image_bytes"]) for row in stats
        ),
        "transmitted_image_patches_32px": sum(
            int(row["transmitted_image_patches_32px"]) for row in stats
        ),
        "ai_latency_seconds": sum(float(row["ai_latency_seconds"]) for row in stats),
    }


def _build_review_rows(
    case: EvaluationCase, method: str, matches: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    by_id = {event.id: event for event in case.events}
    rows = []
    for match in matches:
        event = by_id[str(match["event_id"])]
        rows.append(
            {
                "case_id": case.id,
                "event_id": event.id,
                "method": method,
                "triggered": match["triggered"],
                "matched_sequence": match["matched_sequence"],
                "label_time_range": [event.start, event.end],
                "label_region": asdict(event.region) if event.region else None,
                "observation_file": f"cases/{case.id}/{method}/observations.json",
                "image_files": [
                    f"cases/{case.id}/{method}/{path}"
                    for path in match["image_files"]
                ],
                "interpretation": match["interpretation"],
                "label_notes": event.notes,
                "evidence_visible": None,
                "semantic_correct": None,
                "task_state_correct": None,
                "review_notes": "",
            }
        )
    return rows


def _empty_review_counts() -> dict[str, int]:
    return {
        "events": 0,
        "evidence_visible_reviewed": 0,
        "evidence_visible_passed": 0,
        "semantic_correct_reviewed": 0,
        "semantic_correct_passed": 0,
        "task_state_correct_reviewed": 0,
        "task_state_correct_passed": 0,
        "end_to_end_reviewed": 0,
        "end_to_end_passed": 0,
    }


def _finalize_review_counts(counts: dict[str, int]) -> dict[str, Any]:
    events = counts["events"]
    result: dict[str, Any] = dict(counts)
    complete = True
    for field in ("evidence_visible", "semantic_correct", "task_state_correct"):
        reviewed = counts[f"{field}_reviewed"]
        passed = counts[f"{field}_passed"]
        field_complete = reviewed == events
        complete = complete and field_complete
        result[f"{field}_review_coverage"] = _rate(reviewed, events, empty=1.0)
        result[f"{field}_rate"] = _rate(passed, events) if field_complete else None
    end_complete = counts["end_to_end_reviewed"] == events
    result["end_to_end_review_coverage"] = _rate(
        counts["end_to_end_reviewed"], events, empty=1.0
    )
    result["end_to_end_success_rate"] = (
        _rate(counts["end_to_end_passed"], events) if end_complete else None
    )
    result["review_complete"] = complete and end_complete
    return result


def _validate_event_times(case: EvaluationCase, metadata: VideoMetadata) -> None:
    for event in case.events:
        if event.end > metadata.duration_seconds + 1 / metadata.fps:
            raise EvaluationError(
                f"event {case.id}/{event.id} ends after the video duration"
            )


def _event_to_dict(event: LabeledEvent) -> dict[str, Any]:
    payload = asdict(event)
    payload["acceptable_states"] = list(event.acceptable_states)
    return payload


def _interval_distance(timestamp: float, start: float, end: float) -> float:
    if timestamp < start:
        return start - timestamp
    if timestamp > end:
        return timestamp - end
    return 0.0


def _normalize_state(value: str) -> str:
    return "_".join(value.strip().lower().replace("-", "_").split())


def _rate(numerator: int, denominator: int, *, empty: float = 0.0) -> float:
    return numerator / denominator if denominator else empty


def _validate_id(value: str, kind: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", value):
        raise EvaluationError(
            f"{kind} id {value!r} must use letters, numbers, dots, dashes, or underscores"
        )


def _required_string(payload: dict[str, Any], key: str, context: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EvaluationError(f"{context} {key!r} must be a non-empty string")
    return value


def _required_number(payload: dict[str, Any], key: str) -> float:
    value = payload.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise EvaluationError(f"{key!r} must be numeric")
    return float(value)


def _optional_number(payload: dict[str, Any], key: str, default: float) -> float:
    if key not in payload:
        return default
    return _required_number(payload, key)


def _read_json_object(path: Path, kind: str) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EvaluationError(f"{kind} file was not found: {path}") from error
    except json.JSONDecodeError as error:
        raise EvaluationError(f"{kind} file is invalid JSON: {error}") from error
    if not isinstance(payload, dict):
        raise EvaluationError(f"{kind} file must contain a JSON object")
    return payload


def _json_text(payload: object) -> str:
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _fingerprint(payload: object) -> str:
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _interpreter_metadata(
    interpreter: SemanticInterpreter | None,
) -> dict[str, object] | None:
    if interpreter is None:
        return None
    metadata_method = getattr(interpreter, "metadata", None)
    if callable(metadata_method):
        metadata = metadata_method()
        if isinstance(metadata, dict):
            return metadata
    return {
        "type": f"{type(interpreter).__module__}.{type(interpreter).__qualname__}"
    }
