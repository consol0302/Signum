from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass, field, replace
from typing import Protocol

import cv2
import numpy as np


@dataclass(frozen=True)
class GatewayConfig:
    analysis_width: int = 192
    local_analysis_width: int = 768
    pixel_threshold: int = 18
    min_changed_fraction: float = 0.002
    min_local_component_pixels: int = 12
    stable_frames: int = 2
    min_event_interval_seconds: float = 0.5
    max_active_seconds: float = 5.0
    crop_margin: int = 12
    context_width: int = 384
    detail_width: int = 768
    jpeg_quality: int = 80
    peak_image_min_difference: float = 0.02

    def validate(self) -> None:
        if self.analysis_width < 16:
            raise ValueError("analysis_width must be at least 16")
        if self.local_analysis_width < self.analysis_width:
            raise ValueError("local_analysis_width cannot be below analysis_width")
        if not 0 <= self.pixel_threshold <= 255:
            raise ValueError("pixel_threshold must be between 0 and 255")
        if not 0 <= self.min_changed_fraction <= 1:
            raise ValueError("min_changed_fraction must be between 0 and 1")
        if self.min_local_component_pixels <= 0:
            raise ValueError("min_local_component_pixels must be greater than zero")
        if self.stable_frames <= 0:
            raise ValueError("stable_frames must be greater than zero")
        if self.min_event_interval_seconds < 0:
            raise ValueError("min_event_interval_seconds cannot be negative")
        if self.max_active_seconds <= 0:
            raise ValueError("max_active_seconds must be greater than zero")
        if self.crop_margin < 0:
            raise ValueError("crop_margin cannot be negative")
        if self.context_width < 16 or self.detail_width < 16:
            raise ValueError("image widths must be at least 16")
        if not 1 <= self.jpeg_quality <= 100:
            raise ValueError("jpeg_quality must be between 1 and 100")
        if not 0 <= self.peak_image_min_difference <= 1:
            raise ValueError("peak_image_min_difference must be between 0 and 1")

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ChangeRegion:
    x: int
    y: int
    width: int
    height: int
    frame_width: int
    frame_height: int

    @property
    def area_ratio(self) -> float:
        frame_area = self.frame_width * self.frame_height
        return self.width * self.height / frame_area if frame_area else 0.0

    def expanded(self, margin: int) -> ChangeRegion:
        x1 = max(0, self.x - margin)
        y1 = max(0, self.y - margin)
        x2 = min(self.frame_width, self.x + self.width + margin)
        y2 = min(self.frame_height, self.y + self.height + margin)
        return ChangeRegion(
            x=x1,
            y=y1,
            width=max(1, x2 - x1),
            height=max(1, y2 - y1),
            frame_width=self.frame_width,
            frame_height=self.frame_height,
        )

    def merge(self, other: ChangeRegion) -> ChangeRegion:
        if (self.frame_width, self.frame_height) != (
            other.frame_width,
            other.frame_height,
        ):
            raise ValueError("cannot merge regions from different frame sizes")
        x1 = min(self.x, other.x)
        y1 = min(self.y, other.y)
        x2 = max(self.x + self.width, other.x + other.width)
        y2 = max(self.y + self.height, other.y + other.height)
        return ChangeRegion(
            x=x1,
            y=y1,
            width=x2 - x1,
            height=y2 - y1,
            frame_width=self.frame_width,
            frame_height=self.frame_height,
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "pixels": {
                "x": self.x,
                "y": self.y,
                "width": self.width,
                "height": self.height,
            },
            "normalized": {
                "x": self.x / self.frame_width,
                "y": self.y / self.frame_height,
                "width": self.width / self.frame_width,
                "height": self.height / self.frame_height,
            },
            "area_ratio": self.area_ratio,
        }


