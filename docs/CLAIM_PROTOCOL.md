# Comparative claim protocol

Signum may claim an accuracy or cost advantage only when `signum assess-claim`
accepts a frozen comparison. A detector-only win over uniform temporal sampling
does not establish an advantage over OpenAI or Claude computer use.

## Two separate comparisons

The benchmark reports two tracks and never merges them into one score.

1. `controlled_vision` gives every model the same saved screenshots, prompt,
   observation budget, and output schema. This isolates visual perception.
2. `event_checkpoint_native_replay` gives each provider its documented
   computer-use tool contract at the same frozen event checkpoints and allows
   screenshot retries plus documented zoom behavior. Every extra screenshot
   and model turn counts toward cost and latency. Click, type, scroll, and
   navigation requests fail visibly because action execution is outside the
   perception comparison.

OpenAI's current Responses computer tool emits `computer_call` actions and
accepts `computer_call_output` screenshots. The comparator uses that current
contract rather than treating the deprecated preview snapshot as the product:
[OpenAI computer-use guide](https://developers.openai.com/api/docs/guides/tools-computer-use).

Claude computer use is a client-side tool loop. The current enhanced tool can
request a full-resolution zoom region, so the native track must honor that
request and charge the additional screenshot and turn:
[Claude computer use](https://platform.claude.com/docs/en/agents-and-tools/tool-use/computer-use-tool).

`examples/provider_api_probe.py` implements `controlled_vision`.
`examples/native_computer_use_probe.py` implements the separate native event
checkpoint replay. Native selection reads frozen eligible labels directly and
does not consult either method's `triggered` field. Label notes, acceptable
states, and event categories remain hidden from the provider prompt.

The native track is intentionally scoped. It can support a claim about the
specified perception replay, not a blanket claim about the full OpenAI or
Claude autonomous computer-use product. Passive event checkpoints are
label-aligned and therefore favorable to the baseline; that choice and its
cost consequence must remain visible in the publication.

## Freeze before evaluation

Create a public, immutable protocol anchor and preregister the collection before
recording any held-out workflow:

```bash
signum preregister-heldout held-out/plan.json \
  --output held-out/preregistration.json

# Commit and push the plan and preregistration before collecting recordings.
signum audit-manifest held-out/manifest.json --profile claim180
signum freeze-manifest held-out/manifest.json \
  --output held-out/freeze.json \
  --role held_out \
  --preregistration held-out/preregistration.json

signum verify-freeze held-out/freeze.json
```

The preregistration locks the exact case ids, Claim 180 category targets,
evidence policy, observation budget, repository, and full protocol commit hash.
The held-out freeze rejects recordings or manifests that predate that local
lock, case-id changes, incomplete Claim 180 coverage, and duplicate source
transitions. The final lock hashes the preregistration, manifest, and every
video. A public Git history remains the external evidence that the lock really
preceded collection; local timestamps alone are not presented as proof.

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

Every system must also list distinct raw run artifacts with their relative
path, byte count, and SHA-256. The review contract lists one similarly sealed
artifact per reviewer plus a sealed adjudication artifact. `assess-claim`
recomputes every hash and blocks publication if a file is absent, outside the
comparison directory, reused as another run, or changed after assembly. This
provides artifact integrity; it does not prove that a named reviewer is human,
so reviewer identity and independence still require publication-level audit.

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

The native replay state machine and Claim 180 preregistration gate are now
implemented and covered by offline fixtures. Actual OpenAI and Anthropic runs
remain `not_run` because this environment has neither provider API key. No
accuracy or cost claim is currently supported.
