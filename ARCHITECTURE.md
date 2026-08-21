# Architecture

## Decision summary

Signum 0.0.x is one Python package with a CLI and no service boundary. OpenCV is the only direct runtime dependency beyond NumPy. It provides cross-platform video decode, resizing, image comparison, video generation for benchmarks, and frame export without requiring FFmpeg as a separate executable.

The first useful vertical slice is:

```text
video -> metadata -> sparse low-resolution candidates -> deterministic signals
      -> budgeted selection -> original-resolution frame extraction
      -> timeline.json + report.json
```

The experimental Codex-only vertical slice is:

```text
video frames -> global + local deterministic change gate
             -> stable current frame + optional peak
             -> context/detail JPEGs -> codex exec JSONL
             -> schema-validated observation + runtime usage
```

The deterministic gate owns event discovery and source metadata. Codex only interprets events that the gate emits; it is not used to decide which frames changed.

## Components

- `video.py`: metadata probing, sparse sequential candidate decoding, and source-frame extraction.
- `signals.py`: frame difference, grayscale histogram difference, motion-pixel fraction, robust per-video normalization, and weighted importance.
- `selector.py`: score-only reference selector, current hybrid selector, temporal suppression, and compact-signature duplicate suppression.
- `pipeline.py`: orchestration and artifact serialization.
- `gateway.py`: stateful global/local screen-change gating, region extraction, action-verification checkpoints, stability handling, and visual-input preparation.
- `interpreters.py`: the isolated Codex CLI subprocess adapter and structured observation contract.
- `observe.py`: video-to-event orchestration and observation serialization.
- `evaluation.py`: labeled replay manifests, equal-budget uniform observations, temporal matching, aggregate cost metrics, and human-review scoring.
- `streaming.py`: live frame submission, bounded frame and event retention, non-blocking semantic queuing, retries, requested crops, and result polling.
- `cli.py`: user-facing `signum analyze` and `signum observe` commands.
- `synthetic.py` and `benchmark.py`: deterministic ground-truth fixtures and equal-budget comparisons.

## Key choices

Frames are decoded sequentially and regular candidates are analyzed at a configurable maximum width. The default candidate rate is 4 Hz. Because the sequential decoder already visits every frame, the default path also computes a 16×9 grayscale signature per frame. An abrupt-change guard promotes the first frame of a transition run when its mean signature difference is at least 0.35. This recovered the benchmark's between-sample full-screen flash without another decode pass. Small or low-contrast sub-250 ms events can still be missed. Seeking every timestamp was rejected because many codecs make random access slower and less deterministic than a sequential pass.

Raw signals have different scales, so each is divided by its own non-zero 95th percentile within the video before applying configurable weights. This is a simple relative normalization, not a learned calibration. The first-frame score is zero because it has no predecessor.

The initial selector ranks importance with a minimum temporal distance. Its known weakness is poor whole-video coverage. The current hybrid reserves a configurable fraction of the budget for uniformly spaced anchors, then spends the rest on high-scoring candidates. Near-identical compact grayscale signatures are suppressed when alternatives exist. If the video contains fewer unique observations than the requested budget, deterministic redundant fills preserve the budget invariant. The spike guard is configurable and can be disabled to reproduce the previous sampling path.

## Source preservation

Every selected observation records:

- timestamp in seconds;
- original zero-based frame index;
- source interval represented by the candidate;
- source video path and metadata at the timeline level;
- extracted frame filename.

This is sufficient to seek or sequentially re-extract the original frame. The source media itself is never modified.

Codex events additionally record the event frame, the maximum-change frame when one exists, timestamps, normalized change region, image roles, and exact JPEG artifacts. A transient peak is attached only when it differs materially from the final stable frame. Pending changes are flushed at end of stream instead of being silently lost.

For each transmitted image, Signum records encoded bytes, pixels, and the unadjusted number of 32-pixel patches. The patch count is deterministic and useful for comparing gateway variants, but it is not labeled as a billed-token estimate. Model-side resizing and accounting are outside the deterministic core.

The passive detector uses a cheap 192-pixel-wide full-screen fraction first. If that triggers, the event still uses the 768-pixel-wide binary map for crop localization; this preserves thin evidence that can disappear from coarse coordinates without changing the trigger threshold. If the global fraction does not trigger, the same 768-pixel map is checked for a connected local component. This preserves small UI evidence without lowering the global threshold and accepting every scattered compression artifact. Both paths remain deterministic.

After a controller action, `verify_after_action` compares explicit pre-action and post-action frames and bypasses the stability and cooldown gates. Both visual states are attached, and it emits even when no pixels changed because visible non-change is evidence that an action may not have taken effect. The event carries the action and expected visible result, and the semantic contract requires an explicit verification status.

## Codex boundary

`codex exec` is started once per gated observation. Runs are ephemeral, read-only, non-interactive, and validated with a JSON Schema. The adapter enables Codex's JSONL event stream and reads usage from the final `turn.completed` record. Signum stores input, cached-input, output, and reasoning-output fields without trying to reconstruct missing values. Aggregate reported tokens are input plus output; reasoning output is retained as a separate diagnostic and is not added again. Signum passes the goal, previous semantic summary, event metadata, and local JPEG paths. It does not access Codex credentials or call the OpenAI API directly.

This process-per-event implementation is intentionally simple and testable. A persistent SDK or app-server session could reduce startup latency later, but it is not justified until real recordings show that Codex startup dominates the useful observation budget.

## Evaluation boundary

The replay evaluator uses source-timeline event intervals and both current and preserved-peak image timestamps. A gateway call is a trigger hit when one of those image timestamps falls inside the labeled interval plus its declared annotation tolerance. Each recording's uniform baseline receives exactly the number of observations emitted by Signum, placed at equal-bin centers. Initial context is included rather than silently removed from Signum's cost.

Temporal matching cannot establish that resized text is legible or that a model's description is correct. The evaluator therefore generates a review contract with separate visible-evidence, semantic-correctness, and task-state-correctness verdicts. Missing human verdicts remain unavailable; they are never inferred from detector geometry or model confidence. End-to-end success requires all three verdicts, while an unmatched event is an automatic failure.

## Streaming boundary

The streaming runtime keeps deterministic gating on the frame-submission path and moves only semantic interpretation to a single background worker. This preserves event order and previous-state context while preventing Codex latency from pausing capture. A bounded queue prevents unbounded JPEG retention. Overflow is returned as an explicit failed result, and retained event artifacts can be requeued by sequence.

The recent-frame ring is bounded independently from event history. Requested crops use the latest retained full-resolution frame, while retries reuse the exact event JPEGs originally prepared. Action verification accepts controller-provided before and after frames and bypasses passive stability gates.

## Explicit non-goals

There is no database, server, plugin framework, GPU requirement, audio pipeline, action executor, or desktop-capture implementation in this milestone. There are also no API or non-Codex model adapters. Petasos or another controller must supply frames and own actions.
