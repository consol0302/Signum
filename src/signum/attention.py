"""Experimental, CPU-only attention policy over Signum's existing detector.

No model is called here. A controller consumes evidence packets, then explicitly
acknowledges completed interpretations. Capture, delivery and interpretation are
separate operations; enqueueing an image never makes a belief current.
"""
from __future__ import annotations

import hashlib
import math
import threading
from collections import OrderedDict, deque
from dataclasses import asdict, dataclass, field, replace
from typing import Callable

import cv2
import numpy as np

from .gateway import (
    ChangeRegion, GatewayConfig, PerceptionEvent, PerceptionGateway,
    SemanticResult, VisualInput, _analysis_pair,
    _detect_change, _encode_visual, _largest_component, _region_from_mask,
)


@dataclass(frozen=True)
class WatchRegion:
    """Normalized priority region, never a mask that disables the global guard."""
    x: float
    y: float
    width: float
    height: float

    def __post_init__(self) -> None:
        values = (self.x, self.y, self.width, self.height)
        if not all(math.isfinite(v) for v in values):
            raise ValueError("region coordinates must be finite")
        if (min(self.x, self.y) < 0 or min(self.width, self.height) <= 0
                or self.x + self.width > 1 or self.y + self.height > 1):
            raise ValueError("region must fit inside the normalized image")

    def pixels(self, frame: np.ndarray) -> ChangeRegion:
        h, w = frame.shape[:2]
        x, y = int(self.x * w), int(self.y * h)
        return ChangeRegion(x, y, max(1, math.ceil((self.x + self.width) * w) - x),
                            max(1, math.ceil((self.y + self.height) * h) - y), w, h)


@dataclass(frozen=True)
class ObservationContract:
    goal: str
    version: str = "initial"
    watch_regions: tuple[WatchRegion, ...] = ()
    recheck_after_seconds: float = 30.0
    action_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.goal, str) or not isinstance(self.version, str) or not self.goal.strip() or not self.version.strip():
            raise ValueError("goal and version cannot be empty")
        if (not math.isfinite(self.recheck_after_seconds)
                or self.recheck_after_seconds <= 0):
            raise ValueError("recheck_after_seconds must be positive and finite")
        if len(self.watch_regions) > 8 or not all(
            isinstance(r, WatchRegion) for r in self.watch_regions
        ):
            raise ValueError("watch_regions must contain at most eight WatchRegions")
        object.__setattr__(self, "watch_regions", tuple(self.watch_regions))
        if self.action_id is not None and not self.action_id.strip():
            raise ValueError("action_id cannot be blank")

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> ObservationContract:
        """Parse the contract attached to an EXISTING agent response; no extra call."""
        if not isinstance(data, dict):
            raise ValueError("contract must be an object")
        allowed = {"goal", "version", "watch_regions", "recheck_after_seconds", "action_id"}
        if set(data) - allowed or "goal" not in data:
            raise ValueError("unknown contract fields or missing goal")
        values = dict(data)
        try:
            values["watch_regions"] = tuple(WatchRegion(**r) for r in values.get("watch_regions", ()))
            return cls(**values)
        except (TypeError, AttributeError) as error:
            raise ValueError("invalid observation contract") from error


@dataclass(frozen=True)
class AttentionConfig:
    evidence_max_bytes: int = 64 * 1024 * 1024
    evidence_ttl_seconds: float = 120.0
    max_frame_bytes: int = 24 * 1024 * 1024
    max_pending: int = 16
    history_size: int = 128
    history_max_bytes: int = 32 * 1024 * 1024
    delivery_timeout_seconds: float = 60.0
    color_guard: bool = True
    eager_changes: bool = False

    def __post_init__(self) -> None:
        for name in ("evidence_max_bytes", "max_frame_bytes", "max_pending",
                     "history_size", "history_max_bytes"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"{name} must be a positive integer")
        if self.history_size < self.max_pending:
            raise ValueError("history_size cannot be smaller than max_pending")
        for name in ("evidence_ttl_seconds", "delivery_timeout_seconds"):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be positive and finite")


@dataclass(frozen=True)
class SourceFrame:
    role: str
    timestamp: float
    frame_index: int | None
    frame: np.ndarray = field(repr=False, compare=False)


