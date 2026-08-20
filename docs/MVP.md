# Signum 0.0.x MVP

## Goal

Given a local video and a positive frame budget, emit at most that many original-resolution observations which are more event-rich than equal-budget uniform sampling while retaining reasonable temporal coverage.

The adjacent Codex-mode goal is narrower: given a screen recording and a computer-use goal, emit deterministic change events and ask an authenticated local Codex CLI to describe only those events as structured observations.

## Command

```bash
signum analyze INPUT --budget 32 --output output
signum observe INPUT --goal "Describe the task state" --output observe-output
```

Useful controls are `--candidate-hz`, `--analysis-width`, `--min-distance`, `--coverage-fraction`, `--no-spike-guard`, and `--strategy`. Defaults are deterministic and recorded in the output report.

## Output contract

- `frames/`: selected original-resolution frames named by selection order, frame index, and timestamp.
- `timeline.json`: source metadata and chronologically ordered observations.
- `report.json`: configuration, processing counts/timing, score summary, and redundancy information.

For a decodable non-empty video, output count is `min(budget, analyzed candidate count)`. Duplicate suppression prefers distinct observations but does not silently return fewer frames when the requested budget can be filled.

## Acceptance criteria

- CLI completes on an ordinary OpenCV-readable video.
- Selected count never exceeds the budget and fills it when enough candidates exist.
- Timestamps match `frame_index / fps` within floating-point tolerance.
- Runs with identical media and configuration select identical source frame indices.
- Obvious near-duplicates are avoided when distinct alternatives exist.
- Synthetic benchmark reports equal-budget event recall, redundancy, temporal coverage, analyzed-frame count, and CPU wall time for Signum and uniform sampling.

## Known limitations

- The per-frame spike guard catches abrupt global changes between scheduled candidates, but short local or low-contrast events can still be missed.
- Pixel change cannot determine semantic importance; small but meaningful changes may score poorly.
- Camera movement and animated backgrounds can consume the importance budget.
- OpenCV-reported timestamps and frame counts depend on the codec backend.
- Synthetic results validate mechanics, not downstream VLM accuracy or real-world token savings.
- Codex mode currently starts one CLI process per event; startup latency is measured but not yet benchmarked on a labeled real suite.
- The global gateway path uses one bounding rectangle for changed pixels, so multiple distant changes can create an unnecessarily large detail region. The local guard keeps only the largest connected component.
- UI changes smaller than the configured local component threshold can still be missed.
- Consecutive animation can delay emission until the active timeout and may consume more Codex calls than a static workflow.
- The project interprets recorded video and exposes an action-verification API, but it does not capture a live desktop or execute actions.
