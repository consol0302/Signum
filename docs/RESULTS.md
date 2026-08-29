# Measured results

This page summarizes results that are useful for understanding the current
runtime. The complete protocols, frozen manifests, collection outcomes, and
research history live in
[Signum Benchmarks](https://github.com/consol0302/signum-benchmarks).

## Synthetic sampler regression

The deterministic suite contains seven six-second, 20 fps MJPEG videos. Every
method receives a budget of six observations per case.

| Method | Event recall | Redundancy | Temporal coverage | Full candidates | Coarse frames |
|---|---:|---:|---:|---:|---:|
| Uniform | 0.429 | 0.500 | 1.000 | 0 | 0 |
| Hybrid, spike guard off | 0.857 | 0.429 | 0.643 | 25 | 0 |
| Hybrid | 1.000 | 0.405 | 0.667 | 25 | 120 |

The per-frame 16×9 spike guard recovered the one-frame flash that fell between
the scheduled 4 Hz candidates. It did not reduce recall on the other six
fixtures. Uniform retained perfect temporal coverage and performed no content
analysis.

These videos are constructed regression fixtures. They validate timing,
selection, budget handling, and a known short-event failure. They do not
validate semantic importance, VLM accuracy, real-video generalization, token
cost, or production latency.

## Development screen replay

On a 180-event development detector suite, the current one-stable-frame default
triggered 164 events while equal-budget uniform sampling triggered 86. Each
method received 473 observations.

That suite was used to choose the default and is therefore not held out. The
result is evidence for a regression setting, not a general performance claim.

## Held-out status

A fresh V4 public-web collection, its mechanically anchored event inventory,
and method-blind review packets have been frozen. Two independent human reviews
and adjudication are still required before the suite can support a comparison.
Provider runs have not started.

Accordingly, Signum does not currently support a claim that it is more accurate
or cheaper than OpenAI or Claude computer use.

## Reproduce

```bash
python -m signum.benchmark --output benchmark-output
```

The command writes the generated videos and machine-readable
`benchmark.json` into the ignored output directory. Machine timing is
environment-specific; compare selectors on the same machine and suite.
