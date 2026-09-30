# Experimental attention contracts

This is an opt-in, evidence-only streaming path. It does not replace the legacy
sampler, change its thresholds, run a model, capture a desktop or execute an
action. Import `signum.attention.AttentionGateway` explicitly.

## What the hypothesis is

Cheap visual monitoring can continue while expensive semantic interpretation is
suspended. Reinterpret when evidence changes, a new action/question invalidates
the old context, the controller requests detail, or a freshness deadline expires.
An unchanged canvas does not imply that a new question needs no observation.
This is an engineering hypothesis, not a model of the human brain or a claim of
human-level art understanding.

## Implemented boundaries

- Keep the legacy adjacent-frame detector; add a cumulative scene anchor and an
  acknowledged-evidence anchor. Enqueue and delivery never acknowledge a belief.
- Optional normalized watch regions are analyzed at their own scale. Global
  detection stays enabled. An RGB difference guard preserves equal-luminance
  color changes which a grayscale-only detector can miss.
- Source event IDs address original-resolution current/peak/before frames.
  Originals have byte and age limits. Missing evidence raises
  `EvidenceUnavailable`; it never returns the latest frame as a substitute.
- Context epochs, action IDs, visual revisions, timeouts and source timestamps
  block stale/out-of-order results from overwriting current belief. Historical
  detail results remain historical even if they happen to look like the screen.
- Packets can be delivered directly to an existing agent. There is no second
  semantic model in this path. The agent may attach an `ObservationContract` to
  its already-required response rather than making another planning call.
- Priority/deadline ordering and bounded batches retain distinct event IDs.
  Queue overflow, missing originals, eviction and late results are visible.
- Optional repeat approval suppresses ONLY exact full-frame patterns already
  reviewed as the same passive state. This is a controller assertion, not
  automatic semantic equivalence. New pixels, goals, actions, age or frame-count
  limits cancel it. No unreviewed intermediate event is merged away.
- An optional externally calibrated image-cost function compares native-resolution
  evidence crops plus context against native-resolution full images. It does not
  infer billed tokens or guarantee that one layout is semantically sufficient.

## Minimal controller loop

```python
from signum.attention import AttentionGateway, ObservationContract, WatchRegion

attention = AttentionGateway(ObservationContract(
    goal="Wait for export to finish and check for errors",
    version="export-1",
    watch_regions=(WatchRegion(0.65, 0.65, 0.35, 0.35),),
    recheck_after_seconds=15.0,
))

for frame_index, frame, timestamp in controller_frames():
    attention.submit_frame(frame, timestamp, frame_index=frame_index)
    for packet in attention.poll_packets(max_items=1):
        # Existing agent/model; send packet.event.images AND source metadata.
        # Use packet.goal/action/context, not a newer goal for historical packets.
        answer = existing_agent_interpret(packet)
        acknowledgement = attention.acknowledge(packet.event.sequence, answer)
        if acknowledgement.accepted_as_current:
            controller_use(answer)
    controller_record(attention.poll_notices())
```

`controller_frames`, `existing_agent_interpret`, `controller_use`, and
`controller_record` are integration points, not library functions. The answer is
an existing `SemanticResult`. Its confidence is not used as proof of correctness.
A fresh result may still be semantically wrong. Visible non-change never confirms
that an action succeeded.

Call `tick(now)` from the controller when no frames arrive. Use the SAME monotonic
source timeline for frames and tick; advance it before accepting a delayed result.
A true return requests a fresh capture. Tick does not capture, wake a hidden
worker or relabel an old screenshot with a new time. For an offline replay,
advance source time, not wall time. `request_current()` reuses the latest source
with its original timestamp; old evidence can therefore fail freshness checks.
Call `flush()` at end-of-stream to retain unfinished transitions.

## Internal events and static artwork

```python
attention.set_contract(ObservationContract(
    goal="Inspect the lighting and shadow direction",
    version="lighting-question",
    watch_regions=(WatchRegion(0.1, 0.1, 0.5, 0.5),),
))
# The next frame emits even if every pixel is identical.

# Revisit an exact earlier event, not the latest screen:
packet = attention.request_detail(event_id, WatchRegion(.1, .2, .3, .4), role="peak")
```

An agent can request current reconsideration for uncertainty, a new question,
conflicting evidence or a new inspection plan. Automatic detection of semantic
uncertainty is NOT implemented here; the controller supplies that event. A
painting can remain static while the viewer changes from naming objects to
examining composition, color or brushwork. The original must remain available
for such internal reinspection. External-change-only sleep would miss this.

## Repeat and budget rules

`approve_repeat((event_a, event_b), valid_for_seconds=5)` requires completed,
passive observations in the same context with the same reviewed state. Two to
eight distinct exact source images may be approved. Default suppression is
limited to 300 submitted frames and expires at the earlier of approval expiry
and the normal recheck deadline. General animation recognition is not included.
The full-frame hashes are conservative and have CPU/memory-bandwidth cost.

`poll_packets(max_items=4, max_image_bytes=...)` is a bounded transport batch, not
an instruction to drop event history. An oversized first packet is delivered
alone with a notice. If an external agent uses a single model call for a batch,
record usage ONCE in the controller's call ledger. Do not copy that call's total
into every event result. Per-event usage can remain missing. Local counters then
explicitly remain incomplete; they cannot establish a billed-cost claim.

`retry_event(id)` returns a new packet ID with the exact old images and original
context. A late response to the failed attempt cannot acknowledge the retry.
Use the packet's `source_event_id` when requesting original detail after retry.

## Memory and correctness limitations

Evidence and event history have independent byte limits. Additional bounded
working memory includes the latest input frame, the legacy detector's pending
peak and a small number of analysis signatures. `max_frame_bytes` bounds the
input size; the evidence limit alone is NOT the process's total memory bound.
History eviction can fail an in-flight event, and the caller must consume notices.

Diff thresholds, reduced-resolution signatures and JPEGs are lossy. Subthreshold
changes, capture gaps and high-frequency transients can still be missed. A fresh
belief means current under this observation policy, not a guarantee of truth.
Small chromatic changes require color-specific evaluation. Camera motion and
natural-video tracking are not solved by these UI-focused checks.

## Validation and promotion

Run the unchanged suite and synthetic sampler benchmark, then attention fixtures:

```bash
python -m unittest discover -s tests -v
python -m signum.benchmark --output benchmark-output
python examples/attention_replay.py --output attention-output.json
```

These fixtures check invariants, not semantic or real-world accuracy. The existing
V4 data, frozen manifests and benchmark archive remain untouched. Additions used
to tune attention are development data. Before promotion compare legacy Signum,
equal-budget uniform, and a simple action-aftercheck + diff + heartbeat baseline
under the same model/task/capture conditions. Evaluate task completion, false
confirmations, evidence legibility, p95 event-to-decision delay, actual call-level
usage/invoices, failed attempts and capture/CPU cost. A larger event count is not
by itself an improvement. No provider comparisons are run by this patch.
