from __future__ import annotations

import queue
import threading
import time
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

from .gateway import (
    ChangeRegion,
    GatewayConfig,
    GatewayObservation,
    PerceptionEvent,
    PerceptionGateway,
    SemanticInterpreter,
    SemanticResult,
)


@dataclass(frozen=True)
class StreamingConfig:
    ring_buffer_frames: int = 8
    max_pending_events: int = 16
    max_interpreter_retries: int = 1
    event_history_size: int = 128

    def validate(self) -> None:
        if self.ring_buffer_frames <= 0:
            raise ValueError("ring_buffer_frames must be greater than zero")
        if self.max_pending_events <= 0:
            raise ValueError("max_pending_events must be greater than zero")
        if self.max_interpreter_retries < 0:
            raise ValueError("max_interpreter_retries cannot be negative")
        if self.event_history_size <= 0:
            raise ValueError("event_history_size must be greater than zero")


@dataclass(frozen=True)
class StreamingResult:
    event: PerceptionEvent
    interpretation: SemanticResult | None
    error: str | None
    attempts: int
    completed_monotonic: float

    @property
    def succeeded(self) -> bool:
        return self.error is None

    def to_dict(self) -> dict[str, object]:
        return {
            "event": self.event.to_dict(),
            "interpretation": (
                self.interpretation.to_dict() if self.interpretation else None
            ),
            "error": self.error,
            "attempts": self.attempts,
            "succeeded": self.succeeded,
            "completed_monotonic": self.completed_monotonic,
        }


@dataclass
class StreamingStats:
    frames_submitted: int = 0
    detector_events: int = 0
    events_enqueued: int = 0
    events_dropped: int = 0
    retry_requests: int = 0
    detail_requests: int = 0
    action_verifications: int = 0
    interpretation_attempts: int = 0
    interpretations_completed: int = 0
    interpretations_failed: int = 0
    detector_seconds: float = 0.0
    max_observed_queue_depth: int = 0

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class _FrameSample:
    frame: np.ndarray
    timestamp: float
    frame_index: int | None


@dataclass(frozen=True)
class _QueuedEvent:
    event: PerceptionEvent
    goal: str
    attempt: int


_STOP = object()