@dataclass(frozen=True)
class VisualInput:
    role: str
    jpeg: bytes = field(repr=False)
    width: int
    height: int

    @property
    def pixel_count(self) -> int:
        return self.width * self.height

    @property
    def patch_count_32px(self) -> int:
        """Return the unadjusted 32px-patch count for this image.

        This is an observable payload metric, not a claim about billed tokens.
        Model-specific resizing, detail settings, and multipliers may change the
        number reported by the runtime.
        """

        return math.ceil(self.width / 32) * math.ceil(self.height / 32)


@dataclass(frozen=True)
class PerceptionEvent:
    sequence: int
    timestamp: float
    frame_index: int | None
    reason: str
    change_fraction: float
    region: ChangeRegion | None
    images: tuple[VisualInput, ...] = field(repr=False)
    discovery: str = "global_fraction"
    peak_timestamp: float | None = None
    peak_frame_index: int | None = None
    action: str | None = None
    expected_result: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "frame_index": self.frame_index,
            "reason": self.reason,
            "discovery": self.discovery,
            "change_fraction": self.change_fraction,
            "peak_timestamp": self.peak_timestamp,
            "peak_frame_index": self.peak_frame_index,
            "action": self.action,
            "expected_result": self.expected_result,
            "region": self.region.to_dict() if self.region else None,
            "images": [
                {
                    "role": image.role,
                    "width": image.width,
                    "height": image.height,
                    "bytes": len(image.jpeg),
                    "patches_32px": image.patch_count_32px,
                }
                for image in self.images
            ],
        }


@dataclass(frozen=True)
class SemanticResult:
    state: str
    summary: str
    relevant: bool
    confidence: float
    recommended_action: str
    verification: str = "not_applicable"
    evidence: tuple[str, ...] = ()
    input_tokens: int | None = None
    cached_input_tokens: int | None = None
    output_tokens: int | None = None
    reasoning_output_tokens: int | None = None
    latency_seconds: float = 0.0

    @property
    def reported_total_tokens(self) -> int | None:
        if self.input_tokens is None or self.output_tokens is None:
            return None
        return self.input_tokens + self.output_tokens

    def to_dict(self) -> dict[str, object]:
        return {
            **asdict(self),
            "reported_total_tokens": self.reported_total_tokens,
        }


class SemanticInterpreter(Protocol):
    def interpret(
        self,
        event: PerceptionEvent,
        goal: str,
        previous: SemanticResult | None,
    ) -> SemanticResult: ...


@dataclass(frozen=True)
class GatewayObservation:
    event: PerceptionEvent
    interpretation: SemanticResult | None

    def to_dict(self) -> dict[str, object]:
        return {
            "event": self.event.to_dict(),
            "interpretation": (
                self.interpretation.to_dict() if self.interpretation else None
            ),
        }


@dataclass
class GatewayStats:
    frames_seen: int = 0
    events_emitted: int = 0
    ai_calls: int = 0
    prepared_image_bytes: int = 0
    prepared_image_pixels: int = 0
    transmitted_image_bytes: int = 0
    transmitted_image_pixels: int = 0
    transmitted_image_patches_32px: int = 0
    ai_calls_with_reported_usage: int = 0
    reported_input_tokens: int = 0
    reported_cached_input_tokens: int = 0
    reported_output_tokens: int = 0
    reported_reasoning_output_tokens: int = 0
    ai_latency_seconds: float = 0.0

    def to_dict(self) -> dict[str, object]:
        reported_total_tokens = (
            self.reported_input_tokens + self.reported_output_tokens
            if self.ai_calls_with_reported_usage > 0
            else None
        )
        return {
            **asdict(self),
            "reported_total_tokens": reported_total_tokens,
            "ai_calls_without_reported_usage": (
                self.ai_calls - self.ai_calls_with_reported_usage
            ),
            "reported_usage_complete": (
                self.ai_calls > 0
                and self.ai_calls == self.ai_calls_with_reported_usage
            ),
        }


