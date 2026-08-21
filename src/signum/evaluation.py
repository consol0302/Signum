from __future__ import annotations

import hashlib
import json
import math
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from .gateway import GatewayConfig, PerceptionGateway, SemanticInterpreter
from .observe import observe_video, serialize_observation
from .video import VideoMetadata, iter_frames, probe_video


class EvaluationError(ValueError):
    pass


EVENT_CATEGORIES = frozenset(
    {
        "small_ui",
        "action_success",
        "action_failure",
        "popup_notification",
        "loading_completion",
        "scroll_navigation",
        "cursor_hover_focus",
        "animation_game_hud",
        "transient_event",
        "other",
    }
)
RISK_LEVELS = frozenset({"low", "normal", "high", "critical"})
PILOT60_TARGETS = {
    "small_ui": 10,
    "action_success": 8,
    "action_failure": 8,
    "popup_notification": 6,
    "loading_completion": 6,
    "scroll_navigation": 5,
    "cursor_hover_focus": 5,
    "animation_game_hud": 6,
    "transient_event": 6,
}


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
    category: str = "other"
    risk: str = "normal"
    before_timestamp: float | None = None
    after_timestamp: float | None = None
    action: str | None = None
    expected_result: str | None = None
    notes: str = ""

    @property
    def is_action_verification(self) -> bool:
        return self.category in {"action_success", "action_failure"}

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
        if self.category not in EVENT_CATEGORIES:
            raise EvaluationError(
                f"event {self.id!r} has unknown category {self.category!r}"
            )
        if self.risk not in RISK_LEVELS:
            raise EvaluationError(f"event {self.id!r} has unknown risk {self.risk!r}")
        action_fields = (
            self.before_timestamp,
            self.after_timestamp,
            self.action,
            self.expected_result,
        )
        if self.is_action_verification:
            if any(value is None for value in action_fields):
                raise EvaluationError(
                    f"action event {self.id!r} must provide before_timestamp, "
                    "after_timestamp, action, and expected_result"
                )
            assert self.before_timestamp is not None
            assert self.after_timestamp is not None
            if self.before_timestamp < 0 or self.after_timestamp < self.before_timestamp:
                raise EvaluationError(
                    f"action event {self.id!r} has invalid verification timestamps"
                )
            if not self.action or not self.action.strip():
                raise EvaluationError(f"action event {self.id!r} has an empty action")
            if not self.expected_result or not self.expected_result.strip():
                raise EvaluationError(
                    f"action event {self.id!r} has an empty expected_result"
                )
        elif any(value is not None for value in action_fields):
            raise EvaluationError(
                f"non-action event {self.id!r} cannot provide action verification fields"
            )


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
    schema_version: int
    cases: tuple[EvaluationCase, ...]


