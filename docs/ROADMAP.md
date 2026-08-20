# Codex-mode improvement roadmap

Signum should optimize for evidence capture before it optimizes for fewer Codex calls. A cheap gate is not useful when the image sent to Codex no longer contains the event.

## Metrics

Evaluate the pipeline as four separate stages:

1. **Trigger recall**: fraction of labeled events that cause a gateway event.
2. **Evidence recall**: fraction of labeled events visibly present in at least one emitted image.
3. **Semantic accuracy**: fraction of Codex observations that correctly describe the labeled state.
4. **Task-state accuracy**: fraction of observations that recommend a safe and useful next step for the stated goal.

Also record false calls per minute, Codex calls per minute, prepared image bytes, transmitted image bytes, per-call latency, and failed calls. Every detector comparison must use the same labeled recordings and Codex observation policy.

## Priority 0: establish a real screen-recording benchmark

Build a small manually labeled suite containing dialogs, toasts, progress completion, disabled/enabled controls, small text changes, cursor and caret motion, loading animation, scrolling, and rapid open-close transitions. Store event intervals and evidence regions separately from predictions. Compare against fixed-interval observation at the same Codex call budget.

No detection-success claim should be made before this suite exists.

## Priority 1: validate and tune small-region recall

The gateway now supplements its global fraction with a higher-resolution connected-component guard. Validate its width and minimum component size on labeled recordings. If it still misses compact evidence, compare it with a tiled guard at the same CPU and false-call budget. Keep the implementation CPU-only and deterministic.

Acceptance criterion: higher trigger and evidence recall on small labeled UI changes without exceeding an agreed CPU or false-call budget.

## Priority 2: suppress state-return duplicates

Keep a compact signature of the last emitted stable screen. If animation or a blinking cursor ends on the same semantic screen, avoid another Codex call unless a preserved transition peak contains distinct evidence.

Acceptance criterion: fewer false calls per minute with no loss in evidence recall.

## Priority 3: make Codex failures recoverable

Write each event and its pending interpretation to disk before invoking Codex. Record explicit timeout, authentication, schema, and rate-limit failures. Add bounded retry and resume support so one failed call does not discard an otherwise useful long run.

Acceptance criterion: an interrupted run can resume without repeating successful Codex calls or losing source metadata.

## Priority 4: reduce interpreter startup latency

The current adapter intentionally uses one stable `codex exec` process per event. Measure process startup separately from model latency. Consider a persistent Codex SDK or app-server session only if startup is a material share of end-to-end latency and the simpler adapter has already met accuracy targets.

Acceptance criterion: a measured latency improvement with unchanged semantic test cases and no weaker isolation.

## Deferred

Live desktop capture, action execution, audio, databases, servers, non-Codex providers, neural detectors, and GPU acceleration remain outside the current milestone. They should not be added to compensate for an unmeasured detector.
