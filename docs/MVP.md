# Signum 0.0.x MVP

## Goal

Given a local video and a positive frame budget, emit at most that many original-resolution observations which are more event-rich than equal-budget uniform sampling while retaining reasonable temporal coverage.

## Command

```bash
signum analyze INPUT --budget 32 --output output
```

Useful controls are `--candidate-hz`, `--analysis-width`, `--min-distance`, `--coverage-fraction`, and `--strategy`. Defaults are deterministic and recorded in the output report.

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

- Candidate-rate sampling can miss events shorter than its sampling interval.
- Pixel change cannot determine semantic importance; small but meaningful changes may score poorly.
- Camera movement and animated backgrounds can consume the importance budget.
- OpenCV-reported timestamps and frame counts depend on the codec backend.
- Synthetic results validate mechanics, not downstream VLM accuracy or real-world token savings.
