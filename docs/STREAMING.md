# Streaming perception runtime

`StreamingPerceptionGateway` accepts caller-provided BGR frames while the screen is changing. Deterministic detection runs during `submit_frame`; semantic interpretation runs on a single background worker so a slow Codex turn does not stop the next frame from being inspected.

Signum does not capture the desktop or execute actions. Petasos should own those responsibilities and pass source timestamps and frame indices into the gateway.

## Basic integration

```python
from signum.gateway import GatewayConfig
from signum.interpreters import CodexExecInterpreter
from signum.streaming import StreamingConfig, StreamingPerceptionGateway

gateway = StreamingPerceptionGateway(
    goal="Complete the form and verify submission",
    interpreter=CodexExecInterpreter(model="MODEL_NAME"),
    gateway_config=GatewayConfig(),
    streaming_config=StreamingConfig(
        ring_buffer_frames=8,
        max_pending_events=16,
        max_interpreter_retries=1,
    ),
)

try:
    for frame_index, frame, timestamp in petasos_frames():
        event = gateway.submit_frame(
            frame,
            timestamp,
            frame_index=frame_index,
        )
        for result in gateway.poll_results():
            petasos.handle_perception(result.to_dict())
finally:
    gateway.close(wait=True, timeout=120)
```

`submit_frame` returns as soon as CPU detection and JPEG preparation are complete. It does not wait for Codex. Results retain their event sequence and can arrive later through `poll_results`.

## Requested detail

Petasos can request a normalized region from the latest retained full-resolution frame:

```python
gateway.request_detail(
    x=0.72,
    y=0.78,
    width=0.25,
    height=0.16,
    goal="Read the small completion message",
)
```

The request bypasses passive change thresholds and prepares a context image plus a higher-resolution crop when the region is small enough.

## Action verification

After a click or key action, submit explicit before and after frames:

```python
gateway.verify_after_action(
    before_frame,
    after_frame,
    timestamp,
    action="clicked Submit",
    expected_result="a submission confirmation is visible",
)
```

This emits even when no pixels changed. Visible non-change is evidence that the action may have failed.

## Retries and overload

Interpreter failures are retried in place so later events cannot overtake an earlier event's semantic context. If the bounded semantic queue is full, frame detection continues, the event is retained, and a failed `StreamingResult` explicitly reports the dropped interpretation. Petasos may requeue it:

```python
accepted = gateway.retry_event(sequence)
```

Monitor `stats_dict()` for queue depth, dropped events, attempts, failures, retained frames, and detector time. The default ring holds eight full-resolution frames to bound memory; event JPEGs are retained separately for explicit retries.

## What “real-time” means here

The gateway keeps inspecting incoming frames while Codex is busy. It does not guarantee that semantic results finish before the next action. Petasos must decide whether a particular action requires waiting for verification. End-to-end latency still depends on capture rate, CPU detection, queue depth, Codex startup, model latency, and subscription throttling.
