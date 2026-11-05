from __future__ import annotations

import html
import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from .config import SamplerConfig
from .models import Candidate, VideoMetadata
from .pipeline import analyze_video
from .video import extract_frames, probe_video


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _export_uniform(
    metadata: VideoMetadata, count: int, output: Path
) -> dict[str, Any]:
    """Choose source-frame indices without inspecting pixels or Signum scores."""
    started = time.perf_counter()
    indices = [
        int(round(value))
        for value in np.linspace(0, metadata.frame_count - 1, count)
    ]
    selection_seconds = time.perf_counter() - started
    extraction_started = time.perf_counter()
    names = extract_frames(metadata, indices, output / "frames")
    extraction_seconds = time.perf_counter() - extraction_started
    observations = []
    half_frame = 0.5 / metadata.fps
    for index in indices:
        timestamp = index / metadata.fps
        observation = Candidate(
            frame_index=index,
            timestamp=timestamp,
            source_start=max(0.0, timestamp - half_frame),
            source_end=min(metadata.duration_seconds, timestamp + half_frame),
            discovery="uniform",
        ).to_dict()
        observation["frame_file"] = f"frames/{names[index]}"
        observations.append(observation)
    timeline = {
        "schema_version": 1,
        "source": metadata.to_dict(),
        "observations": observations,
    }
    report = {
        "schema_version": 1,
        "source": metadata.to_dict(),
        "config": {"strategy": "uniform_source_frames", "budget": count},
        "counts": {
            "source_frames": metadata.frame_count,
            "analyzed_candidates": 0,
            "coarse_scanned_frames": 0,
            "selected_observations": len(observations),
        },
        "timing_seconds": {
            "selection": selection_seconds,
            "frame_extraction": extraction_seconds,
            "total": time.perf_counter() - started,
        },
    }
    _write_json(output / "timeline.json", timeline)
    _write_json(output / "report.json", report)
    return {"timeline": timeline, "report": report}


def _method_html(name: str, label: str, result: dict[str, Any]) -> str:
    cards = []
    for observation in result["timeline"]["observations"]:
        timestamp = float(observation["timestamp"])
        index = int(observation["frame_index"])
        image_path = html.escape(f"{name}/{observation['frame_file']}", quote=True)
        cards.append(
            '<li><figure>'
            f'<a href="{image_path}"><img src="{image_path}" '
            f'alt="Source frame {index} at {timestamp:.3f} seconds" '
            'loading="lazy"></a>'
            f'<figcaption><strong>{timestamp:.3f}s</strong>'
            f'<span>Frame {index}</span></figcaption></figure></li>'
        )
    return (
        f'<section class="method"><h2>{label}</h2>'
        f'<p>{len(cards)} observations &middot; '
        f'<a href="{name}/timeline.json">Timeline JSON</a> &middot; '
        f'<a href="{name}/report.json">Export report</a></p>'
        f'<ol class="frames">{"".join(cards)}</ol></section>'
    )


