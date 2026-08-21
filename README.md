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

The one-shot public-web v3 collection retained all 45 attempts and selected the first 30 independently valid recordings in preregistered order. A conservative action-anchored inventory found 143 eligible visible transitions, not 180. It assigns no label to three pointer-only or repeated actions without independent visible evidence and is explicitly marked as pending human review. The audit exposed a frozen deficit of 18 loading-completion events and 19 action-failure events. No model was run before the deficit and its supplement procedure were fixed.

That supplement has now completed under its published acquisition lock. All 52
attempts were retained: independent verification found 48 valid captures,
three invalid captures, one startup failure, and no missing attempt. The frozen
first-valid rule selected exactly 18 loading-completion and 19 action-failure
events. The reproducible supplement collection id is
`355c99a227b3a893d47ef4b3dfcffd769a0603f73fc2925c99552a4f42057390`.
This closes the mechanical 180-event capacity deficit; it does not replace
human label review or establish an OpenAI/Claude accuracy or cost claim.

The 143-event V3 inventory and 37-event supplement inventory have been combined
without reusing a source transition. The composite inventory contains exactly
180 eligible events across 67 workflows and matches the frozen Claim 180
category distribution. Its inventory id is
`ca24e78e5bfe081a3ecced64817d331f646759e4739a5d0f0d1eeda28494bde5`.
It remains mechanically anchored and pending human review, so comparative model
runs have not started.

As a development-only detector validation, the previous two-stable-frame
default found 122/180 transitions while equal-budget uniform sampling found
79/180. Changing only the default to one stable frame raised Signum to 164/180
with 473 observations; uniform found 86/180 at that same budget. Cooldown,
active-timeout, and smaller local-component experiments did not improve the
tradeoff and were rejected. Because this suite was used to choose the setting,
it is not the final held-out claim suite.

The repository now includes a method-blind ground-truth workflow for the next
fresh suite. `examples/build_ground_truth_review_packet.py` randomizes the
frozen before/after evidence and keeps case identities in a coordinator-only
mapping. Two independent reviewers complete every verdict before any method is
run; `examples/compare_ground_truth_reviews.py` sends every disagreement or
negative verdict to adjudication. This protects the labels from detector and
provider-output leakage, but it does not itself establish a comparative claim.

The fresh V4 candidate plan was collected once after its plan and acquisition
lock were pushed. It contains
30 balanced slots with two ordered candidates per slot, exactly six target
events per candidate, and the fixed 180-event category distribution. The 60
candidates are split evenly across three domains absent from earlier plans:
PlayLab, QA Practice Hub, and TestPages. Reconnaissance covered all 17 unique
domain/template combinations without running Signum or any provider model;
17/17 captures passed independent integrity, timing, action, and target-frame
checks. This validated collection mechanics only. The collector revision is
`b6025b84d4498c682a76273e8540c63032d8e83e` and the plan-builder revision is
`67c821dc38bc07e38816a5f39030a607222a0f83`. The plan and pre-collection lock
are now public. The reproducible preregistration id is
`02912857cf4064f23311ba722c546c3d6297658afb189fecb2e7e76fd531fc02`.
The final run retained all 60 attempts. Independent verification found 56
valid and four invalid captures, with no missing or startup-failed attempt.
Every slot had a valid candidate, so the frozen first-valid-per-slot rule
selected 30 cases. The collection id is
`5f8ece1a7830d45c65dca4c8b2de837cd40c3c8eeb7e4c729081b4c248a6bbdf`.
No detector or provider output was generated before selection.

The selected captures were encoded at 30 fps with complete output-to-source
timestamp maps. The preregistered six actions per slot produce a mechanically
anchored 180-event inventory with id
`39b53be53fd6c090519aa819e4576007c7a9cce24e527983045689b9cebfe050`.
An exact-pixel audit found that immediate post-action anchors left 15/180
before/after pairs identical. Applying one fixed 0.3-second settle delay to all
events reduced that to 2/180 without crossing a following action. Both
remaining cases are the same TestPages hover target. This is a disclosed
ground-truth visibility deficit, not a detector result. The method-blind review
packet id is
`341033d585d5279c4286bac7251dfcca48a38b1c9cbd3ee836f341f444f66e5d`;
its 360 images, coordinator mapping, packet, and reviewer templates are bound by
review lock `d2a139ef087a903020bb868aa84189f2fd86558a9b4fe88ff41ad0e3a796f725`.
two independent human reviews and adjudication are still required before the
suite can be frozen or any comparative claim can be assessed.

