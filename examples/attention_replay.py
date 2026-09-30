"""Deterministic development fixture. No model calls, invoices or semantic claims.

Run: python examples/attention_replay.py --output attention-output.json
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from signum.attention import AttentionGateway, ObservationContract
from signum.gateway import GatewayConfig, PerceptionGateway, SemanticResult


def run():
    config = GatewayConfig(analysis_width=64, local_analysis_width=64,
        min_event_interval_seconds=0.0)
    old = PerceptionGateway(config)
    new = AttentionGateway(ObservationContract("watch the canvas", recheck_after_seconds=30),
                           gateway_config=config)
    # Pixels are constant for one second, then fade by one level per frame.
    frames = [np.zeros((64, 64, 3), np.uint8) for _ in range(20)]
    frames += [np.full((64, 64, 3), level, np.uint8) for level in range(1, 81)]
    old_times, new_times = [], []
    for index, frame in enumerate(frames):
        timestamp = index / 20
        event = old.observe_frame(frame, timestamp, goal="watch the canvas", frame_index=index)
        if event:
            old_times.append(event.event.timestamp)
        new.submit_frame(frame, timestamp, frame_index=index)
        for packet in new.poll_packets(16):
            new_times.append(packet.event.timestamp)
            # Mechanical acknowledgement only. This is NOT a real visual judge.
            new.acknowledge(packet.event.sequence, SemanticResult(
                "fixture", "synthetic acknowledgement", True, 1.0, "wait"))
    new.set_contract(ObservationContract("inspect the composition", version="composition"))
    internal = new.submit_frame(frames[-1], 5.0, frame_index=100)
    budget = len(new_times)
    duration = len(frames) / 20
    uniform_times = [(i + .5) * duration / budget for i in range(budget)]
    return {
        "classification": "development_only_not_held_out",
        "provider_calls": 0,
        "billed_cost": None,
        "semantic_accuracy": None,
        "frames": len(frames),
        "legacy_observation_times": old_times,
        "attention_observation_times": new_times,
        "equal_budget_uniform_observation_times": uniform_times,
        "internal_question_event": internal.event.reason,
        "limitations": [
            "Constructed slow-fade fixture, not natural video or art understanding.",
            "Uniform is given equal observation count, not equal CPU work.",
            "Additional drift detections may increase calls; no cost-saving claim.",
            "The acknowledgement is a deterministic stub, not semantic evidence."]}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("attention-output.json"))
    args = parser.parse_args()
    data = run()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(data, indent=2))