class PerceptionGateway:
    """Stateful, frame-by-frame perception gate for a computer-use loop."""

    def __init__(
        self,
        config: GatewayConfig | None = None,
        interpreter: SemanticInterpreter | None = None,
    ) -> None:
        self.config = config or GatewayConfig()
        self.config.validate()
        self.interpreter = interpreter
        self.stats = GatewayStats()
        self._previous_gray: np.ndarray | None = None
        self._previous_local_gray: np.ndarray | None = None
        self._pending_region: ChangeRegion | None = None
        self._pending_change_fraction = 0.0
        self._pending_discovery = "global_fraction"
        self._pending_peak_frame: np.ndarray | None = None
        self._pending_peak_timestamp: float | None = None
        self._pending_peak_frame_index: int | None = None
        self._active_since: float | None = None
        self._stable_count = 0
        self._last_event_time = float("-inf")
        self._sequence = 0
        self._last_interpretation: SemanticResult | None = None

    def observe_frame(
        self,
        frame: np.ndarray,
        timestamp: float,
        *,
        goal: str,
        frame_index: int | None = None,
    ) -> GatewayObservation | None:
        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("frame must be a BGR image with three channels")
        if timestamp < 0:
            raise ValueError("timestamp cannot be negative")

        self.stats.frames_seen += 1
        gray, local_gray = _analysis_pair(frame, self.config)
        if self._previous_gray is None:
            self._previous_gray = gray
            self._previous_local_gray = local_gray
            return self._emit(
                frame,
                timestamp,
                frame_index,
                goal,
                reason="initial",
                change_fraction=1.0,
                region=None,
                discovery="initial",
            )

        assert self._previous_local_gray is not None
        detection = _detect_change(
            gray,
            self._previous_gray,
            local_gray,
            self._previous_local_gray,
            frame.shape[1],
            frame.shape[0],
            self.config,
        )
        self._previous_gray = gray
        self._previous_local_gray = local_gray

        region = detection.region
        change_fraction = detection.change_fraction
        materially_changed = region is not None

        if materially_changed:
            self._pending_region = (
                region
                if self._pending_region is None
                else self._pending_region.merge(region)
            )
            if change_fraction > self._pending_change_fraction:
                self._pending_change_fraction = change_fraction
                self._pending_discovery = detection.discovery
                self._pending_peak_frame = frame.copy()
                self._pending_peak_timestamp = timestamp
                self._pending_peak_frame_index = frame_index
            self._stable_count = 0
            if self._active_since is None:
                self._active_since = timestamp
            if (
                timestamp - self._active_since >= self.config.max_active_seconds
                and self._can_emit(timestamp)
            ):
                return self._emit_pending(
                    frame, timestamp, frame_index, goal, "active_timeout"
                )
            return None

        if self._pending_region is None:
            return None

        self._stable_count += 1
        if self._stable_count < self.config.stable_frames:
            return None
        if not self._can_emit(timestamp):
            return None
        return self._emit_pending(
            frame, timestamp, frame_index, goal, "change_stable"
        )

    def verify_after_action(
        self,
        before_frame: np.ndarray,
        after_frame: np.ndarray,
        timestamp: float,
        *,
        goal: str,
        action: str,
        expected_result: str,
        frame_index: int | None = None,
    ) -> GatewayObservation:
        """Force an observation after an action, including visible non-change."""

        for name, frame in (("before_frame", before_frame), ("after_frame", after_frame)):
            if frame.ndim != 3 or frame.shape[2] != 3:
                raise ValueError(f"{name} must be a BGR image with three channels")
        if before_frame.shape != after_frame.shape:
            raise ValueError("before_frame and after_frame must have the same shape")
        if timestamp < 0:
            raise ValueError("timestamp cannot be negative")
        if not action.strip():
            raise ValueError("action cannot be empty")
        if not expected_result.strip():
            raise ValueError("expected_result cannot be empty")

        self.stats.frames_seen += 1
        before_gray, before_local_gray = _analysis_pair(before_frame, self.config)
        after_gray, after_local_gray = _analysis_pair(after_frame, self.config)
        detection = _detect_change(
            after_gray,
            before_gray,
            after_local_gray,
            before_local_gray,
            after_frame.shape[1],
            after_frame.shape[0],
            self.config,
        )
        self._previous_gray = after_gray
        self._previous_local_gray = after_local_gray
        self._clear_pending()
        return self._emit(
            after_frame,
            timestamp,
            frame_index,
            goal,
            reason="action_verification",
            change_fraction=detection.change_fraction,
            region=detection.region,
            discovery="forced",
            action=action,
            expected_result=expected_result,
            before_frame=before_frame,
        )

    def force_snapshot(
        self,
        frame: np.ndarray,
        timestamp: float,
        *,
        goal: str,
        frame_index: int | None = None,
        reason: str = "scheduled_baseline",
        discovery: str = "uniform",
        region: ChangeRegion | None = None,
    ) -> GatewayObservation:
        """Emit a scheduled full-frame observation for a reference method."""

        if frame.ndim != 3 or frame.shape[2] != 3:
            raise ValueError("frame must be a BGR image with three channels")
        if timestamp < 0:
            raise ValueError("timestamp cannot be negative")
        if not goal.strip():
            raise ValueError("goal cannot be empty")
        if region is not None and (
            region.frame_width != frame.shape[1]
            or region.frame_height != frame.shape[0]
        ):
            raise ValueError("region dimensions must match the source frame")
        self.stats.frames_seen += 1
        return self._emit(
            frame,
            timestamp,
            frame_index,
            goal,
            reason=reason,
            change_fraction=0.0,
            region=region,
            discovery=discovery,
        )

    def flush(
        self,
        frame: np.ndarray,
        timestamp: float,
        *,
        goal: str,
        frame_index: int | None = None,
    ) -> GatewayObservation | None:
        """Emit an unfinished transition so the end of a stream is not lost."""

        if self._pending_region is None:
            return None
        return self._emit_pending(frame, timestamp, frame_index, goal, "stream_end")

    def _can_emit(self, timestamp: float) -> bool:
        return (
            timestamp - self._last_event_time
            >= self.config.min_event_interval_seconds
        )

    def _emit_pending(
        self,
        frame: np.ndarray,
        timestamp: float,
        frame_index: int | None,
        goal: str,
        reason: str,
    ) -> GatewayObservation:
        region = self._pending_region
        change_fraction = self._pending_change_fraction
        discovery = self._pending_discovery
        peak_frame = self._pending_peak_frame
        peak_timestamp = self._pending_peak_timestamp
        peak_frame_index = self._pending_peak_frame_index
        self._clear_pending()
        return self._emit(
            frame,
            timestamp,
            frame_index,
            goal,
            reason=reason,
            change_fraction=change_fraction,
            region=region,
            discovery=discovery,
            peak_frame=peak_frame,
            peak_timestamp=peak_timestamp,
            peak_frame_index=peak_frame_index,
        )

    def _clear_pending(self) -> None:
        self._pending_region = None
        self._pending_change_fraction = 0.0
        self._pending_discovery = "global_fraction"
        self._pending_peak_frame = None
        self._pending_peak_timestamp = None
        self._pending_peak_frame_index = None
        self._active_since = None
        self._stable_count = 0

    def _emit(
        self,
        frame: np.ndarray,
        timestamp: float,
        frame_index: int | None,
        goal: str,
        *,
        reason: str,
        change_fraction: float,
        region: ChangeRegion | None,
        discovery: str = "global_fraction",
        peak_frame: np.ndarray | None = None,
        peak_timestamp: float | None = None,
        peak_frame_index: int | None = None,
        action: str | None = None,
        expected_result: str | None = None,
        before_frame: np.ndarray | None = None,
    ) -> GatewayObservation:
        images = _build_visual_inputs(
            frame, region, self.config, peak_frame, before_frame
        )
        event = PerceptionEvent(
            sequence=self._sequence,
            timestamp=timestamp,
            frame_index=frame_index,
            reason=reason,
            change_fraction=change_fraction,
            region=region,
            images=images,
            discovery=discovery,
            peak_timestamp=peak_timestamp,
            peak_frame_index=peak_frame_index,
            action=action,
            expected_result=expected_result,
        )
        self._sequence += 1
        self._last_event_time = timestamp
        self.stats.events_emitted += 1
        image_bytes = sum(len(image.jpeg) for image in images)
        image_pixels = sum(image.pixel_count for image in images)
        self.stats.prepared_image_bytes += image_bytes
        self.stats.prepared_image_pixels += image_pixels

        interpretation = None
        if self.interpreter is not None:
            self.stats.transmitted_image_bytes += image_bytes
            self.stats.transmitted_image_pixels += image_pixels
            self.stats.transmitted_image_patches_32px += sum(
                image.patch_count_32px for image in images
            )
            started = time.perf_counter()
            interpretation = self.interpreter.interpret(
                event, goal, self._last_interpretation
            )
            elapsed = time.perf_counter() - started
            if interpretation.latency_seconds <= 0:
                interpretation = replace(
                    interpretation,
                    latency_seconds=elapsed,
                )
            self._last_interpretation = interpretation
            self.stats.ai_calls += 1
            if (
                interpretation.input_tokens is not None
                and interpretation.output_tokens is not None
            ):
                self.stats.ai_calls_with_reported_usage += 1
                self.stats.reported_input_tokens += interpretation.input_tokens
                self.stats.reported_output_tokens += interpretation.output_tokens
                self.stats.reported_cached_input_tokens += (
                    interpretation.cached_input_tokens or 0
                )
                self.stats.reported_reasoning_output_tokens += (
                    interpretation.reasoning_output_tokens or 0
                )
            self.stats.ai_latency_seconds += interpretation.latency_seconds

        return GatewayObservation(event=event, interpretation=interpretation)


