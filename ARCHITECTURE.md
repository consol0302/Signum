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
             -> context/detail JPEGs -> codex exec -> schema-validated observation
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

The passive detector uses a cheap 192-pixel-wide full-screen fraction first. If that does not trigger, a 768-pixel-wide binary change map is checked for a connected local component. This preserves small UI evidence without lowering the global threshold and accepting every scattered compression artifact. Both paths remain deterministic.

After a controller action, `verify_after_action` compares explicit pre-action and post-action frames and bypasses the stability and cooldown gates. Both visual states are attached, and it emits even when no pixels changed because visible non-change is evidence that an action may not have taken effect. The event carries the action and expected visible result, and the semantic contract requires an explicit verification status.

## Codex boundary

`codex exec` is started once per gated observation. Runs are ephemeral, read-only, non-interactive, and validated with a JSON Schema. Signum passes the goal, previous semantic summary, event metadata, and local JPEG paths. It does not access Codex credentials or call the OpenAI API directly.

This process-per-event implementation is intentionally simple and testable. A persistent SDK or app-server session could reduce startup latency later, but it is not justified until real recordings show that Codex startup dominates the useful observation budget.

## Explicit non-goals

There is no database, server, plugin framework, GPU requirement, audio pipeline, action executor, live capture loop, or realtime buffer in this milestone. There are also no API or non-Codex model adapters. Those abstractions would add cost before the gating hypothesis is validated.
