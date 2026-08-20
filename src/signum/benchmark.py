from __future__ import annotations

import argparse
import json
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

from .config import SamplerConfig
from .models import Candidate
from .selector import select_candidates, signature_distance
from .signals import analyze_candidates
from .synthetic import GroundTruthEvent, SyntheticCase, generate_suite
from .video import candidate_indices, probe_video


def event_recall(selected: list[Candidate], events: tuple[GroundTruthEvent, ...]) -> float:
    if not events:
        return 1.0
    captured = 0
    for event in events:
        if any(
            event.start - event.tolerance <= item.timestamp <= event.end + event.tolerance
            for item in selected
        ):
            captured += 1
    return captured / len(events)


def redundancy(selected: list[Candidate], threshold: float) -> float:
    if len(selected) < 2:
        return 0.0
    duplicate_count = 0
    for index, candidate in enumerate(selected):
        if any(
            signature_distance(candidate, prior) < threshold
            for prior in selected[:index]
        ):
            duplicate_count += 1
    return duplicate_count / len(selected)


def temporal_coverage(
    selected: list[Candidate], duration: float, budget: int
) -> float:
    if not selected or duration <= 0:
        return 0.0
    bins = min(budget, max(1, len(selected)))
    occupied = {
        min(bins - 1, int(item.timestamp / duration * bins)) for item in selected
    }
    return len(occupied) / bins


def _method_result(
    case: SyntheticCase,
    candidates: list[Candidate],
    config: SamplerConfig,
    selector_strategy: str,
    analysis_seconds: float,
    scheduled_candidates: int,
    coarse_scanned_frames: int,
    promoted_spikes: int,
) -> dict[str, Any]:
    method_config = replace(config, budget=case.budget, strategy=selector_strategy)
    started = time.perf_counter()
    selected = select_candidates(candidates, method_config)
    selection_seconds = time.perf_counter() - started
    return {
        "event_recall": event_recall(selected, case.events),
        "redundancy": redundancy(selected, config.duplicate_threshold),
        "temporal_coverage": temporal_coverage(selected, case.duration, case.budget),
        "selected_count": len(selected),
        "selected_timestamps": [item.timestamp for item in selected],
        "full_analysis_candidates": (
            0 if selector_strategy == "uniform" else scheduled_candidates
        ),
        "coarse_scanned_frames": (
            0 if selector_strategy == "uniform" else coarse_scanned_frames
        ),
        "promoted_spikes": (
            0 if selector_strategy == "uniform" else promoted_spikes
        ),
        "analysis_seconds": (
            0.0 if selector_strategy == "uniform" else analysis_seconds
        ),
        "selection_seconds": selection_seconds,
    }


def run_benchmark(output_dir: Path, config: SamplerConfig | None = None) -> dict[str, Any]:
    base_config = config or SamplerConfig(budget=6)
    base_config.validate()
    media_dir = output_dir / "media"
    cases_payload: list[dict[str, Any]] = []
    for case, video_path in generate_suite(media_dir):
        metadata = probe_video(video_path)
        indices = candidate_indices(metadata, base_config.candidate_hz)
        previous_config = replace(base_config, spike_guard=False)
        previous_started = time.perf_counter()
        previous_analysis = analyze_candidates(metadata, indices, previous_config)
        previous_seconds = time.perf_counter() - previous_started

        analysis_started = time.perf_counter()
        analysis = analyze_candidates(metadata, indices, base_config)
        analysis_seconds = time.perf_counter() - analysis_started

        methods = {
            "uniform": _method_result(
                case,
                previous_analysis.candidates,
                previous_config,
                "uniform",
                0.0,
                previous_analysis.scheduled_candidate_count,
                0,
                0,
            ),
            "score_only": _method_result(
                case,
                analysis.candidates,
                base_config,
                "score_only",
                analysis_seconds,
                analysis.scheduled_candidate_count,
                analysis.coarse_scanned_frames,
                analysis.promoted_spike_count,
            ),
            "hybrid_no_spike_guard": _method_result(
                case,
                previous_analysis.candidates,
                previous_config,
                "hybrid",
                previous_seconds,
                previous_analysis.scheduled_candidate_count,
                previous_analysis.coarse_scanned_frames,
                previous_analysis.promoted_spike_count,
            ),
            "hybrid": _method_result(
                case,
                analysis.candidates,
                base_config,
                "hybrid",
                analysis_seconds,
                analysis.scheduled_candidate_count,
                analysis.coarse_scanned_frames,
                analysis.promoted_spike_count,
            ),
        }
        cases_payload.append(
            {
                "case": case.to_dict(),
                "video": str(video_path.resolve()),
                "candidate_count": len(analysis.candidates),
                "methods": methods,
            }
        )

    aggregate: dict[str, dict[str, float]] = {}
    for strategy in (
        "uniform",
        "score_only",
        "hybrid_no_spike_guard",
        "hybrid",
    ):
        method_rows = [row["methods"][strategy] for row in cases_payload]
        aggregate[strategy] = {
            metric: sum(float(row[metric]) for row in method_rows) / len(method_rows)
            for metric in (
                "event_recall",
                "redundancy",
                "temporal_coverage",
                "full_analysis_candidates",
                "coarse_scanned_frames",
                "promoted_spikes",
                "analysis_seconds",
                "selection_seconds",
            )
        }

    payload = {
        "schema_version": 1,
        "config": base_config.to_dict(),
        "case_count": len(cases_payload),
        "aggregate_mean": aggregate,
        "cases": cases_payload,
        "notes": [
            "Synthetic fixtures validate mechanics, not semantic understanding.",
            "Uniform analysis time excludes metric instrumentation and is defined as zero because it inspects no pixels.",
            "Wall times from this small suite are indicative and should not be treated as stable throughput claims.",
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "benchmark.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m signum.benchmark")
    parser.add_argument("--output", type=Path, default=Path("benchmark-output"))
    parser.add_argument("--candidate-hz", type=float, default=4.0)
    parser.add_argument("--analysis-width", type=int, default=192)
    args = parser.parse_args(argv)
    config = SamplerConfig(
        budget=6,
        candidate_hz=args.candidate_hz,
        analysis_width=args.analysis_width,
    )
    result = run_benchmark(args.output, config)
    print(json.dumps(result["aggregate_mean"], indent=2, sort_keys=True))
    print(f"details: {(args.output / 'benchmark.json').resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
