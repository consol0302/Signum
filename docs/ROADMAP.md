# Roadmap

Signum should improve evidence capture before it optimizes for fewer semantic
calls. A cheap gate is not useful when the emitted image no longer contains the
event.

## Measurement contract

Track the pipeline as four separate stages:

1. Trigger recall.
2. Visible-evidence recall.
3. Semantic accuracy.
4. Task-state accuracy.

Also record false calls per minute, calls per minute, image bytes, image
patches, latency, runtime-reported token usage, missing usage, and failed calls.
Every detector comparison must use the same recordings and the same observation
budget as uniform sampling.

## Priority 0: complete independent held-out review

The V4 collection and method-blind review packets are frozen. Complete two
independent reviews and adjudicate every disagreement before generating method
or provider outputs. The protocol and current blockers are preserved in
[Signum Benchmarks](https://github.com/consol0302/signum-benchmarks).

Acceptance criterion: a fully reviewed frozen suite whose labels were not
influenced by detector or provider output.

## Priority 1: validate compact UI recall

Compare the current higher-resolution connected-component guard with a tiled
alternative on the frozen suite at the same CPU and false-call budget.

Acceptance criterion: higher trigger and evidence recall without exceeding the
declared CPU or false-call limit.

## Priority 2: suppress returned-state duplicates

Keep a compact signature of the last emitted stable screen and suppress a
returned semantic state unless a preserved transition peak contains distinct
evidence.

Acceptance criterion: fewer false calls per minute with no loss in evidence
recall.

## Priority 3: make interpretation recoverable

Persist pending events before interpretation and add bounded resume support for
timeouts, authentication failures, schema errors, and rate limits.

Acceptance criterion: an interrupted run resumes without repeating successful
calls or losing source metadata.

## Priority 4: evaluate bounded batching

One structured batch was cheaper and faster than isolated Codex calls on a
small development fixture, but it delays each result. Measure batch size,
maximum wait, semantic accuracy, and false confirmations on frozen data before
adding a policy.

Acceptance criterion: a declared batching policy that keeps high-risk action
verification on a bounded immediate path.

## Deferred

Desktop action execution, audio, databases, servers, neural detectors, and GPU
requirements remain outside the current milestone.