@dataclass(frozen=True)
class _ChangeDetection:
    region: ChangeRegion | None
    change_fraction: float
    discovery: str


def _detect_change(
    gray: np.ndarray,
    previous_gray: np.ndarray,
    local_gray: np.ndarray,
    previous_local_gray: np.ndarray,
    frame_width: int,
    frame_height: int,
    config: GatewayConfig,
) -> _ChangeDetection:
    global_mask = cv2.absdiff(gray, previous_gray) >= config.pixel_threshold
    global_fraction = float(np.mean(global_mask))
    local_mask = (
        cv2.absdiff(local_gray, previous_local_gray) >= config.pixel_threshold
    )
    if global_fraction >= config.min_changed_fraction:
        return _ChangeDetection(
            region=_region_from_mask(local_mask, frame_width, frame_height),
            change_fraction=global_fraction,
            discovery="global_fraction",
        )

    component_mask, component_pixels = _largest_component(local_mask)
    if component_pixels < config.min_local_component_pixels:
        return _ChangeDetection(None, global_fraction, "none")
    return _ChangeDetection(
        region=_region_from_mask(component_mask, frame_width, frame_height),
        change_fraction=float(component_pixels / local_mask.size),
        discovery="local_component",
    )


def _largest_component(mask: np.ndarray) -> tuple[np.ndarray, int]:
    count, labels, stats, _ = cv2.connectedComponentsWithStats(
        mask.astype(np.uint8), connectivity=8
    )
    if count <= 1:
        return np.zeros_like(mask, dtype=bool), 0
    areas = stats[1:, cv2.CC_STAT_AREA]
    label = int(np.argmax(areas)) + 1
    area = int(stats[label, cv2.CC_STAT_AREA])
    return labels == label, area


