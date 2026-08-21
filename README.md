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

The CLI accepts video files. The Python streaming runtime also accepts live frames supplied by a controller such as Petasos. Desktop capture, audio, action execution, and non-Codex model providers are not implemented inside Signum.

## Current evidence

The latest local development Pilot has 65 labels, 60 independent source transitions, and eight real failed actions. Signum triggered 65/65 labels while equal-budget uniform sampling triggered 22/65 at the same 93-observation budget. This is a detector regression result, not a production accuracy claim: the workflows are correlated, the recordings were used during development, and no native-provider comparison has completed.

A final stratified Codex batch described 18/18 sampled states consistently with the saved evidence and returned the expected verdict for four action checks, with zero provisional false confirmations across two failed actions. Those judgments are not yet independently human-reviewed. OpenAI and Anthropic paid API comparisons were not run because no API keys were available.

The one-shot public-web v3 collection retained all 45 attempts and selected the first 30 independently valid recordings in preregistered order. A conservative action-anchored inventory found 143 eligible visible transitions, not 180. It assigns no label to three pointer-only or repeated actions without independent visible evidence and is explicitly marked as pending human review. The remaining frozen deficit is 18 loading-completion events and 19 action-failure events. No model has been run on this collection, and the deficit will be filled only by a separately preregistered supplement.

See [Pilot 60 local measurement](docs/PILOT60_RESULTS.md) for the exact counts, confidence intervals, token measurements, label corrections, and blockers. No claim that Signum is more accurate or cheaper than OpenAI or Claude computer use is currently supported.

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

Each initial or stable changed screen becomes one Codex call. A 768-pixel-wide local guard supplements the 192-pixel global detector, allowing a compact connected change to trigger even when its full-screen area fraction is tiny. Global trigger decisions still use the cheap 192-pixel signal, but crop coordinates come from the 768-pixel map so thin UI evidence is not clipped by coarse localization. Short transitions keep their highest-change frame so a disappearing notification is not replaced by the later background. The final unfinished transition is emitted when the video ends.

Codex is launched non-interactively with attached JPEG files, a strict JSON schema, an ephemeral session, and a read-only sandbox. User configuration is ignored for the perception run, while Codex authentication remains available. You may override the executable, model, or timeout:

On Windows, the default `codex` command prefers `%APPDATA%\npm\codex.cmd` when it exists. This avoids selecting the protected desktop-app executable through the Windows application alias. An explicit `--codex-command` is never rewritten.

```text
--codex-command   Codex executable or absolute path (default: codex)
--model           optional Codex model override
--codex-timeout   maximum seconds per observation (default: 120)
--local-analysis-width          local UI guard width (default: 768)
--min-local-component-pixels    minimum connected local change (default: 12)
```

The output contains the exact event images under `events/` and structured results in `observations.json`. Codex usage limits still depend on the signed-in plan, so this mode is deliberately event-driven rather than frame-driven.

`observations.json` also records the usage reported by each completed Codex turn:

- input, cached-input, output, and reasoning-output tokens;
- total reported tokens, defined as input plus output tokens;
- per-call latency and whether every call supplied a usage record;
- encoded image bytes, pixels, and the unadjusted number of 32-pixel image patches sent.

The patch count is a stable payload measurement, not a prediction of billed tokens. Image resizing, detail policy, and model-specific accounting happen beyond Signum's deterministic boundary. Missing Codex usage is left as `null` per observation and counted under `ai_calls_without_reported_usage` instead of being estimated as zero. An aggregate is partial whenever `reported_usage_complete` is false, and remains `null` when no call supplied usage. The observation file uses schema version 2 for these fields.

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

### Stream frames without blocking on Codex

`StreamingPerceptionGateway` runs deterministic detection during frame submission and sends semantic work to a background worker. New frames continue to be inspected while a Codex turn is running. It keeps a bounded recent-frame buffer and event history, exposes queue overflow instead of hiding it, and supports requested detail crops, explicit event retries, and action verification.

