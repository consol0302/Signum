# Signum contributor guide

Signum is a CPU-first perception gateway that reduces the video and audio presented to multimodal models. The current milestone is a deterministic, video-only sampler and an honest benchmark against uniform temporal sampling.

## Non-negotiable principles

- Algorithm before AI.
- CPU-first; GPU acceleration may only be optional.
- Benchmark every meaningful sampler change against the same observation budget.
- Never claim performance without measurements.
- Preserve source timestamps, frame indices, and enough metadata to re-extract every observation.
- Avoid unnecessary dependencies and premature framework layers.
- Prefer simple deterministic implementations.
- Expose failures rather than hiding them or tuning the benchmark around them.
- Keep model-provider integration out of the deterministic core.

## Working loop

1. Reproduce a benchmark failure.
2. State one falsifiable hypothesis.
3. Implement the smallest change that tests it.
4. Run tests and the same benchmark suite.
5. Compare with uniform sampling and the previous Signum variant.
6. Keep the change only when measurements or a documented invariant justify it.

The MVP must remain runnable after each change. Do not add a web server, database, plugin system, distributed architecture, neural model, or realtime abstraction without benchmark evidence and an explicit milestone that requires it.

## Verification

Run:

```bash
python -m unittest discover -s tests -v
python -m signum.benchmark --output benchmark-output
```

Generated benchmark artifacts belong outside the source tree or in ignored output directories.
