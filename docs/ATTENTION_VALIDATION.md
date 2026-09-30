# Attention implementation validation record

Date: 2026-09-30. Baseline: `a0583f68419bef658d3a030132f63208c2453cd1`.

## First CI run

Attention implementation commit: `e0b48dc0b2c7d6eb29e720237009a11876f5905c`.
GitHub Actions run: https://github.com/consol0302/Signum/actions/runs/36722758798
Job ID: `109911801510`. Artifact ID: `11102230951`.

- 86 tests passed, including 45 new attention invariants and 41 existing tests.
- Ubuntu runner, Python 3.11.16, NumPy 2.4.6, OpenCV headless 5.0.0.93.
- Existing synthetic sampler benchmark completed: hybrid recall 1.0,
  no-spike hybrid 0.8571428571428571, uniform 0.42857142857142855.
- Synthetic attention replay completed with no provider calls.

The tested source was subsequently downloaded from the CI artifact and all 86
tests passed locally with NumPy 2.3.5 and OpenCV 4.13.0. Adding the call ledger and
eight accounting tests brought the local suite to 94 passing tests. The PR's
latest CI status is authoritative for subsequent commits; it is not assumed here.

## Slow-change fixture

In the constructed 100-frame replay, the legacy gateway emitted at `[0.0]`;
attention emitted at `[0.0, 1.85, 2.75, 3.65, 4.55]`. Equal-budget uniform times
were `[0.5, 1.5, 2.5, 3.5, 4.5]`. A new question on an unchanged final image
produced `contract_changed`.

This demonstrates a mechanism for recovering cumulative drift. It INCREASED the
number of observations over the legacy detector; it does not prove cheaper
inference. The acknowledgement was a deterministic stub, not a semantic judge.
The fixture is development-only, not held out. No natural-video, art-perception,
provider cost or human-level visual-understanding result follows from it.

## Invariants covered

Static-frame suppression; cumulative changes; A-B-A and out-of-order rejection;
context/action invalidation; source-time freshness; missing capture; exact
historical crops; transient peaks; evidence byte/TTL limits; array ownership;
visible queue overflow; retries with new identities; global guard outside watched
regions; equal-luminance color changes; explicit internal reconsideration;
conservative reviewed repeat patterns; batching; incomplete accounting; and
one-call-many-packets usage without double counting.

## Unfinished evaluation, deliberately not claimed

No paid provider requests, invoice-based cost comparisons, independent human
semantic review, held-out V4 evaluation, live Petasos integration, calibrated
image-cost model, general animation classification or natural-camera motion
tracking were performed. Existing sampler defaults and frozen research records
were not changed. Use the opt-in path for experiments before any default switch.