def _analysis_gray(frame: np.ndarray, max_width: int) -> np.ndarray:
    height, width = frame.shape[:2]
    if width > max_width:
        scale = max_width / width
        frame = cv2.resize(
            frame,
            (max_width, max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    return cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)


def _analysis_pair(
    frame: np.ndarray, config: GatewayConfig
) -> tuple[np.ndarray, np.ndarray]:
    gray = _analysis_gray(frame, config.analysis_width)
    if (
        config.local_analysis_width == config.analysis_width
        or frame.shape[1] <= config.analysis_width
    ):
        return gray, gray
    return gray, _analysis_gray(frame, config.local_analysis_width)


def _region_from_mask(
    mask: np.ndarray, frame_width: int, frame_height: int
) -> ChangeRegion | None:
    points = cv2.findNonZero(mask.astype(np.uint8))
    if points is None:
        return None
    x, y, width, height = cv2.boundingRect(points)
    analysis_height, analysis_width = mask.shape
    scale_x = frame_width / analysis_width
    scale_y = frame_height / analysis_height
    source_x = max(0, int(np.floor(x * scale_x)))
    source_y = max(0, int(np.floor(y * scale_y)))
    source_x2 = min(frame_width, int(np.ceil((x + width) * scale_x)))
    source_y2 = min(frame_height, int(np.ceil((y + height) * scale_y)))
    return ChangeRegion(
        x=source_x,
        y=source_y,
        width=max(1, source_x2 - source_x),
        height=max(1, source_y2 - source_y),
        frame_width=frame_width,
        frame_height=frame_height,
    )


def _build_visual_inputs(
    frame: np.ndarray,
    region: ChangeRegion | None,
    config: GatewayConfig,
    peak_frame: np.ndarray | None = None,
    before_frame: np.ndarray | None = None,
) -> tuple[VisualInput, ...]:
    if region is None:
        images = [_encode_visual("context", frame, config.detail_width, config)]
        if before_frame is not None and before_frame.shape == frame.shape:
            images.insert(
                0,
                _encode_visual(
                    "before_action", before_frame, config.detail_width, config
                ),
            )
        return tuple(images)

    expanded = region.expanded(config.crop_margin)
    if expanded.area_ratio >= 0.60:
        images = [_encode_visual("detail", frame, config.detail_width, config)]
    else:
        context = _encode_visual("context", frame, config.context_width, config)
        crop = _crop_region(frame, expanded)
        detail = _encode_visual("detail", crop, config.detail_width, config)
        images = [context, detail]

    if before_frame is not None and before_frame.shape == frame.shape:
        before_crop = (
            before_frame
            if expanded.area_ratio >= 0.60
            else _crop_region(before_frame, expanded)
        )
        images.insert(
            0,
            _encode_visual(
                "before_action", before_crop, config.detail_width, config
            ),
        )

    if (
        peak_frame is not None
        and peak_frame.shape == frame.shape
        and _visual_difference(peak_frame, frame)
        >= config.peak_image_min_difference
    ):
        peak_crop = (
            peak_frame
            if expanded.area_ratio >= 0.60
            else _crop_region(peak_frame, expanded)
        )
        images.append(
            _encode_visual("change_peak", peak_crop, config.detail_width, config)
        )
    return tuple(images)


def _crop_region(frame: np.ndarray, region: ChangeRegion) -> np.ndarray:
    return frame[
        region.y : region.y + region.height,
        region.x : region.x + region.width,
    ]


def _visual_difference(left: np.ndarray, right: np.ndarray) -> float:
    left_gray = _analysis_gray(left, 96)
    right_gray = _analysis_gray(right, 96)
    return float(np.mean(cv2.absdiff(left_gray, right_gray)) / 255.0)


def _encode_visual(
    role: str, frame: np.ndarray, max_width: int, config: GatewayConfig
) -> VisualInput:
    height, width = frame.shape[:2]
    encoded_frame = frame
    if width > max_width:
        scale = max_width / width
        encoded_frame = cv2.resize(
            frame,
            (max_width, max(1, int(round(height * scale)))),
            interpolation=cv2.INTER_AREA,
        )
    ok, encoded = cv2.imencode(
        ".jpg", encoded_frame, [cv2.IMWRITE_JPEG_QUALITY, config.jpeg_quality]
    )
    if not ok:
        raise RuntimeError("failed to encode perception image")
    encoded_height, encoded_width = encoded_frame.shape[:2]
    return VisualInput(
        role=role,
        jpeg=encoded.tobytes(),
        width=encoded_width,
        height=encoded_height,
    )
