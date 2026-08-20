from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .config import SamplerConfig
from .selector import select_candidates, signature_distance
from .signals import analyze_candidates
from .video import candidate_indices, extract_frames, probe_video


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _redundancy(selected: list, threshold: float) -> float:
    if len(selected) < 2:
        return 0.0
    redundant = 0
    seen = []
    for candidate in selected:
        if any(signature_distance(candidate, previous) < threshold for previous in seen):
            redundant += 1
        seen.append(candidate)
    return redundant / len(selected)


def analyze_video(
    source: Path | str, output_dir: Path | str, config: SamplerConfig
) -> dict[str, Any]:
    config.validate()
    started = time.perf_counter()
    metadata = probe_video(Path(source))
    indices = candidate_indices(metadata, config.candidate_hz)
    candidates = analyze_candidates(metadata, indices, config)
    selected = select_candidates(candidates, config)
    analysis_seconds = time.perf_counter() - started

    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    extract_started = time.perf_counter()
    frame_names = extract_frames(
        metadata, [item.frame_index for item in selected], output / "frames"
    )
    extraction_seconds = time.perf_counter() - extract_started

    observations = []
    for item in selected:
        serialized = item.to_dict()
        serialized["frame_file"] = f"frames/{frame_names[item.frame_index]}"
        observations.append(serialized)

    timeline = {
        "schema_version": 1,
        "source": metadata.to_dict(),
        "observations": observations,
    }
    scores = [item.importance for item in candidates]
    report = {
        "schema_version": 1,
        "source": metadata.to_dict(),
        "config": config.to_dict(),
        "counts": {
            "source_frames": metadata.frame_count,
            "analyzed_candidates": len(candidates),
            "selected_observations": len(selected),
        },
        "timing_seconds": {
            "analysis_and_selection": analysis_seconds,
            "frame_extraction": extraction_seconds,
            "total": time.perf_counter() - started,
        },
        "importance": {
            "minimum": min(scores, default=0.0),
            "maximum": max(scores, default=0.0),
            "mean": sum(scores) / len(scores) if scores else 0.0,
        },
        "selected_redundancy": _redundancy(selected, config.duplicate_threshold),
    }
    _write_json(output / "timeline.json", timeline)
    _write_json(output / "report.json", report)
    return {"timeline": timeline, "report": report}
