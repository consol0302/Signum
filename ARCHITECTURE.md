# Architecture

## Decision summary

Signum 0.0.x is one Python package with a CLI and no service boundary. OpenCV is the only direct runtime dependency beyond NumPy. It provides cross-platform video decode, resizing, image comparison, video generation for benchmarks, and frame export without requiring FFmpeg as a separate executable.

The first useful vertical slice is:

```text
video -> metadata -> sparse low-resolution candidates -> deterministic signals
      -> budgeted selection -> original-resolution frame extraction
      -> timeline.json + report.json
```

## Components

- `video.py`: metadata probing, sparse sequential candidate decoding, and source-frame extraction.
- `signals.py`: frame difference, grayscale histogram difference, motion-pixel fraction, robust per-video normalization, and weighted importance.
- `selector.py`: score-only reference selector, current hybrid selector, temporal suppression, and compact-signature duplicate suppression.
- `pipeline.py`: orchestration and artifact serialization.
- `cli.py`: user-facing `signum analyze` command.
- `synthetic.py` and `benchmark.py`: deterministic ground-truth fixtures and equal-budget comparisons.

## Key choices

Candidate frames are decoded sequentially and analyzed at a configurable maximum width. The default candidate rate is 4 Hz. This can miss sub-250 ms events; the benchmark must make that failure visible. Seeking every timestamp was rejected because many codecs make random access slower and less deterministic than a sequential pass.

Raw signals have different scales, so each is divided by its own non-zero 95th percentile within the video before applying configurable weights. This is a simple relative normalization, not a learned calibration. The first-frame score is zero because it has no predecessor.

The initial selector ranks importance with a minimum temporal distance. Its known weakness is poor whole-video coverage. The current hybrid reserves a configurable fraction of the budget for uniformly spaced anchors, then spends the rest on high-scoring candidates. Near-identical compact grayscale signatures are suppressed when alternatives exist. If the video contains fewer unique observations than the requested budget, deterministic redundant fills preserve the budget invariant.

## Source preservation

Every selected observation records:

- timestamp in seconds;
- original zero-based frame index;
- source interval represented by the candidate;
- source video path and metadata at the timeline level;
- extracted frame filename.

This is sufficient to seek or sequentially re-extract the original frame. The source media itself is never modified.

## Explicit non-goals

There is no database, server, plugin framework, GPU requirement, neural inference, audio pipeline, or realtime buffer in this milestone. Those abstractions would add cost before the sampling hypothesis is validated.