def _render_report(
    comparison: dict[str, Any], signum: dict[str, Any], uniform: dict[str, Any]
) -> str:
    source = comparison["source"]
    filename = html.escape(Path(str(source["path"])).name)
    requested = comparison["requested_budget"]
    effective = comparison["effective_budget"]
    duration = float(source["duration_seconds"])
    source_frames = int(source["frame_count"])
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Signum comparison &mdash; {filename}</title>
<style>
:root {{ color-scheme: light; font-family: system-ui, sans-serif; color: #182a30; background: #f1f5f3; }}
* {{ box-sizing: border-box; }}
body {{ margin: 0; }}
main {{ max-width: 1400px; margin: auto; padding: 32px; }}
.eyebrow {{ color: #28654d; font-size: .8rem; font-weight: 700; letter-spacing: .14em; text-transform: uppercase; }}
h1 {{ font-size: clamp(1.8rem, 4vw, 2.8rem); line-height: 1.12; margin: 12px 0; }}
h2 {{ margin: 0 0 8px; font-size: 1.3rem; }}
p {{ line-height: 1.6; }}
a {{ color: #175b46; text-underline-offset: .18em; overflow-wrap: anywhere; }}
.source {{ overflow-wrap: anywhere; }}
.summary {{ display: flex; flex-wrap: wrap; gap: 12px; margin: 24px 0; }}
.stat {{ background: white; border: 1px solid #d5e1da; border-radius: 12px; padding: 16px 24px; flex: 1; min-width: 150px; }}
.stat strong {{ display: block; font-size: 1.6rem; }}
.notice {{ border-left: 4px solid #ae761d; background: #fff7e8; padding: 12px 18px; margin: 24px 0; }}
.methods {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 24px; align-items: start; }}
.method {{ min-width: 0; background: white; border: 1px solid #d5e1da; border-radius: 16px; padding: 20px; }}
.method > p {{ font-size: .85rem; }}
.frames {{ list-style: none; padding: 0; margin: 20px 0 0; display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }}
figure {{ margin: 0; background: #f1f5f3; border-radius: 8px; overflow: hidden; }}
img {{ width: 100%; height: auto; display: block; background: #182a30; }}
figcaption {{ padding: 10px; font-size: .8rem; }}
figcaption strong, figcaption span {{ display: block; }}
figcaption span {{ color: #52666b; margin-top: 3px; }}
footer {{ color: #52666b; font-size: .85rem; margin-top: 24px; }}
@media (max-width: 850px) {{ .methods {{ grid-template-columns: 1fr; }} }}
@media (max-width: 480px) {{ main {{ padding: 16px; }} .frames {{ grid-template-columns: repeat(2, minmax(0, 1fr)); }} .method {{ padding: 16px; }} }}
</style>
</head>
<body><main>
<div class="eyebrow">Signum Perception / Visual comparison</div>
<h1>Same video. Same frame count.</h1>
<p class="source">{filename} &middot; {duration:.3f}s &middot; {source_frames} source frames</p>
<div class="summary">
<div class="stat"><strong>{requested}</strong>Requested frame budget</div>
<div class="stat"><strong>{effective}</strong>Frames exported per method</div>
<div class="stat"><strong>0</strong>AI calls</div>
</div>
<div class="notice"><strong>Inspect what each method preserves and misses.</strong>
This report has no event labels and measures neither semantic accuracy nor model token use or billing.
If fewer Signum candidates are available than requested, both methods use the smaller count.</div>
<div class="methods">
{_method_html("signum", "Signum hybrid selection", signum)}
{_method_html("uniform", "Uniform source-frame sampling", uniform)}
</div>
<footer>
<p>Frames are in source order. Click a frame to inspect the exported image.
Uniform indices depend only on source length and count, never on Signum scores or promoted events.
Both exports decode the source; processing times in the JSON reports are single-run diagnostics.</p>
<p><a href="comparison.json">Comparison JSON</a></p>
</footer>
</main></body></html>
"""


def compare_video(
    source: Path | str, output_dir: Path | str, config: SamplerConfig
) -> dict[str, Any]:
    """Export an offline visual comparison without inferring accuracy or savings."""
    config.validate()
    if config.strategy != "hybrid":
        raise ValueError("comparison requires the hybrid Signum strategy")
    metadata = probe_video(Path(source))
    output = Path(output_dir)
    signum = analyze_video(source, output / "signum", config)
    count = len(signum["timeline"]["observations"])
    uniform = _export_uniform(metadata, count, output / "uniform")
    comparison = {
        "schema_version": 1,
        "source": metadata.to_dict(),
        "requested_budget": config.budget,
        "effective_budget": count,
        "equal_observation_count": count == len(uniform["timeline"]["observations"]),
        "methods": {
            "signum": {
                "strategy": "hybrid",
                "selected_observations": count,
                "timeline_file": "signum/timeline.json",
                "report_file": "signum/report.json",
            },
            "uniform": {
                "strategy": "uniform_source_frames",
                "selected_observations": len(uniform["timeline"]["observations"]),
                "timeline_file": "uniform/timeline.json",
                "report_file": "uniform/report.json",
            },
        },
        "unmeasured": ["event_recall", "semantic_accuracy", "model_tokens", "billing_cost"],
    }
    _write_json(output / "comparison.json", comparison)
    (output / "index.html").write_text(
        _render_report(comparison, signum, uniform), encoding="utf-8"
    )
    return comparison