class EvidenceUnavailable(LookupError):
    """The requested original was expired, evicted or never retained."""


class EvidenceStore:
    """FIFO byte/age-bounded original frames. Never substitutes a newer frame."""
    def __init__(self, max_bytes: int, ttl_seconds: float) -> None:
        if max_bytes <= 0 or not math.isfinite(ttl_seconds) or ttl_seconds <= 0:
            raise ValueError("invalid evidence limits")
        self.max_bytes, self.ttl_seconds = max_bytes, ttl_seconds
        self.bytes_used = 0
        self._items: OrderedDict[int, tuple[float, tuple[SourceFrame, ...]]] = OrderedDict()

    def expire(self, now: float) -> None:
        for key, (created, _) in list(self._items.items()):
            if now - created >= self.ttl_seconds:
                self.discard(key)

    def discard(self, key: int) -> None:
        item = self._items.pop(key, None)
        if item is not None:
            self.bytes_used -= sum(s.frame.nbytes for s in item[1])

    def put(self, key: int, sources: tuple[SourceFrame, ...], now: float) -> bool:
        self.expire(now)
        self.discard(key)
        size = sum(s.frame.nbytes for s in sources)
        if size > self.max_bytes:
            return False
        while self.bytes_used + size > self.max_bytes:
            self.discard(next(iter(self._items)))
        owned = []
        for source in sources:
            image = source.frame.copy()
            image.flags.writeable = False
            owned.append(replace(source, frame=image))
        self._items[key] = (now, tuple(owned))
        self.bytes_used += size
        return True

    def get(self, key: int, role: str, now: float) -> SourceFrame:
        self.expire(now)
        item = self._items.get(key)
        if item is not None:
            for source in item[1]:
                if source.role == role:
                    # A copy prevents a caller from changing retained evidence.
                    return replace(source, frame=source.frame.copy())
        raise EvidenceUnavailable(f"event {key} source {role!r} unavailable or expired")


@dataclass(frozen=True)
class AttentionPacket:
    event: PerceptionEvent
    goal: str
    contract_version: str
    action_id: str | None
    epoch: int
    visual_revision: int
    priority: int
    due_at: float
    source_event_id: int
    source_role: str = "current"
    historical: bool = False

    def to_dict(self) -> dict[str, object]:
        return {"event": self.event.to_dict(), "goal": self.goal,
                "contract_version": self.contract_version, "action_id": self.action_id,
                "epoch": self.epoch, "visual_revision": self.visual_revision,
                "priority": self.priority, "due_at": self.due_at,
                "source_event_id": self.source_event_id,
                "source_role": self.source_role, "historical": self.historical}


@dataclass(frozen=True)
class Acknowledgement:
    sequence: int
    accepted_as_current: bool
    reason: str


@dataclass
class _Record:
    packet: AttentionPacket
    signature: tuple[np.ndarray, ...]
    status: str = "queued"
    delivered: bool = False
    result_received: bool = False
    interpretation: SemanticResult | None = None

    @property
    def nbytes(self) -> int:
        return (sum(s.nbytes for s in self.signature)
                + sum(len(i.jpeg) for i in self.packet.event.images))


class _SourceDetector(PerceptionGateway):
    """Retain the exact inputs at the existing event-emission boundary."""
    sources: tuple[SourceFrame, ...] = ()

    @property
    def has_pending_change(self) -> bool:
        return self._pending_region is not None

    def _emit(self, frame, timestamp, frame_index, goal, **kwargs):
        observation = super()._emit(frame, timestamp, frame_index, goal, **kwargs)
        sources = [SourceFrame("current", timestamp, frame_index, frame)]
        peak = kwargs.get("peak_frame")
        if peak is not None:
            sources.append(SourceFrame("peak", kwargs["peak_timestamp"],
                                       kwargs["peak_frame_index"], peak))
        before = kwargs.get("before_frame")
        if before is not None:
            # The caller supplies the exact before timestamp in verify_after_action.
            sources.append(SourceFrame("before", timestamp, None, before))
        self.sources = tuple(sources)
        return observation


# A cost function must be provided by the controller and calibrated externally.
# Its return value is explicitly an estimate, never inferred billed tokens.
ImageCost = Callable[[tuple[VisualInput, ...]], float]


