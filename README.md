# Signum

Signum is an experiment in reducing how much video a multimodal model needs to inspect.

Most video is repetitive. Passing frames at a fixed interval is cheap, but it can miss short events. Passing every frame avoids that problem and creates a much larger one: unnecessary decoding, tokens, latency, and cost. Signum sits in front of that pipeline and uses ordinary image-processing signals to decide which moments are worth keeping.

The deterministic core runs on the CPU and keeps enough source information to recover every selected frame later. An experimental Codex mode can interpret gated screen events through a locally authenticated Codex CLI. It does not use an API key.

## What it does

```text
video
  -> low-resolution scheduled candidates + per-frame spike guard
  -> frame difference, histogram change, and motion scores
  -> temporal spacing and duplicate suppression
  -> original-resolution frames + a timestamped timeline
```

The Codex observation path is separate from the sampler:

```text
screen recording
  -> low-resolution global change + higher-resolution local component guard
  -> wait for a stable screen or preserve a short transition peak
  -> current context + changed-region crop
  -> codex exec with a strict JSON output schema
  -> observations.json
```

The current release accepts video files only. Live screen capture, audio, action execution, and non-Codex model providers are not implemented.

## Install

Signum requires Python 3.11 or newer.

```bash
git clone https://github.com/consol0302/Signum.git
cd Signum
python -m pip install -e .
```

OpenCV is the only substantial runtime dependency. No GPU or separate FFmpeg installation is required, although codec support still depends on the OpenCV build available on your system.

Codex mode also requires a working [Codex CLI](https://learn.chatgpt.com/docs/developer-commands?surface=cli) authenticated with `codex login`. ChatGPT subscription authentication is handled by Codex itself; Signum never reads or stores the credential.

## Use

```bash
signum analyze input.mp4 --budget 32 --output output
```

The output directory looks like this:

```text
output/
  frames/
    frame_000000000_00000000.000s.jpg
    ...
  timeline.json
  report.json
```

`timeline.json` contains the selected frame index, timestamp, source interval, score, and signal values. `report.json` records the input metadata, sampler settings, candidate count, timing, and measured redundancy.

Useful options:

```text
--candidate-hz       candidate analysis rate (default: 4)
--analysis-width     maximum analysis width (default: 192)
--min-distance       preferred spacing between selections (default: 0.5s)
--coverage-fraction  budget reserved for timeline coverage (default: 0.25)
--no-spike-guard     disable abrupt-change checks between scheduled candidates
--strategy           hybrid, score_only, or uniform
```

### Observe with Codex

```bash
signum observe screen-recording.mp4 \
  --goal "Wait until the export finishes and identify the next safe action" \
  --output observe-output
```

Each initial or stable changed screen becomes one Codex call. A 768-pixel-wide local guard supplements the 192-pixel global detector, allowing a compact connected change to trigger even when its full-screen area fraction is tiny. Short transitions keep their highest-change frame so a disappearing notification is not replaced by the later background. The final unfinished transition is emitted when the video ends.

Codex is launched non-interactively with attached JPEG files, a strict JSON schema, an ephemeral session, and a read-only sandbox. User configuration is ignored for the perception run, while Codex authentication remains available. You may override the executable, model, or timeout:

```text
--codex-command   Codex executable or absolute path (default: codex)
--model           optional Codex model override
--codex-timeout   maximum seconds per observation (default: 120)
--local-analysis-width          local UI guard width (default: 768)
--min-local-component-pixels    minimum connected local change (default: 12)
```

The output contains the exact event images under `events/` and structured results in `observations.json`. Codex usage limits still depend on the signed-in plan, so this mode is deliberately event-driven rather than frame-driven.

### Verify after a computer action

A computer-use controller can bypass passive stability gating after every click, keypress, or tool action:

```python
observation = gateway.verify_after_action(
    pre_action_frame,
    post_action_frame,
    timestamp,
    goal="Save the document",
    action="clicked Save",
    expected_result="a saved confirmation is visible",
)
```

This always emits an observation, including when the screen did not change. Codex returns `confirmed`, `not_confirmed`, or `uncertain` for action-verification events; ordinary observations use `not_applicable`. Signum still does not execute the action itself.

## How selection works

Frames are decoded sequentially. Signum performs the regular analysis at 4 Hz by default and keeps a 16×9 grayscale signature for every decoded frame. That tiny per-frame check acts as a guard for abrupt changes which happen between scheduled candidates; it does not require a second decode pass.

The regular candidate analysis calculates three simple signals:

- mean pixel difference;
- grayscale histogram distance;
- the fraction of pixels that changed beyond a fixed threshold.

The signals are normalized within the video and combined into an importance score. The default `hybrid` selector reserves part of the frame budget for timeline coverage and uses the rest for high-scoring moments. Near-identical compact frame signatures are skipped when a distinct alternative exists.

There are no learned weights or hidden model calls in `signum analyze`. Given the same video and settings, selection is deterministic. `signum observe` preserves the deterministic gate metadata, but its semantic result depends on Codex.

## Benchmark

The repository includes a deterministic synthetic benchmark with seven cases: short motion in a static scene, hard cuts, slow change, a one-frame flash, continuous motion, repetitive motion, and camera-like panning.

Run it with:

```bash
python -m signum.benchmark --output benchmark-output
```

The first local run used six observations per six-second video:

| Method | Mean event recall | Temporal coverage | Redundancy |
| --- | ---: | ---: | ---: |
| Uniform | 0.429 | 1.000 | 0.500 |
| Hybrid without spike guard | 0.857 | 0.643 | 0.429 |
| Hybrid | 1.000 | 0.667 | 0.405 |

These numbers are useful for checking the mechanics, not for claiming real-world performance. The spike guard recovered the one-frame full-screen flash that previously fell between candidate samples. Across ten repeated runs, median analysis time increased from 6.89 ms to 12.24 ms on these small fixtures. Brief local changes can still be missed, and uniform sampling still requires no pixel analysis.

The benchmark setup and full notes are in [docs/BENCHMARK.md](docs/BENCHMARK.md) and [docs/RESULTS.md](docs/RESULTS.md).

## Development

Run the test suite:

```bash
python -m unittest discover -s tests -v
```

The project currently has thirteen tests covering the CLI, budget handling, timestamps, duplicate handling, deterministic selection, between-sample flash recovery, small local UI changes, transient peak preservation, forced action verification, end-of-stream flushing, observation serialization, and the isolated Codex command and verification contracts. Tests do not spend Codex subscription usage.

The next useful step is a small manually labeled screen-recording suite. It should measure trigger recall, semantic accuracy, task-state accuracy, calls per minute, and latency against fixed-interval Codex observations. Synthetic results alone cannot establish real computer-use detection success.

## Project notes

- [Architecture](ARCHITECTURE.md)
- [MVP scope](docs/MVP.md)
- [Benchmark methodology](docs/BENCHMARK.md)
- [Initial results](docs/RESULTS.md)
- [Codex-mode improvement roadmap](docs/ROADMAP.md)

Signum is currently at `0.0.2`. The API and output schema may still change while the core sampling approach is being validated.