def load_manifest(path: Path | str) -> EvaluationManifest:
    manifest_path = Path(path).resolve()
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise EvaluationError(f"evaluation manifest was not found: {manifest_path}") from error
    except json.JSONDecodeError as error:
        raise EvaluationError(f"evaluation manifest is invalid JSON: {error}") from error
    if not isinstance(payload, dict) or payload.get("schema_version") not in (1, 2):
        raise EvaluationError("evaluation manifest schema_version must be 1 or 2")
    schema_version = int(payload["schema_version"])
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvaluationError("evaluation manifest must contain at least one case")
    cases = tuple(
        _parse_case(item, manifest_path.parent, schema_version) for item in raw_cases
    )
    case_ids = [case.id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise EvaluationError("evaluation manifest has duplicate case ids")
    for case in cases:
        case.validate()
    return EvaluationManifest(
        path=manifest_path,
        schema_version=schema_version,
        cases=cases,
    )


def audit_manifest(
    path: Path | str,
    *,
    profile: str = "pilot60",
) -> dict[str, Any]:
    """Check whether a labeled suite has the planned category coverage."""

    if profile != "pilot60":
        raise EvaluationError(f"unknown evaluation profile: {profile!r}")
    manifest = load_manifest(path)
    counts = {category: 0 for category in sorted(EVENT_CATEGORIES)}
    risk_counts = {risk: 0 for risk in sorted(RISK_LEVELS)}
    events_with_regions = 0
    events_with_states = 0
    for case in manifest.cases:
        for event in case.events:
            counts[event.category] += 1
            risk_counts[event.risk] += 1
            events_with_regions += int(event.region is not None)
            events_with_states += int(bool(event.acceptable_states))
    deficits = {
        category: max(0, target - counts[category])
        for category, target in PILOT60_TARGETS.items()
    }
    return {
        "schema_version": 1,
        "manifest": str(manifest.path),
        "manifest_schema_version": manifest.schema_version,
        "profile": profile,
        "case_count": len(manifest.cases),
        "event_count": sum(counts.values()),
        "category_counts": counts,
        "risk_counts": risk_counts,
        "events_with_regions": events_with_regions,
        "events_with_acceptable_states": events_with_states,
        "targets": dict(PILOT60_TARGETS),
        "deficits": deficits,
        "profile_complete": all(value == 0 for value in deficits.values()),
        "notes": [
            "Profile completion checks label coverage, not recording quality.",
            "Synthetic or duplicated events must not be reported as real-world evidence.",
        ],
    }


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
        forced_verifications = sum(
            int(event.is_action_verification) for event in case.events
        )
        if forced_verifications:
            _append_action_verifications(
                case,
                metadata,
                signum_payload,
                signum_output,
                gateway_config,
                interpreter,
            )
            _append_action_verifications(
                case,
                metadata,
                uniform_payload,
                case_output / "uniform",
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
                "forced_action_verifications": forced_verifications,
                "events": [_event_to_dict(event) for event in case.events],
                "methods": methods,
            }
        )

    aggregate = {
        method: _aggregate_method(case_rows, method) for method in ("signum", "uniform")
    }
    by_category = {
        method: _aggregate_categories(case_rows, method)
        for method in ("signum", "uniform")
    }
    payload = {
        "schema_version": 1,
        "manifest": str(manifest.path),
        "manifest_schema_version": manifest.schema_version,
        "semantic_attempted": interpreter is not None,
        "interpreter": _interpreter_metadata(interpreter),
        "config": gateway_config.to_dict(),
        "aggregate": aggregate,
        "by_category": by_category,
        "cases": case_rows,
        "notes": [
            "Trigger matching uses current and preserved-peak image timestamps.",
            "Uniform uses the same number of observations as Signum in each case.",
            "Requested action verifications are forced for both methods and are not "
            "part of the passive observation budget.",
            "Human review is required for visible-evidence, semantic, task-state, "
            "and end-to-end success rates.",
            "Wilson intervals treat labeled events as Bernoulli trials; repeated or "
            "correlated events from one workflow reduce their inferential strength.",
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
        "review_method": "",
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
    category_counts: dict[str, dict[str, dict[str, int]]] = {
        method: {} for method in ("signum", "uniform")
    }
    cases = evaluation.get("cases")
    if not isinstance(cases, list):
        raise EvaluationError("evaluation file must contain cases")
    for case in cases:
        if not isinstance(case, dict):
            raise EvaluationError("evaluation case must be an object")
        case_id = str(case.get("id"))
        raw_events = case.get("events")
        if not isinstance(raw_events, list):
            raise EvaluationError(f"evaluation case {case_id!r} has invalid events")
        event_categories = {
            str(event.get("id")): str(event.get("category", "other"))
            for event in raw_events
            if isinstance(event, dict)
        }
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
                category = event_categories.get(event_id, "other")
                targets = [
                    method_counts[method],
                    category_counts[method].setdefault(
                        category, _empty_review_counts()
                    ),
                ]
                for counts in targets:
                    counts["events"] += 1
                    if category == "action_failure":
                        counts["action_failure_events"] += 1
                if not triggered:
                    for counts in targets:
                        for field in (
                            "evidence_visible",
                            "semantic_correct",
                            "task_state_correct",
                        ):
                            counts[f"{field}_reviewed"] += 1
                        counts["end_to_end_reviewed"] += 1
                        if category == "action_failure":
                            counts["false_confirmation_reviewed"] += 1
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
                        for counts in targets:
                            counts[f"{field}_reviewed"] += 1
                            counts[f"{field}_passed"] += int(value)
                        verdicts.append(value)
                if len(verdicts) == 3:
                    for counts in targets:
                        counts["end_to_end_reviewed"] += 1
                        counts["end_to_end_passed"] += int(all(verdicts))
                if category == "action_failure":
                    false_confirmation = row.get("false_confirmation")
                    if false_confirmation is not None and not isinstance(
                        false_confirmation, bool
                    ):
                        raise EvaluationError(
                            "review field 'false_confirmation' must be boolean or null"
                        )
                    if isinstance(false_confirmation, bool):
                        for counts in targets:
                            counts["false_confirmation_reviewed"] += 1
                            counts["false_confirmations"] += int(false_confirmation)

    methods_scored = {
        method: _finalize_review_counts(counts)
        for method, counts in method_counts.items()
    }
    categories_scored = {
        method: {
            category: _finalize_review_counts(counts)
            for category, counts in sorted(grouped.items())
        }
        for method, grouped in category_counts.items()
    }
    payload = {
        "schema_version": 1,
        "evaluation": str(evaluation_file.resolve()),
        "reviews": str(reviews_file.resolve()),
        "reviewer": reviews.get("reviewer", ""),
        "review_method": reviews.get("review_method", ""),
        "reviewed_at_utc": reviews.get("reviewed_at_utc", ""),
        "methods": methods_scored,
        "by_category": categories_scored,
        "complete": all(
            row["review_complete"] for row in methods_scored.values()
        ),
        "notes": [
            "Untriggered labeled events count as failures in all reviewed success rates.",
            "A rate remains null until every triggered event has the required explicit verdict.",
        ],
    }
    destination = (
        Path(output_path)
        if output_path is not None
        else evaluation_file.parent / "score.json"
    )
    destination.write_text(_json_text(payload), encoding="utf-8")
    return payload


def _parse_case(raw: object, root: Path, schema_version: int) -> EvaluationCase:
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
        events=tuple(_parse_event(item, schema_version) for item in raw_events),
    )


def _parse_event(raw: object, schema_version: int) -> LabeledEvent:
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
    category = raw.get("category", "other" if schema_version == 1 else None)
    if not isinstance(category, str) or not category.strip():
        raise EvaluationError("schema_version 2 events must provide a category")
    risk = raw.get("risk", "normal")
    if not isinstance(risk, str) or not risk.strip():
        raise EvaluationError("event risk must be a non-empty string")
    return LabeledEvent(
        id=_required_string(raw, "id", "event"),
        start=_required_number(raw, "start"),
        end=_required_number(raw, "end"),
        tolerance=_optional_number(raw, "tolerance", 0.0),
        region=parsed_region,
        acceptable_states=tuple(states),
        category=category,
        risk=risk,
        before_timestamp=_optional_nullable_number(raw, "before_timestamp"),
        after_timestamp=_optional_nullable_number(raw, "after_timestamp"),
        action=_optional_string(raw, "action"),
        expected_result=_optional_string(raw, "expected_result"),
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


def _append_action_verifications(
    case: EvaluationCase,
    metadata: VideoMetadata,
    payload: dict[str, Any],
    output: Path,
    config: GatewayConfig,
    interpreter: SemanticInterpreter | None,
) -> None:
    started = time.perf_counter()
    events = [event for event in case.events if event.is_action_verification]
    if not events:
        return
    target_indices: set[int] = set()
    event_indices: list[tuple[LabeledEvent, int, int]] = []
    for event in events:
        assert event.before_timestamp is not None
        assert event.after_timestamp is not None
        before_index = _timestamp_frame_index(event.before_timestamp, metadata)
        after_index = _timestamp_frame_index(event.after_timestamp, metadata)
        event_indices.append((event, before_index, after_index))
        target_indices.update((before_index, after_index))

    frames: dict[int, Any] = {}
    for frame_index, frame in iter_frames(metadata):
        if frame_index in target_indices:
            frames[frame_index] = frame.copy()
        if len(frames) == len(target_indices):
            break
    missing = sorted(target_indices.difference(frames))
    if missing:
        raise EvaluationError(
            f"case {case.id!r} could not decode action frames: {missing}"
        )

    gateway = PerceptionGateway(config, interpreter=interpreter)
    observations = payload.get("observations")
    if not isinstance(observations, list):
        raise EvaluationError(f"case {case.id!r} has invalid observation output")
    sequence_offset = max(
        (
            int(row["event"]["sequence"])
            for row in observations
            if isinstance(row, dict) and isinstance(row.get("event"), dict)
        ),
        default=-1,
    ) + 1
    images_dir = output / "action-events"
    images_dir.mkdir(parents=True, exist_ok=True)
    for event, before_index, after_index in event_indices:
        assert event.after_timestamp is not None
        assert event.action is not None
        assert event.expected_result is not None
        observation = gateway.verify_after_action(
            frames[before_index],
            frames[after_index],
            event.after_timestamp,
            goal=case.goal,
            action=event.action,
            expected_result=event.expected_result,
            frame_index=after_index,
        )
        serialized = serialize_observation(observation, images_dir, output)
        serialized["event"]["sequence"] = (  # type: ignore[index]
            sequence_offset + observation.event.sequence
        )
        observations.append(serialized)
    stats = payload.get("stats")
    if not isinstance(stats, dict):
        raise EvaluationError(f"case {case.id!r} has invalid gateway stats")
    _merge_gateway_stats(stats, gateway.stats.to_dict())
    stats["processing_seconds"] = stats.get("processing_seconds", 0.0) + (
        time.perf_counter() - started
    )
    (output / "observations.json").write_text(
        _json_text(payload), encoding="utf-8"
    )


def _timestamp_frame_index(timestamp: float, metadata: VideoMetadata) -> int:
    return min(
        metadata.frame_count - 1,
        max(0, int(round(timestamp * metadata.fps))),
    )


def _merge_gateway_stats(base: dict[str, Any], addition: dict[str, Any]) -> None:
    additive_fields = (
        "frames_seen",
        "events_emitted",
        "ai_calls",
        "prepared_image_bytes",
        "prepared_image_pixels",
        "transmitted_image_bytes",
        "transmitted_image_pixels",
        "transmitted_image_patches_32px",
        "ai_calls_with_reported_usage",
        "reported_input_tokens",
        "reported_cached_input_tokens",
        "reported_output_tokens",
        "reported_reasoning_output_tokens",
        "ai_latency_seconds",
    )
    for field in additive_fields:
        base[field] = base.get(field, 0) + addition.get(field, 0)
    usage_calls = int(base["ai_calls_with_reported_usage"])
    ai_calls = int(base["ai_calls"])
    base["ai_calls_without_reported_usage"] = ai_calls - usage_calls
    base["reported_usage_complete"] = ai_calls > 0 and ai_calls == usage_calls
    base["reported_total_tokens"] = (
        int(base["reported_input_tokens"]) + int(base["reported_output_tokens"])
        if usage_calls
        else None
    )


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
    verification_total = 0
    verification_correct = 0
    automatic_false_confirmations = 0
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
        expected_verification = None
        verification_is_correct: bool | None = None
        false_confirmation: bool | None = None
        actual_verification = match.get("verification") if match is not None else None
        if semantic_attempted and event.is_action_verification:
            expected_verification = (
                "confirmed" if event.category == "action_success" else "not_confirmed"
            )
            verification_total += 1
            verification_is_correct = actual_verification == expected_verification
            verification_correct += int(verification_is_correct)
            if event.category == "action_failure":
                false_confirmation = actual_verification == "confirmed"
                automatic_false_confirmations += int(false_confirmation)
        matches.append(
            {
                "event_id": event.id,
                "triggered": match is not None,
                "matched_sequence": match.get("sequence") if match else None,
                "matched_reason": match.get("reason") if match else None,
                "matched_timestamp": match.get("timestamp") if match else None,
                "matched_image_role": match.get("image_role") if match else None,
                "matched_image_timestamp": match.get("image_timestamp") if match else None,
                "state": match.get("state") if match else None,
                "verification": actual_verification,
                "expected_verification": expected_verification,
                "verification_correct": verification_is_correct,
                "false_confirmation": false_confirmation,
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
            "verification_events": verification_total,
            "verification_correct": verification_correct,
            "verification_accuracy": (
                _rate(verification_correct, verification_total)
                if verification_total
                else None
            ),
            "automatic_false_confirmations": automatic_false_confirmations,
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
        is_action_observation = event.get("reason") == "action_verification"
        if labeled.is_action_verification != is_action_observation:
            continue
        interpretation = observation.get("interpretation")
        state = interpretation.get("state") if isinstance(interpretation, dict) else None
        verification = (
            interpretation.get("verification")
            if isinstance(interpretation, dict)
            else None
        )
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
                "reason": event.get("reason"),
                "timestamp": event.get("timestamp"),
                "image_role": role,
                "image_timestamp": timestamp,
                "state": state,
                "verification": verification,
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
    verification_events = sum(int(row["verification_events"]) for row in metrics)
    verification_correct = sum(int(row["verification_correct"]) for row in metrics)
    automatic_false_confirmations = sum(
        int(row["automatic_false_confirmations"]) for row in metrics
    )
    ai_calls = sum(int(row["ai_calls"]) for row in stats)
    usage_calls = sum(int(row["ai_calls_with_reported_usage"]) for row in stats)
    trigger_recall = _rate(triggered, events, empty=1.0)
    exact_state_accuracy = (
        _rate(state_correct, state_events) if state_events else None
    )
    return {
        "labeled_events": events,
        "triggered_events": triggered,
        "trigger_recall": trigger_recall,
        "trigger_recall_ci95": _wilson_interval(triggered, events),
        "observations": observations,
        "false_observations": false_observations,
        "false_calls_per_minute": (
            false_observations / duration_minutes if duration_minutes else 0.0
        ),
        "calls_per_minute": observations / duration_minutes if duration_minutes else 0.0,
        "exact_state_events": state_events,
        "exact_state_correct": state_correct,
        "exact_state_accuracy": exact_state_accuracy,
        "exact_state_accuracy_ci95": _wilson_interval(state_correct, state_events),
        "verification_events": verification_events,
        "verification_correct": verification_correct,
        "verification_accuracy": (
            _rate(verification_correct, verification_events)
            if verification_events
            else None
        ),
        "verification_accuracy_ci95": _wilson_interval(
            verification_correct, verification_events
        ),
        "automatic_false_confirmations": automatic_false_confirmations,
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


def _aggregate_categories(
    case_rows: list[dict[str, Any]], method: str
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, int]] = {}
    for case in case_rows:
        events = {
            str(event["id"]): event
            for event in case["events"]
            if isinstance(event, dict)
        }
        for match in case["methods"][method]["matches"]:
            event = events[str(match["event_id"])]
            category = str(event["category"])
            row = grouped.setdefault(
                category,
                {
                    "labeled_events": 0,
                    "triggered_events": 0,
                    "exact_state_events": 0,
                    "exact_state_correct": 0,
                    "verification_events": 0,
                    "verification_correct": 0,
                    "automatic_false_confirmations": 0,
                },
            )
            row["labeled_events"] += 1
            row["triggered_events"] += int(bool(match["triggered"]))
            if match["exact_state_correct"] is not None:
                row["exact_state_events"] += 1
                row["exact_state_correct"] += int(bool(match["exact_state_correct"]))
            if match["verification_correct"] is not None:
                row["verification_events"] += 1
                row["verification_correct"] += int(
                    bool(match["verification_correct"])
                )
            row["automatic_false_confirmations"] += int(
                bool(match["false_confirmation"])
            )

    result: dict[str, dict[str, Any]] = {}
    for category, counts in sorted(grouped.items()):
        events = counts["labeled_events"]
        triggered = counts["triggered_events"]
        state_events = counts["exact_state_events"]
        state_correct = counts["exact_state_correct"]
        verification_events = counts["verification_events"]
        verification_correct = counts["verification_correct"]
        result[category] = {
            **counts,
            "trigger_recall": _rate(triggered, events, empty=1.0),
            "trigger_recall_ci95": _wilson_interval(triggered, events),
            "exact_state_accuracy": (
                _rate(state_correct, state_events) if state_events else None
            ),
            "exact_state_accuracy_ci95": _wilson_interval(
                state_correct, state_events
            ),
            "verification_accuracy": (
                _rate(verification_correct, verification_events)
                if verification_events
                else None
            ),
            "verification_accuracy_ci95": _wilson_interval(
                verification_correct, verification_events
            ),
        }
    return result


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
                "category": event.category,
                "risk": event.risk,
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
                "false_confirmation": (
                    None if event.category == "action_failure" else False
                ),
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
        "action_failure_events": 0,
        "false_confirmation_reviewed": 0,
        "false_confirmations": 0,
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
    action_failures = counts["action_failure_events"]
    false_confirmation_complete = (
        counts["false_confirmation_reviewed"] == action_failures
    )
    result["false_confirmation_review_coverage"] = _rate(
        counts["false_confirmation_reviewed"], action_failures, empty=1.0
    )
    result["false_confirmation_rate"] = (
        _rate(counts["false_confirmations"], action_failures)
        if action_failures and false_confirmation_complete
        else None
    )
    result["false_confirmation_rate_ci95"] = (
        _wilson_interval(counts["false_confirmations"], action_failures)
        if false_confirmation_complete
        else None
    )
    result["review_complete"] = (
        complete and end_complete and false_confirmation_complete
    )
    return result


def _validate_event_times(case: EvaluationCase, metadata: VideoMetadata) -> None:
    for event in case.events:
        if event.end > metadata.duration_seconds + 1 / metadata.fps:
            raise EvaluationError(
                f"event {case.id}/{event.id} ends after the video duration"
            )
        for name, timestamp in (
            ("before_timestamp", event.before_timestamp),
            ("after_timestamp", event.after_timestamp),
        ):
            if (
                timestamp is not None
                and timestamp > metadata.duration_seconds + 1 / metadata.fps
            ):
                raise EvaluationError(
                    f"event {case.id}/{event.id} {name} is after the video duration"
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


def _wilson_interval(successes: int, total: int) -> list[float] | None:
    """Return a two-sided 95% Wilson score interval for a binomial rate."""

    if total <= 0:
        return None
    z = 1.959963984540054
    proportion = successes / total
    denominator = 1 + z * z / total
    center = (proportion + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(
            proportion * (1 - proportion) / total
            + z * z / (4 * total * total)
        )
        / denominator
    )
    return [max(0.0, center - margin), min(1.0, center + margin)]


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


def _optional_nullable_number(
    payload: dict[str, Any], key: str
) -> float | None:
    if key not in payload or payload[key] is None:
        return None
    return _required_number(payload, key)


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise EvaluationError(f"{key!r} must be a string or null")
    return value


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
