# Benchmark methodology

## Question

At the same frame budget, does Signum capture more known events than uniform temporal sampling, and what CPU/decode cost does that require?

The benchmark also compares `score_only` (the initial implementation) with `hybrid` (one improvement: reserve temporal coverage anchors). This makes the improvement falsifiable instead of silently replacing the reference behavior.

## Synthetic suite

The generator uses deterministic MJPEG AVI videos and emits exact ground-truth intervals. Cases intentionally include both favorable and hostile conditions:

1. Static scene with a short moving object.
2. Multiple hard scene cuts.
3. Slow low-amplitude visual change.
4. A very brief flash that candidate sampling may miss.
5. Continuous full-frame motion with sparse marked events.
6. Repetitive motion where many high-score frames are redundant.
7. Camera-like global panning with a small local event.

These fixtures test timing and selection behavior. They are not evidence of real-world semantic understanding.

## Metrics

- **Event recall:** fraction of labeled event intervals containing at least one selected timestamp. A small declared tolerance accounts for discrete frames.
- **Redundancy:** fraction of selected observations after the first whose compact signature is near-identical to an earlier selected observation.
- **Temporal coverage:** fraction of equal temporal bins containing at least one selection. Bin count equals the frame budget (capped by available candidates).
- **Processing time:** wall-clock analysis and selection time. Treat small runs as indicative, not stable performance claims.
- **Analyzed frames:** candidates decoded for signal analysis. Export decoding is reported separately.
- **Frame budget:** identical within each case and method.

Uniform sampling does not need to analyze visual content, so it should normally be much cheaper. Signum must justify its extra CPU work through recall or a later downstream metric.

## Guardrails

- Scenarios, budgets, event labels, and tolerance are fixed before comparing selectors.
- Aggregate numbers are accompanied by per-case results so failures remain visible.
- No benchmark output is copied into README as a durable performance claim.
- Changes are compared with both uniform and the previous selector.
- A regression is not hidden by averaging it with easy cases.

## Running

```bash
$env:PYTHONPATH = "src"
python -m signum.benchmark --output benchmark-output
```

The command writes generated media and `benchmark.json`. Generated files are reproducible and should not be committed.

The first measured run and its limitations are recorded in [RESULTS.md](RESULTS.md).