class AttentionGateway:
    """Thread-safe evidence-only path; external agents own semantic inference.

    Time parameters use one nondecreasing source timeline. Deadlines advance on
    submit_frame/tick, not in a hidden timer. Missing capture requires tick.
    The original sampler and StreamingPerceptionGateway remain unchanged.
    """
    def __init__(self, contract: ObservationContract, *,
                 gateway_config: GatewayConfig | None = None,
                 config: AttentionConfig | None = None,
                 image_cost: ImageCost | None = None) -> None:
        self.contract = contract
        self.gateway_config = gateway_config or GatewayConfig()
        self.gateway_config.validate()
        if self.gateway_config.pixel_threshold <= 0:
            raise ValueError("attention requires a strictly positive pixel threshold")
        self.config = config or AttentionConfig()
        self.image_cost = image_cost
        self._lock = threading.RLock()
        self._detector = _SourceDetector(self.gateway_config)
        self.evidence = EvidenceStore(self.config.evidence_max_bytes,
                                      self.config.evidence_ttl_seconds)
        self._records: OrderedDict[int, _Record] = OrderedDict()
        self._outbox: dict[int, AttentionPacket] = {}
        self._notices: deque[dict[str, object]] = deque(maxlen=self.config.history_size)
        self._latest: SourceFrame | None = None
        self._scene: tuple[np.ndarray, ...] | None = None
        self._committed: tuple[np.ndarray, ...] | None = None
        self._current: int | None = None
        self._sequence = self._epoch = self._revision = 0
        self._now = 0.0
        self._next_check = 0.0
        self._force_reason: str | None = None
        self._repeat: dict[str, object] | None = None
        self.stats = {"frames": 0, "packets": 0, "delivered": 0, "batches": 0,
                      "failed": 0, "stale_results": 0, "duplicate_pending": 0,
                      "evidence_not_retained": 0, "notice_overflow": 0,
                      "delivered_image_bytes": 0, "delivered_image_pixels": 0,
                      "repeat_suppressed_frames": 0, "semantic_responses": 0, "responses_with_usage": 0,
                      "reported_input_tokens": 0, "reported_cached_input_tokens": 0,
                      "reported_output_tokens": 0, "reported_reasoning_output_tokens": 0}

    def _time(self, now: float) -> None:
        if not math.isfinite(now) or now < self._now:
            raise ValueError("timestamps must be finite, nonnegative and nondecreasing")
        self._now = now
        self.evidence.expire(now)
        if self._repeat is not None and now >= self._repeat["expires_at"]:
            self._invalidate("repeat_expired")
        for key, record in list(self._records.items()):
            if record.status in ("queued", "inflight") and now >= record.packet.due_at:
                self._fail(key, "delivery_timeout")

    def tick(self, now: float) -> bool:
        """Advance expiry without inventing a fresh screenshot; True requests capture."""
        with self._lock:
            self._time(now)
            return (self._force_reason is not None or self._latest is None or now >= self._next_check
                    or now - self._latest.timestamp >= self.contract.recheck_after_seconds)

    def _validate_frame(self, frame: np.ndarray) -> None:
        if (not isinstance(frame, np.ndarray) or frame.dtype != np.uint8
                or frame.ndim != 3 or frame.shape[2] != 3 or min(frame.shape[:2]) < 1):
            raise ValueError("frame must be a nonempty uint8 BGR image")
        if frame.nbytes > self.config.max_frame_bytes:
            raise ValueError("frame exceeds max_frame_bytes")

    def _signature(self, frame: np.ndarray) -> tuple[np.ndarray, ...]:
        gray, local = _analysis_pair(frame, self.gateway_config)
        color = cv2.resize(frame, (local.shape[1], local.shape[0]),
                           interpolation=cv2.INTER_AREA)
        regions = []
        for watch in self.contract.watch_regions:
            r = watch.pixels(frame)
            crop = frame[r.y:r.y+r.height, r.x:r.x+r.width]
            roi_gray, roi_local = _analysis_pair(crop, self.gateway_config)
            roi_color = cv2.resize(crop, (roi_local.shape[1], roi_local.shape[0]), interpolation=cv2.INTER_AREA)
            regions.extend((roi_gray, roi_local, roi_color))
        return (gray, local, color, *regions)

    def _change(self, sig: tuple[np.ndarray, ...], reference: tuple[np.ndarray, ...],
                frame: np.ndarray) -> tuple[ChangeRegion | None, bool]:
        h, w = frame.shape[:2]
        detection = _detect_change(sig[0], reference[0], sig[1], reference[1],
                                   w, h, self.gateway_config)
        region = detection.region
        if self.config.color_guard:
            mask = np.max(cv2.absdiff(sig[2], reference[2]), axis=2) >= self.gateway_config.pixel_threshold
            component, count = _largest_component(mask)
            if count >= self.gateway_config.min_local_component_pixels:
                colored = _region_from_mask(component, w, h)
                if colored is not None:
                    region = colored if region is None else region.merge(colored)
        watched = False
        for index, watch in enumerate(self.contract.watch_regions):
            roi = watch.pixels(frame)
            i = 3 + 3 * index
            found = _detect_change(sig[i], reference[i], sig[i+1], reference[i+1],
                                   roi.width, roi.height, self.gateway_config).region
            if self.config.color_guard:
                color_mask = np.max(cv2.absdiff(sig[i+2], reference[i+2]), axis=2) >= self.gateway_config.pixel_threshold
                component, count = _largest_component(color_mask)
                if count >= self.gateway_config.min_local_component_pixels:
                    color_region = _region_from_mask(component, roi.width, roi.height)
                    if color_region is not None:
                        found = color_region if found is None else found.merge(color_region)
            if found is not None:
                watched = True
                translated = ChangeRegion(roi.x + found.x, roi.y + found.y,
                                          found.width, found.height, w, h)
                region = translated if region is None else region.merge(translated)
        return region, watched

    def set_contract(self, contract: ObservationContract) -> None:
        """A new question/goal is an event even when all pixels are unchanged."""
        with self._lock:
            if contract == self.contract:
                return
            self._invalidate("contract_changed")
            self.contract = contract

    def _invalidate(self, reason: str) -> None:
        # Preserve an unfinished old-context peak BEFORE invalidating its context.
        if self._latest is not None and self._detector.has_pending_change:
            self.flush()
        self._epoch += 1
        self._current = None
        self._repeat = None
        self._committed = self._scene = None
        self._force_reason = reason
        self._detector = _SourceDetector(self.gateway_config)

    def submit_frame(self, frame: np.ndarray, timestamp: float, *,
                     frame_index: int | None = None) -> AttentionPacket | None:
        with self._lock:
            self._validate_frame(frame)
            if frame_index is not None and (not isinstance(frame_index, int) or isinstance(frame_index, bool) or frame_index < 0):
                raise ValueError("frame_index must be a nonnegative integer")
            self._time(timestamp)
            owned = frame.copy()
            if self._latest is not None and self._latest.frame.shape != owned.shape:
                self._invalidate("layout_changed")
            self._latest = SourceFrame("current", timestamp, frame_index, owned)
            self.stats["frames"] += 1
            sig = self._signature(owned)
            if self._repeat is not None:
                repeat = self._repeat
                fingerprint = hashlib.sha256(owned.tobytes()).hexdigest()
                if (timestamp < self._next_check and repeat["remaining_frames"] > 0
                        and fingerprint in repeat["fingerprints"]):
                    repeat["remaining_frames"] -= 1
                    repeat["suppressed_frames"] += 1
                    self.stats["repeat_suppressed_frames"] += 1
                    self._scene = sig
                    # No pending unreviewed events were allowed at approval.
                    self._detector = _SourceDetector(self.gateway_config)
                    return None
                self._invalidate("repeat_broken_or_recheck")
            region, watched = (None, False) if self._scene is None else self._change(sig, self._scene, owned)
            changed = self._scene is None or region is not None
            if changed:
                self._revision += 1
                self._scene = sig
                self._current = None
            # The acknowledged anchor is not advanced on enqueue or delivery.
            committed_region = None
            if self._committed is not None:
                committed_region, _ = self._change(sig, self._committed, owned)
                if committed_region is not None:
                    self._current = None
            observation = self._detector.observe_frame(owned, timestamp,
                goal=self.contract.goal, frame_index=frame_index)
            force = self._force_reason
            if force is not None:
                self._force_reason = None
                assert observation is not None  # detector was reset on invalidation
                observation = replace(observation, event=replace(observation.event, reason=force))
            elif (observation is None and changed and region is not None
                  and (self.config.eager_changes or watched or not self._detector.has_pending_change)):
                # Additional (cumulative, watched-local or color) evidence is kept
                # immediately, including one-frame events that never become stable.
                observation = self._detector.force_snapshot(owned, timestamp,
                    goal=self.contract.goal, frame_index=frame_index,
                    reason="belief_change", discovery="attention", region=region)
            elif observation is None and timestamp >= self._next_check:
                if self._has_pending_current():
                    self.stats["duplicate_pending"] += 1
                    return None
                observation = self._detector.force_snapshot(owned, timestamp,
                    goal=self.contract.goal, frame_index=frame_index,
                    reason="deadline", discovery="scheduled_recheck")
            if observation is None:
                return None
            event = observation.event
            # Suppress only a pending duplicate of the SAME scene revision.
            # A -> B -> A is a new revision, never deduplicated against old A.
            if (event.reason in ("change_stable", "belief_change")
                    and not any(i.role == "change_peak" for i in event.images)
                    and self._has_seen_current()):
                self.stats["duplicate_pending"] += 1
                return None
            priority = 0 if watched or event.reason in ("deadline", "contract_changed", "layout_changed") else 1
            return self._register(event, self._detector.sources, sig, priority=priority)

    def approve_repeat(self, event_ids: tuple[int, ...], *,
                       valid_for_seconds: float = 10.0, max_suppressed_frames: int = 300) -> None:
        """Controller asserts reviewed states are equivalent for the current goal.

        ONLY exact full-frame states already observed are recognized. Any unseen
        pixel pattern, new goal/action, expiry or frame limit cancels suppression.
        No model call or semantic classification is performed by this method.
        """
        if (not math.isfinite(valid_for_seconds) or valid_for_seconds <= 0
                or not isinstance(max_suppressed_frames, int) or max_suppressed_frames <= 0):
            raise ValueError("repeat limits must be positive and finite")
        if not 2 <= len(set(event_ids)) <= 8:
            raise ValueError("approve between two and eight distinct event IDs")
        with self._lock:
            if any(r.status in ("queued", "inflight") for r in self._records.values()):
                raise ValueError("finish pending observations before approving a repeat")
            fingerprints, states = set(), set()
            for key in event_ids:
                record = self._records.get(key)
                if (record is None or record.status != "completed" or record.interpretation is None
                        or record.packet.epoch != self._epoch or record.packet.historical
                        or record.packet.event.action is not None
                        or record.interpretation.verification != "not_applicable"):
                    raise ValueError("repeat approval requires reviewed passive evidence in this context")
                source = self.evidence.get(record.packet.source_event_id, "current", self._now)
                fingerprints.add(hashlib.sha256(source.frame.tobytes()).hexdigest())
                states.add(record.interpretation.state)
            if len(fingerprints) < 2 or len(states) != 1 or self._latest is None:
                raise ValueError("repeat states must be distinct images with the same reviewed state")
            if hashlib.sha256(self._latest.frame.tobytes()).hexdigest() not in fingerprints:
                raise ValueError("the current frame must be one of the reviewed repeat states")
            self._repeat = {"event_ids": list(event_ids), "fingerprints": sorted(fingerprints),
                            "expires_at": self._now + valid_for_seconds,
                            "remaining_frames": max_suppressed_frames, "suppressed_frames": 0}

    def _has_pending_current(self) -> bool:
        return any(r.status in ("queued", "inflight") and not r.packet.historical
                   and r.packet.epoch == self._epoch
                   and r.packet.visual_revision == self._revision
                   for r in self._records.values())

    def _has_seen_current(self) -> bool:
        return any(r.status in ("queued", "inflight", "completed") and not r.packet.historical
                   and r.packet.epoch == self._epoch
                   and r.packet.visual_revision == self._revision
                   for r in self._records.values())

    def _visuals(self, sources: tuple[SourceFrame, ...], event: PerceptionEvent) -> tuple[VisualInput, ...]:
        if self.image_cost is None:
            return event.images
        # Compare native-resolution evidence, not illegible downscaled full frames.
        mapping = {s.role: s.frame for s in sources}
        native = replace(self.gateway_config, detail_width=mapping["current"].shape[1])
        full = tuple(_encode_visual(s.role, s.frame, s.frame.shape[1], native) for s in sources)
        cropped = full
        if event.region is not None:
            region = event.region.expanded(native.crop_margin)
            details = [_encode_visual("context", mapping["current"], native.context_width, native)]
            for source in sources:
                crop = source.frame[region.y:region.y+region.height, region.x:region.x+region.width]
                details.append(_encode_visual(source.role + "_detail", crop, crop.shape[1], native))
            cropped = tuple(details)
        costs = [self.image_cost(images) for images in (cropped, full)]
        if not all(math.isfinite(c) and c >= 0 for c in costs):
            raise ValueError("image_cost must return finite nonnegative estimates")
        return cropped if costs[0] <= costs[1] else full

    def _register(self, event: PerceptionEvent, sources: tuple[SourceFrame, ...],
                  sig: tuple[np.ndarray, ...], *, priority: int,
                  historical: bool = False, source_id: int | None = None,
                  source_role: str = "current") -> AttentionPacket:
        sequence = self._sequence
        self._sequence += 1
        if not historical:
            event = replace(event, images=self._visuals(sources, event))
        event = replace(event, sequence=sequence)
        source_id = sequence if source_id is None else source_id
        packet = AttentionPacket(event, self.contract.goal, self.contract.version,
            self.contract.action_id, self._epoch, self._revision, priority,
            self._now + self.config.delivery_timeout_seconds, source_id,
            source_role, historical)
        self._records[sequence] = _Record(packet, sig)
        self.stats["packets"] += 1
        if sources and not self.evidence.put(sequence, sources, self._now):
            self.stats["evidence_not_retained"] += 1
            self._notice(sequence, "original_evidence_not_retained")
        if len([r for r in self._records.values() if r.status in ("queued", "inflight")]) > self.config.max_pending:
            self._fail(sequence, "queue_overflow")
        else:
            self._outbox[sequence] = packet
        if not historical:
            self._next_check = self._now + self.contract.recheck_after_seconds
        self._trim_history()
        return packet

    def _notice(self, sequence: int, reason: str) -> None:
        if len(self._notices) == self._notices.maxlen:
            self.stats["notice_overflow"] += 1
        self._notices.append({"sequence": sequence, "reason": reason, "at": self._now})

    def _fail(self, sequence: int, reason: str) -> None:
        record = self._records.get(sequence)
        if record is not None:
            if record.status == "failed":
                return
            record.status = "failed"
        self._outbox.pop(sequence, None)
        if sequence == self._current:
            self._current = None
        self.stats["failed"] += 1
        self._notice(sequence, reason)

    def _trim_history(self) -> None:
        while (len(self._records) > self.config.history_size
               or sum(r.nbytes for r in self._records.values()) > self.config.history_max_bytes):
            key = next(iter(self._records))
            self._fail(key, "history_evicted")
            del self._records[key]
            self.evidence.discard(key)

    def poll_packets(self, max_items: int = 1, *, max_image_bytes: int | None = None) -> list[AttentionPacket]:
        """Priority/deadline ordered batch; every distinct event stays in the batch.

        Byte limit is a transport budget, NOT a billed-token estimate. An oversized
        first packet is returned alone with a notice, never silently starved.
        """
        if not isinstance(max_items, int) or max_items <= 0:
            raise ValueError("max_items must be a positive integer")
        if max_image_bytes is not None and max_image_bytes <= 0:
            raise ValueError("max_image_bytes must be positive")
        with self._lock:
            batch, size = [], 0
            for packet in sorted(self._outbox.values(), key=lambda p: (p.priority, p.due_at, p.event.sequence)):
                payload = sum(len(i.jpeg) for i in packet.event.images)
                if max_image_bytes is not None and size + payload > max_image_bytes:
                    if batch:
                        break
                    self._notice(packet.event.sequence, "packet_exceeds_batch_byte_budget")
                batch.append(packet)
                size += payload
                if len(batch) >= max_items or (max_image_bytes is not None and size >= max_image_bytes):
                    break
            for packet in batch:
                self._outbox.pop(packet.event.sequence)
                self._records[packet.event.sequence].status = "inflight"
                self._records[packet.event.sequence].delivered = True
                self.stats["delivered_image_pixels"] += sum(i.pixel_count for i in packet.event.images)
            self.stats["delivered"] += len(batch)
            self.stats["delivered_image_bytes"] += size
            self.stats["batches"] += bool(batch)
            return batch

    def acknowledge(self, sequence: int, interpretation: SemanticResult | None,
                    *, error: str | None = None) -> Acknowledgement:
        """Record the actual result; only fresh, current-version evidence updates belief."""
        with self._lock:
            record = self._records.get(sequence)
            if record is None:
                return Acknowledgement(sequence, False, "unknown_or_evicted")
            if not record.delivered or record.result_received:
                return Acknowledgement(sequence, False, "not_inflight")
            record.result_received = True
            if interpretation is not None:
                record.interpretation = interpretation
                self.stats["semantic_responses"] += 1
                if interpretation.input_tokens is not None and interpretation.output_tokens is not None:
                    self.stats["responses_with_usage"] += 1
                    self.stats["reported_input_tokens"] += interpretation.input_tokens
                    self.stats["reported_output_tokens"] += interpretation.output_tokens
                    self.stats["reported_cached_input_tokens"] += interpretation.cached_input_tokens or 0
                    self.stats["reported_reasoning_output_tokens"] += interpretation.reasoning_output_tokens or 0
            if record.status != "inflight":
                self.stats["stale_results"] += 1
                return Acknowledgement(sequence, False, "delivery_expired_or_failed")
            if error is not None or interpretation is None:
                self._fail(sequence, error or "missing_interpretation")
                return Acknowledgement(sequence, False, error or "missing_interpretation")
            record.interpretation, record.status = interpretation, "completed"
            p = record.packet
            reason = "accepted"
            if p.historical:
                reason = "historical_detail_only"
            elif p.epoch != self._epoch or p.contract_version != self.contract.version or p.action_id != self.contract.action_id:
                reason = "context_changed"
            elif p.visual_revision != self._revision:
                reason = "scene_changed"
            elif self._now - p.event.timestamp >= self.contract.recheck_after_seconds:
                reason = "observation_expired"
            elif self._current is not None and sequence < self._current:
                reason = "superseded_result"
            elif self._latest is None or self._change(self._signature(self._latest.frame), record.signature, self._latest.frame)[0] is not None:
                reason = "evidence_changed"
            if reason != "accepted":
                self.stats["stale_results"] += 1
                self._notice(sequence, reason)
                return Acknowledgement(sequence, False, reason)
            self._committed = record.signature
            self._current = sequence
            return Acknowledgement(sequence, True, reason)

    def current_belief(self) -> dict[str, object]:
        """Freshness is not semantic correctness or proof of action success."""
        with self._lock:
            record = self._records.get(self._current) if self._current is not None else None
            valid = (record is not None and record.packet.epoch == self._epoch
                     and record.packet.visual_revision == self._revision
                     and self._now - record.packet.event.timestamp < self.contract.recheck_after_seconds)
            return {"valid": bool(valid), "sequence": self._current,
                    "as_of": record.packet.event.timestamp if record else None,
                    "repeat_equivalence_active": self._repeat is not None,
                    "interpretation": record.interpretation.to_dict() if valid and record.interpretation else None}

    def flush(self) -> AttentionPacket | None:
        """Preserve a pending transition at end-of-stream; do not mark it interpreted."""
        with self._lock:
            if self._latest is None:
                return None
            s = self._latest
            observation = self._detector.flush(s.frame, s.timestamp,
                frame_index=s.frame_index, goal=self.contract.goal)
            if observation is None:
                return None
            return self._register(observation.event, self._detector.sources,
                                  self._signature(s.frame), priority=0)

    def request_detail(self, event_id: int, region: WatchRegion, *, role: str = "current") -> AttentionPacket:
        """Exact historical source. Missing evidence raises, never uses the latest frame."""
        with self._lock:
            source = self.evidence.get(event_id, role, self._now)
            roi = region.pixels(source.frame)
            crop = source.frame[roi.y:roi.y+roi.height, roi.x:roi.x+roi.width]
            image = _encode_visual("historical_detail", crop, crop.shape[1], self.gateway_config)
            event = PerceptionEvent(-1, source.timestamp, source.frame_index,
                "historical_detail", 0.0, roi, (image,), "requested")
            # Historical details never acknowledge the complete current screen.
            return self._register(event, (), (), priority=0, historical=True,
                                  source_id=event_id, source_role=role)

    def request_current(self, *, reason: str = "question_changed") -> AttentionPacket:
        """Explicit reconsideration of the latest source; its age is not reset."""
        with self._lock:
            if self._latest is None:
                raise EvidenceUnavailable("no captured frame")
            source = self._latest
            self._invalidate(reason)
            sig = self._signature(source.frame)
            self._scene = sig
            self._force_reason = None
            observation = self._detector.observe_frame(source.frame, source.timestamp,
                goal=self.contract.goal, frame_index=source.frame_index)
            assert observation is not None
            event = replace(observation.event, reason=reason)
            return self._register(event, self._detector.sources, sig, priority=0)

    def verify_after_action(self, before_frame: np.ndarray, after_frame: np.ndarray,
                            timestamp: float, *, before_timestamp: float,
                            action_id: str, action: str, expected_result: str,
                            frame_index: int | None = None,
                            before_frame_index: int | None = None) -> AttentionPacket:
        with self._lock:
            self._validate_frame(before_frame)
            self._validate_frame(after_frame)
            if (before_frame.shape != after_frame.shape or not action_id.strip()
                    or not action.strip() or not expected_result.strip()
                    or any(i is not None and (not isinstance(i, int) or isinstance(i, bool) or i < 0)
                           for i in (frame_index, before_frame_index))
                    or not math.isfinite(before_timestamp) or not 0 <= before_timestamp <= timestamp):
                raise ValueError("invalid action evidence")
            self._time(timestamp)
            self._invalidate("action_changed")
            self.contract = replace(self.contract, action_id=action_id)
            self._force_reason = None
            before, after = before_frame.copy(), after_frame.copy()
            self._latest = SourceFrame("current", timestamp, frame_index, after)
            sig = self._signature(after)
            self._scene = sig
            self._revision += 1
            observation = self._detector.verify_after_action(before, after, timestamp,
                goal=self.contract.goal, action=action, expected_result=expected_result,
                frame_index=frame_index)
            sources = tuple(replace(s, timestamp=before_timestamp, frame_index=before_frame_index)
                            if s.role == "before" else s for s in self._detector.sources)
            return self._register(observation.event, sources, sig, priority=0)

    def retry_event(self, sequence: int) -> AttentionPacket | None:
        """Retry exact images under a NEW identity, so late attempts cannot overwrite it."""
        with self._lock:
            record = self._records.get(sequence)
            if record is None or record.status not in ("failed", "completed"):
                return None
            active = sum(r.status in ("queued", "inflight") for r in self._records.values())
            if active >= self.config.max_pending:
                return None
            key = self._sequence
            self._sequence += 1
            packet = replace(record.packet, event=replace(record.packet.event, sequence=key),
                             due_at=self._now + self.config.delivery_timeout_seconds)
            self._records[key] = _Record(packet, record.signature)
            self._outbox[key] = packet
            self.stats["packets"] += 1
            self._trim_history()
            return packet

    def poll_notices(self) -> list[dict[str, object]]:
        with self._lock:
            notices = list(self._notices)
            self._notices.clear()
            return notices

    def report(self) -> dict[str, object]:
        with self._lock:
            return {"stats": dict(self.stats), "contract": asdict(self.contract),
                    "approved_repeat": dict(self._repeat) if self._repeat is not None else None,
                    "evidence_bytes": self.evidence.bytes_used,
                    "history_bytes": sum(r.nbytes for r in self._records.values()),
                    "usage_complete": (self.stats["delivered"] > 0 and
                                       self.stats["responses_with_usage"] == self.stats["delivered"]),
                    "reported_total_tokens": (self.stats["reported_input_tokens"] + self.stats["reported_output_tokens"]
                                              if self.stats["responses_with_usage"] else None),
                    "current_belief": self.current_belief(),
                    "records": [{**r.packet.to_dict(), "status": r.status,
                                 "interpretation": r.interpretation.to_dict() if r.interpretation else None}
                                for r in self._records.values()]}
