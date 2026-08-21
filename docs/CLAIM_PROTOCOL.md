# Comparative claim protocol

Signum may claim an accuracy or cost advantage only when `signum assess-claim`
accepts a frozen comparison. A detector-only win over uniform temporal sampling
does not establish an advantage over OpenAI or Claude computer use.

## Two separate comparisons

The benchmark reports two tracks and never merges them into one score.

1. `controlled_vision` gives every model the same saved screenshots, prompt,
   observation budget, and output schema. This isolates visual perception.
2. `native_computer_use` gives each provider its documented computer-use tool
   contract and allows its normal screenshot, retry, and zoom behavior. Every
   extra screenshot and model turn counts toward cost and latency.

OpenAI's Responses API accepts image inputs and structured JSON outputs. Its
older `computer-use-preview` page currently marks the dated snapshot as
deprecated, so that preview cannot be the only OpenAI comparator:
[Responses API](https://developers.openai.com/api/reference/cli/resources/responses/methods/create),
[computer-use-preview](https://developers.openai.com/api/docs/models/computer-use-preview).

Claude computer use is a client-side tool loop. The current enhanced tool can
request a full-resolution zoom region, so the native track must honor that
request and charge the additional screenshot and turn:
[Claude computer use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool).

`examples/provider_api_probe.py` implements only `controlled_vision`. Its
reports state that mode explicitly. A native runner remains a separate
milestone.

## Freeze before evaluation

Create and verify a lock before tuning or provider execution:

```bash
signum freeze-manifest held-out/manifest.json \
  --output held-out/freeze.json \
  --role held_out

signum verify-freeze held-out/freeze.json
```

The lock hashes the manifest and every referenced video, records video
metadata, event categories, eligibility, and source transition ids. Claim
comparisons must cover every eligible frozen event. Reused eligible transition
ids or fewer than 30 distinct workflow recordings block a claim.

Use `--role development` for data collected after inspecting a failure or
benchmark deficit. Development locks are useful for reproducibility but are
never accepted as claim evidence.

## Minimum evidence

The default gate requires all of the following:

- at least 180 eligible paired events;
- at least 30 distinct workflow recordings;
- at least 20 real failed actions;
- two distinct human-blind reviewers and adjudicated disagreements;
- three paired cost runs using provider invoices or a cited published API
  price snapshot;
- complete coverage of the eligible frozen events by candidate and baseline.

The primary outcome is reviewed end-to-end perception success. A success
requires visible evidence, a correct semantic description, and a safe task
state. Failed actions also receive a false-confirmation verdict.

## Statistical decision

Workflows, not individual frames, are the resampling unit. The gate runs a
deterministic 20,000-sample cluster bootstrap and accepts either:

- accuracy superiority: the lower 95% bound of the paired accuracy difference
  is above zero, with no material false-confirmation regression; or
- cost advantage: the lower 95% accuracy-difference bound is at least -3
  percentage points, the false-confirmation difference is no worse than +1
  point, and every one of at least three paired runs costs no more than 70% of
  its baseline.

The cost gate accepts `provider_invoice` and `published_api_price`. Codex
subscription tokens, image bytes, or an amortized subscription estimate remain
diagnostics and cannot independently establish a billed-cost claim.

Run the final gate with:

```bash
signum assess-claim comparison.json --output claim-assessment.json
```

A nonzero exit means the claim is not supported. The output retains every
failed condition rather than producing a favorable sentence.

## Current status

The completed 65-label Pilot is frozen as `development`. It passes the Pilot
coverage audit but was assembled after the first audit exposed missing failed
actions and transitions. It is therefore useful for failure discovery and
regression testing, not for the final comparative claim.