```python
with StreamingPerceptionGateway(
    goal="Watch the page and verify each action",
    interpreter=CodexExecInterpreter(model="MODEL_NAME"),
) as gateway:
    gateway.submit_frame(frame, timestamp, frame_index=frame_index)
    results = gateway.poll_results()
```

Petasos remains responsible for capture, action timing, and deciding when it must wait for a verification result. See [Streaming perception runtime](docs/STREAMING.md) for the integration contract and overload behavior.

The reproducible browser smoke workflow, review rubric, measured latency, and runtime-reported token cost are documented in [Measuring live Codex perception](docs/CODEX_LIVE_MEASUREMENT.md). A tracked example replays three captured Selenium page states through the same streaming path:

```powershell
python examples/codex_live_web_probe.py `
  --frames-dir C:\path\to\captured-frames `
  --output live-web-output `
  --model gpt-5.6-sol
```

The same captures can be converted into a labeled equal-budget evaluation without committing generated media:

```powershell
python examples/build_live_web_pilot.py `
  --frames-dir benchmark-output/live-web `
  --output benchmark-output/live-web-pilot
```

A larger local replay can be built from the fixed-viewport public-web captures:

```powershell
python examples/build_pilot60_from_captures.py `
  --captures benchmark-output/pilot60-captures `
  --selenium-frames benchmark-output/live-web `
  --completion-captures benchmark-output/heldout-candidates `
  --output benchmark-output/pilot60-suite
```

The optional completion captures add four real rejected actions and one
independent successful action. Their SHA-256 hashes are fixed in the builder.
The resulting 65-label development Pilot has 60 independent transitions and
enough real failed actions to pass the Pilot profile. It was collected after
the original deficit was known, so it is not the larger held-out comparison
suite. Raw captures and generated videos remain in ignored output directories.

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

### Evaluate real screen recordings

Signum can replay a labeled recording suite and compare the gateway with uniform temporal sampling at exactly the same observation count per recording:

```bash
signum evaluate real-evaluation.json --output evaluation-output
```

Add `--with-codex --model MODEL_NAME` to interpret both methods and collect their runtime-reported token usage. The run produces an `evaluation.json`, saved evidence for both methods, and a `review-template.json`. Trigger recall and false calls are automatic. Visible-evidence recall, semantic accuracy, task-state accuracy, and end-to-end success require explicit human verdicts:

```bash
signum score evaluation-output/evaluation.json \
  --reviews evaluation-output/completed-review.json
```

New evaluation manifests use schema version 2 and label each event by category and risk. Audit the planned 60-event pilot distribution before running Codex:

```bash
signum audit-manifest real-evaluation.json
```

Freeze development data before running or tuning against it:

```bash
signum freeze-manifest real-evaluation.json \
  --output evaluation-freeze.json \
  --role development
```

A claim-grade held-out suite cannot be created by changing that role string.
The 180-event plan must be locked before recording, contain at least 30 planned
workflow candidates, use the fixed category distribution, and point to an
immutable protocol commit:

```bash
signum preregister-heldout held-out/plan.json \
  --output held-out/preregistration.json

# Record and label only after publishing the plan and preregistration lock.
signum audit-manifest held-out/manifest.json --profile claim180
signum freeze-manifest held-out/manifest.json \
  --output held-out/freeze.json \
  --role held_out \
  --preregistration held-out/preregistration.json \
  --collection-summary held-out/collection-result.json \
  --collection-root held-out/captures
```

The template is [heldout180-plan.example.json](examples/heldout180-plan.example.json),
and the collection rules are in [Held-out 180 collection](docs/HELDOUT180.md).
The repository's public v3 collection uses a 45-case ordered pool and keeps all
failed attempts. Its conservative inventory exposed a 37-event deficit before
any model run. A deficit-only supplement must bind that exact base evidence,
predeclare one target event per candidate, and select the first independently
valid target events by category in plan order:

```bash
signum preregister-claim180-supplement held-out/supplement-plan.json \
  --output held-out/supplement-preregistration.json