A conditional eight-candidate visibility reserve is also published, but no
reserve capture can replace a V4 event by default. It has two ordered slots of
four fresh post-lock candidates and targets only `cursor_hover_focus`. Its
preregistration id is
`6372f02eb8094223ce5325793e33bd3769517ca57c26ee135c1d9568933cf00a`.
Activation requires both independent reviewers and adjudication to mark the
two named TestPages transitions invisible. The reserve remains ineligible if
that condition is not met, and method output remains forbidden before its
selection.

The first reserve acquisition retained eight startup failures caused by the
capture environment returning `ERR_NETWORK_ACCESS_DENIED`; it selected no
event and has collection id
`14f15891168648938ae6bcd60e9069c650cca30e0d152f4a640937cb6c5cf4e9`.
Those case ids will not be retried. A second-round pool uses new case ids and
binds the complete failed first-round summary before it can be preregistered.

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

V4 replaces the global first-valid rule with balanced per-slot selection. Every
slot has a primary and alternate workflow with the same six category targets.
Both candidates are attempted once and retained; the first independently valid
candidate in that slot is selected. A valid capture must cover the full
requested interval, stay within its frozen frame-gap bound, complete all
required actions, and retain at least one post-completion frame for every target
before the following action starts. Model outputs remain forbidden until all 60
attempts are collected, verified, and selected by that frozen rule.

```powershell
python examples/build_claim180_v4_candidates.py `
  --sources benchmark-protocol/claim180-v4-candidate-sources.json `
  --actions benchmark-protocol/actions-v4 `
  --manifest benchmark-protocol/claim180-v4-actions-manifest.json `
  --collector-revision b6025b84d4498c682a76273e8540c63032d8e83e `
  --check

python examples/build_claim180_v4_plan.py `
  --template benchmark-protocol/claim180-plan-v3.json `
  --sources benchmark-protocol/claim180-v4-candidate-sources.json `
  --actions-manifest benchmark-protocol/claim180-v4-actions-manifest.json `
  --output benchmark-protocol/claim180-plan-v4.json `
  --protocol-revision 67c821dc38bc07e38816a5f39030a607222a0f83 `
  --check

signum preregister-heldout benchmark-protocol/claim180-plan-v4.json `
  --output benchmark-protocol/claim180-preregistration-v4.json

python examples/verify_browser_collection.py `
  --root benchmark-output/claim180-v4-heldout-captures `
  --plan benchmark-protocol/claim180-plan-v4.json

python examples/summarize_claim180_collection.py `
  --root benchmark-output/claim180-v4-heldout-captures `
  --plan benchmark-protocol/claim180-plan-v4.json `
  --preregistration benchmark-protocol/claim180-preregistration-v4.json `
  --output benchmark-protocol/claim180-v4-collection-result.json

python examples/encode_selected_claim180.py `
  --collection-root benchmark-output/claim180-v4-heldout-captures `
  --summary benchmark-protocol/claim180-v4-collection-result.json `
  --fps 30

python examples/build_claim180_v4_event_inventory.py `
  --summary benchmark-protocol/claim180-v4-collection-result.json `
  --collection-root benchmark-output/claim180-v4-heldout-captures `
  --plan benchmark-protocol/claim180-plan-v4.json `
  --output benchmark-protocol/claim180-v4-event-inventory.json

python examples/build_ground_truth_review_packet.py `
  --inventory benchmark-protocol/claim180-v4-event-inventory.json `
  --v4-root benchmark-output/claim180-v4-heldout-captures `
  --output benchmark-output/claim180-v4-ground-truth-review `
  --seed claim180-v4-ground-truth-v1

python examples/lock_ground_truth_review_packet.py `
  --packet-root benchmark-output/claim180-v4-ground-truth-review `
  --output benchmark-protocol/claim180-v4-review-packet-lock.json
```

The repository now also contains the deterministic supplement candidate
builder and its generated 52-case action pool: 26 loading-completion candidates
and 26 action-failure candidates across seven public test domains. Every case
declares exactly one scored target action; setup actions are retained but are
not scored. The collection runner executes the published manifest in order,
does not retry cases, refuses to overwrite an existing output directory, and
preserves collector failures. A reconnaissance run is used only to remove
broken locators or structurally uncapturable workflows; it is not claim
evidence. The final collection will begin only after the candidate revision,
supplement plan, and acquisition lock are published.

The supplement plan is now bound to candidate revision
`6f9dbd67e682c6e168e5b87a478e3cb768cf9fff`. Its acquisition lock has
preregistration id
`47b7d0f2f69164fe5362e345ddbf19821022147830314717e063235a0133b7c5`.
Independent batch verification and the category-aware first-valid summarizer
are included with the lock so their selection behavior is public before the
one-shot collection begins.

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