class StreamingPerceptionGateway:
    """Run deterministic frame gating without blocking on semantic inference."""

    def __init__(
        self,
        *,
        goal: str,
        interpreter: SemanticInterpreter,
        gateway_config: GatewayConfig | None = None,
        streaming_config: StreamingConfig | None = None,
    ) -> None:
        if not goal.strip():
            raise ValueError("goal cannot be empty")
        self.goal = goal
        self.gateway_config = gateway_config or GatewayConfig()
        self.gateway_config.validate()
        self.streaming_config = streaming_config or StreamingConfig()
        self.streaming_config.validate()
        self.interpreter = interpreter
        self.detector = PerceptionGateway(self.gateway_config)
        self.stats = StreamingStats()

        self._frames: deque[_FrameSample] = deque(
            maxlen=self.streaming_config.ring_buffer_frames
        )
        self._event_history: OrderedDict[int, tuple[PerceptionEvent, str]] = (
            OrderedDict()
        )
        self._pending: queue.Queue[_QueuedEvent | object] = queue.Queue(
            maxsize=self.streaming_config.max_pending_events
        )
        self._results: queue.Queue[StreamingResult] = queue.Queue()
        self._lock = threading.RLock()
        self._idle = threading.Condition(self._lock)
        self._outstanding = 0
        self._closed = False
        self._previous_interpretation: SemanticResult | None = None
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="signum-semantic-worker",
            daemon=True,
        )
        self._worker.start()

    def submit_frame(
        self,
        frame: np.ndarray,
        timestamp: float,
        *,
        frame_index: int | None = None,
    ) -> GatewayObservation | None:
        """Process one frame synchronously and enqueue any event asynchronously."""

        self._ensure_open()
        started = time.perf_counter()
        with self._lock:
            self._frames.append(
                _FrameSample(frame.copy(), timestamp, frame_index)
            )
            observation = self.detector.observe_frame(
                frame,
                timestamp,
                goal=self.goal,
                frame_index=frame_index,
            )
            self.stats.frames_submitted += 1
            self.stats.detector_seconds += time.perf_counter() - started
            if observation is not None:
                self.stats.detector_events += 1
                self._remember_and_enqueue(observation.event, self.goal)
            return observation

    def request_detail(
        self,
        *,
        x: float,
        y: float,
        width: float,
        height: float,
        goal: str | None = None,
    ) -> GatewayObservation:
        """Request a higher-resolution crop from the most recent frame."""

        self._ensure_open()
        with self._lock:
            sample = self._latest_frame()
            frame_height, frame_width = sample.frame.shape[:2]
            region = _normalized_region(
                x,
                y,
                width,
                height,
                frame_width,
                frame_height,
            )
            request_goal = goal.strip() if goal is not None else self.goal
            if not request_goal:
                raise ValueError("goal cannot be empty")
            observation = self.detector.force_snapshot(
                sample.frame,
                sample.timestamp,
                goal=request_goal,
                frame_index=sample.frame_index,
                reason="detail_request",
                discovery="requested",
                region=region,
            )
            self.stats.detail_requests += 1
            self.stats.detector_events += 1
            self._remember_and_enqueue(observation.event, request_goal)
            return observation

    def verify_after_action(
        self,
        before_frame: np.ndarray,
        after_frame: np.ndarray,
        timestamp: float,
        *,
        action: str,
        expected_result: str,
        frame_index: int | None = None,
        goal: str | None = None,
    ) -> GatewayObservation:
        self._ensure_open()
        with self._lock:
            request_goal = goal.strip() if goal is not None else self.goal
            if not request_goal:
                raise ValueError("goal cannot be empty")
            self._frames.append(
                _FrameSample(after_frame.copy(), timestamp, frame_index)
            )
            observation = self.detector.verify_after_action(
                before_frame,
                after_frame,
                timestamp,
                goal=request_goal,
                action=action,
                expected_result=expected_result,
                frame_index=frame_index,
            )
            self.stats.action_verifications += 1
            self.stats.detector_events += 1
            self._remember_and_enqueue(observation.event, request_goal)
            return observation

    def retry_event(self, sequence: int) -> bool:
        """Requeue a retained event after an explicit controller request."""

        self._ensure_open()
        with self._lock:
            retained = self._event_history.get(sequence)
            if retained is None:
                return False
            event, goal = retained
            self.stats.retry_requests += 1
            return self._enqueue(_QueuedEvent(event, goal, 1))

    def poll_results(self, max_items: int | None = None) -> list[StreamingResult]:
        if max_items is not None and max_items < 0:
            raise ValueError("max_items cannot be negative")
        results: list[StreamingResult] = []
        while max_items is None or len(results) < max_items:
            try:
                results.append(self._results.get_nowait())
            except queue.Empty:
                break
        return results

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        if timeout is not None and timeout < 0:
            raise ValueError("timeout cannot be negative")
        deadline = None if timeout is None else time.monotonic() + timeout
        with self._idle:
            while self._outstanding:
                remaining = None if deadline is None else deadline - time.monotonic()
                if remaining is not None and remaining <= 0:
                    return False
                self._idle.wait(remaining)
        return True

    def close(self, *, wait: bool = True, timeout: float | None = None) -> bool:
        with self._lock:
            if self._closed and not self._worker.is_alive():
                return not self._worker.is_alive()
            self._closed = True
        idle = self.wait_until_idle(timeout) if wait else False
        try:
            self._pending.put_nowait(_STOP)
        except queue.Full:
            if wait:
                self._pending.put(_STOP)
            else:
                return False
        if wait:
            self._worker.join(timeout)
        return idle and not self._worker.is_alive()

    def stats_dict(self) -> dict[str, Any]:
        with self._lock:
            return {
                **self.stats.to_dict(),
                "current_queue_depth": self._pending.qsize(),
                "outstanding_events": self._outstanding,
                "retained_frames": len(self._frames),
                "retained_events": len(self._event_history),
                "closed": self._closed,
            }

    def __enter__(self) -> StreamingPerceptionGateway:
        return self

    def __exit__(self, *args: object) -> None:
        self.close(wait=True)

    def _remember_and_enqueue(self, event: PerceptionEvent, goal: str) -> bool:
        self._event_history[event.sequence] = (event, goal)
        self._event_history.move_to_end(event.sequence)
        while len(self._event_history) > self.streaming_config.event_history_size:
            self._event_history.popitem(last=False)
        return self._enqueue(_QueuedEvent(event, goal, 1))

    def _enqueue(self, item: _QueuedEvent) -> bool:
        try:
            self._pending.put_nowait(item)
        except queue.Full:
            self.stats.events_dropped += 1
            self._results.put(
                StreamingResult(
                    event=item.event,
                    interpretation=None,
                    error="semantic queue full; event was not interpreted",
                    attempts=0,
                    completed_monotonic=time.monotonic(),
                )
            )
            return False
        self.stats.events_enqueued += 1
        self._outstanding += 1
        self.stats.max_observed_queue_depth = max(
            self.stats.max_observed_queue_depth,
            self._pending.qsize(),
        )
        return True

    def _worker_loop(self) -> None:
        while True:
            item = self._pending.get()
            try:
                if item is _STOP:
                    return
                assert isinstance(item, _QueuedEvent)
                self._interpret(item)
            finally:
                self._pending.task_done()

    def _interpret(self, item: _QueuedEvent) -> None:
        with self._lock:
            previous = self._previous_interpretation
        attempt = item.attempt
        while True:
            with self._lock:
                self.stats.interpretation_attempts += 1
            try:
                interpretation = self.interpreter.interpret(
                    item.event,
                    item.goal,
                    previous,
                )
            except Exception as error:
                if attempt <= self.streaming_config.max_interpreter_retries:
                    attempt += 1
                    continue
                result = StreamingResult(
                    event=item.event,
                    interpretation=None,
                    error=f"{type(error).__name__}: {error}",
                    attempts=attempt,
                    completed_monotonic=time.monotonic(),
                )
                with self._idle:
                    self.stats.interpretations_failed += 1
                    self._outstanding -= 1
                    self._results.put(result)
                    self._idle.notify_all()
                return
            break

        result = StreamingResult(
            event=item.event,
            interpretation=interpretation,
            error=None,
            attempts=attempt,
            completed_monotonic=time.monotonic(),
        )
        with self._idle:
            self._previous_interpretation = interpretation
            self.stats.interpretations_completed += 1
            self._outstanding -= 1
            self._results.put(result)
            self._idle.notify_all()

    def _latest_frame(self) -> _FrameSample:
        if not self._frames:
            raise RuntimeError("no frame has been submitted")
        return self._frames[-1]

    def _ensure_open(self) -> None:
        with self._lock:
            if self._closed:
                raise RuntimeError("streaming gateway is closed")


def _normalized_region(
    x: float,
    y: float,
    width: float,
    height: float,
    frame_width: int,
    frame_height: int,
) -> ChangeRegion:
    values = (x, y, width, height)
    if not all(np.isfinite(value) for value in values):
        raise ValueError("detail region must contain finite values")
    if x < 0 or y < 0 or width <= 0 or height <= 0:
        raise ValueError("detail region must have positive normalized bounds")
    if x + width > 1 or y + height > 1:
        raise ValueError("detail region must remain inside the frame")
    x1 = min(frame_width - 1, int(np.floor(x * frame_width)))
    y1 = min(frame_height - 1, int(np.floor(y * frame_height)))
    x2 = min(frame_width, max(x1 + 1, int(np.ceil((x + width) * frame_width))))
    y2 = min(frame_height, max(y1 + 1, int(np.ceil((y + height) * frame_height))))
    return ChangeRegion(
        x=x1,
        y=y1,
        width=x2 - x1,
        height=y2 - y1,
        frame_width=frame_width,
        frame_height=frame_height,
    )
