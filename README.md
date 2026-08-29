# Signum Perception

**Deterministic, CPU-first event gating for multimodal video and computer-use pipelines.**

Signum reduces the video a multimodal model needs to inspect. It finds visual
changes with ordinary image processing, preserves exact source timestamps and
frame indices, and emits a compact observation timeline that can be reproduced
later.

Signum is a research preview. The sampler and gateway are usable, but no
supported claim currently says Signum is more accurate or cheaper than a model
provider's native computer-use product.

- [Benchmark evidence](https://github.com/consol0302/signum-benchmarks)
- [Architecture](ARCHITECTURE.md)
- [License](LICENSE)

## Why

Most video frames repeat information. Uniform temporal sampling is cheap and
predictable, but it can miss a short dialog, toast, state change, or failed
action. Sending every frame avoids those misses by increasing decoding,
payload, latency, and model work.

Signum sits between those extremes:

```text
video
  -> low-resolution scheduled candidates + per-frame spike guard
  -> frame difference, histogram change, and motion scores
  -> temporal spacing and duplicate suppression
  -> original-resolution frames + timestamped timeline
```

There are no learned weights or hidden model calls in the deterministic core.
The same video and settings produce the same selected source frames.

## Current evidence

| Evaluation | Signum | Equal-budget uniform | Status |
|---|---:|---:|---|
| Seven-case synthetic sampler suite | 1.000 event recall | 0.429 | Deterministic regression only |
| 180-event development detector suite | 164/180 | 86/180 | Used during tuning; not held out |
| Fresh V4 held-out collection | Pending | Pending | Independent human review incomplete |

The synthetic suite uses six observations per six-second case. The development
suite used 473 observations for each method after a detector default was
selected on that suite. Neither result establishes real-world semantic
accuracy, provider superiority, or cost savings.

Protocols, collection outcomes, frozen manifests, review locks, failure
records, and detailed limitations live in
[Signum Benchmarks](https://github.com/consol0302/signum-benchmarks).

## Install

Signum requires Python 3.11 or newer.

```bash
git clone https://github.com/consol0302/Signum.git
cd Signum
python -m pip install -e .
```

OpenCV is the only substantial runtime dependency. A GPU and separate FFmpeg
installation are not required, although codec support depends on the installed
OpenCV build.

## Select event-rich frames

```bash
signum analyze input.mp4 --budget 32 --output output
```

The output is deliberately simple:

```text
output/
  frames/
    frame_000000000_00000000.000s.jpg
    ...
  timeline.json
  report.json
```

`timeline.json` records every selected frame index, source timestamp, source
interval, score, and signal value. `report.json` records the source metadata,
configuration, processing counts, timings, and measured redundancy.

Useful controls include `--candidate-hz`, `--analysis-width`,
`--min-distance`, `--coverage-fraction`, `--no-spike-guard`, and
`--strategy uniform` for the baseline.

## Observe screen changes with Codex

The optional observation path separates deterministic detection from semantic
interpretation:

```bash
signum observe screen-recording.mp4 \
  --goal "Wait until the export finishes and identify the next safe action" \
  --output observe-output
```

Each stable changed screen or preserved short transition becomes one structured
Codex observation. This mode requires an authenticated
[Codex CLI](https://developers.openai.com/codex/cli/) session. Signum does not
read or store the credential.

Codex use remains outside the deterministic sampler. Missing usage records,
timeouts, schema failures, and unsuccessful action verification stay visible
in the output instead of being estimated away.

## Stream caller-provided frames

`StreamingPerceptionGateway` accepts BGR frames from an external controller.
CPU detection runs during `submit_frame` while semantic interpretation runs on
a bounded background worker.

```python
from signum.gateway import GatewayConfig
from signum.interpreters import CodexExecInterpreter
from signum.streaming import StreamingConfig, StreamingPerceptionGateway

gateway = StreamingPerceptionGateway(
    goal="Verify that the form was submitted",
    interpreter=CodexExecInterpreter(model="MODEL_NAME"),
    gateway_config=GatewayConfig(),
    streaming_config=StreamingConfig(),
)

try:
    for frame_index, frame, timestamp in controller_frames():
        gateway.submit_frame(frame, timestamp, frame_index=frame_index)
        for result in gateway.poll_results():
            handle(result.to_dict())
finally:
    gateway.close(wait=True, timeout=120)
```

Signum does not capture the desktop or execute actions. The controller owns
capture, action timing, and the decision to wait for a verification result.
See [Streaming perception runtime](docs/STREAMING.md).

## Evaluate labeled recordings

The replay evaluator gives Signum and uniform temporal sampling exactly the
same observation budget:

```bash
signum evaluate examples/real-evaluation.example.json \
  --output evaluation-output
```

It reports trigger recall, calls per minute, false calls, confidence intervals,
category breakdowns, and saved evidence for review. Semantic and task-state
rates remain incomplete until the required human verdicts are present. See
[Real-world perception evaluation](docs/REAL_WORLD_EVALUATION.md).

## Reproduce the core checks

```bash
python -m unittest discover -s tests -v
python -m signum.benchmark --output benchmark-output
```

The synthetic benchmark compares the current hybrid selector, the previous
no-spike-guard variant, score-only selection, and uniform sampling at the same
frame budget. See [Benchmark methodology](docs/BENCHMARK.md) and
[Results](docs/RESULTS.md).

## Project boundaries

- CPU-first; GPU acceleration may only be optional.
- Deterministic core; provider integration stays outside selection logic.
- Video only in the current milestone; audio is not implemented.
- No desktop capture, action execution, server, database, or realtime control
  framework.
- Every meaningful sampler change must be compared with equal-budget uniform
  sampling.
- Failures and incomplete evidence are reported, not tuned away.

## Documentation

- [Architecture](ARCHITECTURE.md)
- [MVP scope](docs/MVP.md)
- [Benchmark methodology](docs/BENCHMARK.md)
- [Measured results](docs/RESULTS.md)
- [Real-world evaluation](docs/REAL_WORLD_EVALUATION.md)
- [Streaming integration](docs/STREAMING.md)
- [Roadmap](docs/ROADMAP.md)
- [Full benchmark archive](https://github.com/consol0302/signum-benchmarks)

Signum is currently at `0.0.2`. The API and output schema may change while the
approach is being validated.
