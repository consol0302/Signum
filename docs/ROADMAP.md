# Codex-mode improvement roadmap

Signum should optimize for evidence capture before it optimizes for fewer Codex calls. A cheap gate is not useful when the image sent to Codex no longer contains the event.

## Metrics

Evaluate the pipeline as four separate stages:

1. **Trigger recall**: fraction of labeled events that cause a gateway event.
2. **Evidence recall**: fraction of labeled events visibly present in at least one emitted image.
3. **Semantic accuracy**: fraction of Codex observations that correctly describe the labeled state.
4. **Task-state accuracy**: fraction of observations that recommend a safe and useful next step for the stated goal.

Also record false calls per minute, Codex calls per minute, prepared image bytes, transmitted image bytes, transmitted 32-pixel image patches, per-call latency, runtime-reported token usage, missing usage records, and failed calls. Every detector comparison must use the same labeled recordings and Codex observation policy. Token results must come from Codex's completed-turn usage records; patch counts are payload measurements and must not be presented as billed-token estimates.

## Priority 0: establish a real screen-recording benchmark

The labeled replay evaluator, equal-budget uniform baseline, saved review artifacts, and human-review scoring contract are implemented. A local 60-label development suite now covers dialogs or messages, progress completion, disabled/enabled controls, small text changes, cursor or hover changes, scrolling, loading, and repeated HUD-like values. It has only 55 independent transitions and four constructed failed actions, so it remains an incomplete pilot rather than a real benchmark.

The next collection must add at least four real failed actions and five independent transitions, then freeze a held-out suite before tuning. No broad detection-success claim should be made before that suite and its blind review exist.

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

The current default adapter intentionally uses one isolated `codex exec` process per event. A measured resumed-session experiment was slower and used more reported tokens, so it is not the default. A single structured batch was substantially cheaper on five events and passed the provisional semantic checks, but it delays each observation until the batch is submitted.

Acceptance criterion: add an explicit batching policy only after measuring batch size, maximum wait, semantic accuracy, and false confirmations on the frozen suite. High-risk action verification must keep a bounded immediate path.

## Implemented runtime foundation

The streaming gateway now separates CPU detection from semantic inference, retains a bounded recent-frame ring and event history, preserves semantic event order, exposes queue overflow, and supports detail, retry, and action-verification requests. It still needs sustained real-browser measurements for capture rate, detector latency, queue depth, dropped events, and end-to-end Codex latency.

## Deferred

Desktop capture, action execution, audio, databases, servers, non-Codex providers, neural detectors, and GPU acceleration remain outside the current milestone. They should not be added to compensate for an unmeasured detector.