```

The command rejects changed base artifacts, unplanned categories, failure
targets without a preregistered failed outcome, and loading targets that are not
successful asynchronous `wait_for` actions. It creates an acquisition lock; it
does not turn mechanically anchored events into reviewed ground truth.

### Replay native computer-use perception

The native benchmark adapter gives a provider its documented computer tool,
not a generic image prompt. It replays frozen, event-checkpoint source screens,
honors screenshot retries, honors Claude zoom crops, refuses action execution,
and records every request, image byte, turn, token, failure, latency, and priced
run. It selects labels independently of Signum and uniform trigger results, so
detector misses cannot disappear from the provider sample.

```powershell
python examples/native_computer_use_probe.py `
  --provider openai `
  --model MODEL_NAME `
  --evaluation evaluation-output/evaluation.json `
  --output native-openai `
  --case-id workflow-01

python examples/native_computer_use_probe.py `
  --provider anthropic `
  --model MODEL_NAME `
  --evaluation evaluation-output/evaluation.json `
  --output native-claude `
  --case-id workflow-01
```

The adapter reads `OPENAI_API_KEY` or `ANTHROPIC_API_KEY`. A priced run also
requires explicit input/output rates plus `--pricing-source` and
`--pricing-accessed-at`; missing keys produce a machine-readable `not_run`
artifact rather than a zero-cost result. This is an event-checkpoint,
perception-only replay. It does not measure either provider's full autonomous
computer-use product.

Evaluation and review reports include category breakdowns, two-sided 95% Wilson confidence intervals, exact action-verification accuracy, and a separate false-confirmation rate for failed-action cases. Action labels provide before/after timestamps and are forced equally for both methods outside the passive observation budget. See [Pilot 60 perception suite](docs/PILOT60.md) for the collection contract.

Incomplete reviews remain `null`; detector misses count as failures. The manifest format, review rubric, and output fields are documented in [Real-world perception evaluation](docs/REAL_WORLD_EVALUATION.md).

## Development

Run the test suite:

```bash
python -m unittest discover -s tests -v
```

The test suite covers the CLI, budget handling, timestamps, duplicate handling, deterministic selection, between-sample flash recovery, small and thin UI changes, transient peak preservation, forced action verification, end-of-stream flushing, observation serialization, runtime usage accounting, labeled replay evaluation, equal-budget comparison, confidence intervals, category coverage auditing, false-confirmation scoring, human review scoring, non-blocking streaming, overload visibility, requested detail, retries, and the isolated Codex command and verification contracts. Tests do not spend Codex subscription usage.

The 65-label development Pilot now passes its category, independent-transition,
and real failed-action audit. Signum triggered 65/65 labels while equal-budget
uniform sampling triggered 22/65, but the Pilot is not held out and has no
independent blind review or paid native-provider runs. It therefore cannot
establish superiority over OpenAI or Claude computer use. The machine-enforced
publication threshold is documented in
[Comparative claim protocol](docs/CLAIM_PROTOCOL.md).

## Project notes

- [Architecture](ARCHITECTURE.md)
- [MVP scope](docs/MVP.md)
- [Benchmark methodology](docs/BENCHMARK.md)
- [Initial results](docs/RESULTS.md)
- [Codex-mode improvement roadmap](docs/ROADMAP.md)
- [Real-world perception evaluation](docs/REAL_WORLD_EVALUATION.md)
- [Pilot 60 perception suite](docs/PILOT60.md)
- [Pilot 60 local measurement](docs/PILOT60_RESULTS.md)
- [Comparative claim protocol](docs/CLAIM_PROTOCOL.md)
- [Held-out 180 collection](docs/HELDOUT180.md)
- [Timestamped browser capture](docs/CAPTURE_PROTOCOL.md)
- [Streaming perception runtime](docs/STREAMING.md)
- [Measuring live Codex perception](docs/CODEX_LIVE_MEASUREMENT.md)

Signum is currently at `0.0.2`. The API and output schema may still change while the core sampling approach is being validated.
