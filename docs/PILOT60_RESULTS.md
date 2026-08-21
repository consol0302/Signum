# Pilot 60 local measurement

This document records the 2026-08-21 local public-web measurement. It is a
failure-discovery run, not evidence that Signum is more accurate or cheaper
than OpenAI or Claude computer use.

## Dataset status

The generated manifest has the planned 60 labels and exact category totals,
but it does not pass the Pilot 60 audit:

| Audit item | Result |
| --- | ---: |
| Labels | 60 |
| Independent source transitions | 55 |
| Transitions used by more than one label | 5 |
| Real-world-eligible labels | 56 |
| Eligible failed-action labels | 4 / 8 required |
| `profile_complete` | `false` |

The source captures came from Selenium's dynamic page, The Internet test
pages, and Playwright's TodoMVC demo at an intended 1280×720 viewport. Two
browser states were captured at 1265×712 or 1280×712 after browser chrome
changed. The replay builder preserves those pixels and pads only the right and
bottom edges to the largest size in the case. It does not resize the source
content.

Three TodoMVC no-op labels and one Selenium no-op label use identical-frame
constructed replays. They remain useful for verifying the forced action path,
but `real_world_eligible` is false. Five other labels share a source transition
with another label. `audit-manifest` reports both conditions instead of
counting the suite as complete.

Build the local replay from captured PNG files:

```powershell
python examples/build_pilot60_from_captures.py `
  --captures benchmark-output/pilot60-captures `
  --selenium-frames benchmark-output/live-web `
  --output benchmark-output/pilot60-suite
```

Raw captures and generated videos remain ignored. The builder, labels, source
URLs, and limitations are tracked.

## Detector-only result

Both methods received the same passive observation count in every case. Forced
before/after action checks were added equally outside that passive budget.

| Metric | Signum | Equal-budget uniform |
| --- | ---: | ---: |
| Triggered labels | 60 / 60 | 17 / 60 |
| Trigger recall | 1.000 | 0.283 |
| 95% Wilson interval | 0.940–1.000 | 0.185–0.408 |
| Observations | 80 | 80 |
| Unmatched observations | 20 | 63 |
| Unmatched initial-state observations | 14 | 0 |
| Unmatched non-initial observations | 6 | 63 |

Thirteen original cases plus one constructed Selenium no-op case account for
Signum's 14 initial-state observations. They are model calls with no event
label, so the total unmatched count remains the cost-facing metric. The split
prevents required initial context from being confused with transition noise.

The 60/60 trigger result is not a production success rate. Labels are
correlated, replay timing is synthetic, four failed actions are constructed,
and the suite was used to find and correct annotation errors. A held-out suite
must be collected before tuning or making comparative claims.

## Label audit failures found by Codex

The semantic sample exposed two incorrect Selenium timestamps:

1. `box-added.png` was captured immediately after the click but still had no
   red box. The box first appeared in `box-settled.png`.
2. `input-revealed.png` still had no input. The input first appeared in
   `input-settled.png`.

Codex correctly rejected the premature success label. The labels were moved to
the first frames containing visible evidence, and the intermediate states were
labeled as pending transients. These corrections did not change detector
thresholds.

## Stratified Codex semantic sample

The final sample selected two eligible, independent transitions from each of
the nine Pilot 60 categories. Eighteen saved Signum observations were sent in
one structured `gpt-5.6-sol` Codex batch.

| Measurement | Result |
| --- | ---: |
| Events | 18 |
| Codex calls | 1 |
| Reported input tokens | 26,097 |
| Reported output tokens | 1,837 |
| Reported total tokens | 27,934 |
| Reasoning-output tokens | 42 |
| Semantic latency | 41.45 s |
| Provisional label-consistent descriptions | 18 / 18 |
| Provisional action verification | 4 / 4 |
| Provisional false confirmations | 0 / 2 failed actions |

The 18/18 assessment is an AI-assisted audit of the structured text and saved
evidence, not an independent human-blind score. The generated
`review-template.json` leaves every required verdict empty.

## Codex transport experiment

The same five Selenium evidence events were measured with three transports.
All three produced five label-consistent structured observations in the local
audit.

| Transport | Calls | Reported total tokens | Wall or semantic time |
| --- | ---: | ---: | ---: |
| One ephemeral `codex exec` per event | 5 | 75,795 | 36.26 s |
| One resumed Codex session | 5 | 85,866 | 47.33 s |
| One ephemeral structured batch | 1 | 17,218 | 17.58 s |

The resumed session was worse: tokens increased 13.3% and time increased
30.5%. Although it reported 47,616 cached-input tokens, the growing conversation
outweighed that cache. It is not the default transport.

The batch reduced reported tokens by 77.3% and time by 51.5% on this five-event
fixture. It is promising for deferred perception, but batching adds waiting
time and cannot replace immediate high-risk post-action verification without a
separate latency policy.

## External provider comparison

`examples/provider_api_probe.py` can send the same stratified saved evidence to
OpenAI's Responses API or Anthropic's Messages API without adding either
provider to Signum's deterministic core. No API keys were present, so both paid
runs are recorded as `not_run`; there are no OpenAI-versus-Claude accuracy or
cost results.

Before claiming that Signum is more accurate or cheaper, the remaining work is:

1. collect at least four more real failed actions and five more independent
   transitions, then freeze a held-out suite;
2. complete independent blind review for Signum and equal-budget baselines;
3. run pinned OpenAI and Claude models on the exact same evidence policy;
4. report provider invoices or API usage, latency, misses, false confirmations,
   and confidence intervals;
5. repeat on a larger held-out set from workflows not used to adjust labels or
   thresholds.

## Pilot completion update

On 2026-08-21, five additional real browser interactions were captured before
changing detector thresholds: invalid username, invalid password, rejected
readonly input, rejected letters in a number input, and a valid login. The
capture hashes are fixed in the replay builder.

The resulting development suite has 65 labels, 60 independent source
transitions, and eight real eligible failed actions. `profile_complete` is now
`true`.

| Metric | Signum | Equal-budget uniform |
| --- | ---: | ---: |
| Triggered labels | 65 / 65 | 22 / 65 |
| Trigger recall | 1.000 | 0.338 |
| 95% Wilson interval | 0.944–1.000 | 0.235–0.460 |
| Observations | 93 | 93 |
| Unmatched observations | 28 | 71 |
| Unmatched initial observations | 19 | 0 |
| Unmatched non-initial observations | 9 | 71 |

One Codex batch interpreted the five new action pairs in 17.17 seconds and
reported 20,396 input plus 696 output tokens. All four rejected actions were
`not_confirmed`; the successful login was `confirmed`. This is a provisional
AI-assisted check, not a human-blind accuracy score.

The generated suite was hash-locked with freeze id
`61b0fce16ea6964a4c44c19f0fa86ab9592978efab96665e51f470fe652d9baf`
and role `development`. It cannot satisfy the comparative claim gate. The
larger held-out requirements are defined in
[Comparative claim protocol](CLAIM_PROTOCOL.md).
