# Held-out 180 collection

This suite is the minimum claim-grade evidence set. It must be collected once,
after the protocol and plan are public, and must not be used to tune Signum.
Any workflow inspected while changing detector thresholds belongs in a new
development set instead.

The authoritative pre-collection lock is
`benchmark-protocol/claim180-preregistration-v2.json`. It supersedes the v1
lock by binding the development-validated collector plus all 30 action files
through `claim180-actions-manifest.json`. The v1 files remain tracked as
chronological evidence and must not be rewritten.

## Fixed distribution

| Category | Eligible independent transitions |
| --- | ---: |
| Small UI | 30 |
| Action success | 24 |
| Action failure | 24 |
| Popup or notification | 18 |
| Loading completion | 18 |
| Scroll or navigation | 15 |
| Cursor, hover, or focus | 15 |
| Animation or game HUD | 18 |
| Transient event | 18 |
| **Total** | **180** |

Use at least 30 distinct workflow recordings. Every label needs a unique
`source_transition_id`. Multiple labels describing the same state change do
not create independent evidence. Failed actions must be genuine rejected,
unchanged, contradicted, or visibly failed actions; constructed identical-frame
copies are ineligible.

## Before recording

1. Copy `examples/heldout180-plan.example.json` to an output area.
2. Replace the case ids with the exact 30 or more workflows to be recorded.
3. Freeze the evidence policy and per-event turn, screenshot, and zoom limits.
4. Set `protocol_revision` to the full commit hash containing the benchmark
   code and protocol. Commit and push the plan.
5. Run `signum preregister-heldout PLAN --output PREREGISTRATION`.
6. Commit and push the preregistration lock before opening the first workflow.
7. Validate the collector on a non-held-out development page, then commit and
   push that exact collector implementation and all 30 action JSON files before
   opening a preregistered workflow. Follow
   [Timestamped browser capture](CAPTURE_PROTOCOL.md).
8. Run the action generator in `--check` mode and publish
   `claim180-actions-manifest.json`, which records the validated collector
   revision and the byte count and SHA-256 of every action file.

The tool hashes the plan. It rejects a placeholder revision, a non-HTTPS
repository, fewer than 30 unique case ids, changed category targets, or missing
evidence/budget policies.

## Record and label

- Preserve the original capture timestamps, frame rate, dimensions, and source
  files. Do not recreate screen states as fixed-duration slides.
- Record one manifest case per preregistered case id and keep that order.
- For action labels, record the action, expected visible result, and exact
  before/after timestamps. Keep failures even when the screen is unchanged.
- Mark synthetic, constructed, ambiguous, corrupted, or policy-violating
  events `real_world_eligible: false`; do not replace them after seeing model
  output.
- Do not run Signum, uniform, Codex, OpenAI, or Claude on the held-out videos
  until collection and labels are complete.
- Document capture or labeling failures. Do not silently delete hard cases.

Then run:

```bash
signum audit-manifest held-out/manifest.json --profile claim180
signum freeze-manifest held-out/manifest.json \
  --output held-out/freeze.json \
  --role held_out \
  --preregistration held-out/preregistration.json
signum verify-freeze held-out/freeze.json
```

The held-out freeze fails if the manifest or a video predates the local
preregistration lock, planned case ids differ, Claim 180 is incomplete, or a
source transition is reused. The pushed pre-collection Git history is still
required as independent chronological evidence because filesystem timestamps
can be altered.

## Execute and review

Run every compared system on every eligible frozen event under the plan's
budget. Preserve API errors, budget exhaustion, unsupported actions, and empty
outputs as failures. Run at least three paired priced repetitions with pinned
models and cite the provider invoice or published price snapshot.

Give two reviewers anonymized system outputs and identical frozen review
artifacts. They independently score visible evidence, semantic correctness,
safe task state, and false confirmation. Adjudicate disagreements without
changing model output. Only then build the comparison file and run
`signum assess-claim`.
