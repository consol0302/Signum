from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import SamplerConfig
from .pipeline import analyze_video
from .video import VideoError


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="signum")
    subparsers = parser.add_subparsers(dest="command", required=True)
    analyze = subparsers.add_parser(
        "analyze", help="select representative, event-rich frames from a video"
    )
    analyze.add_argument("input", type=Path)
    analyze.add_argument("--budget", type=int, default=32)
    analyze.add_argument("--output", type=Path, default=Path("output"))
    analyze.add_argument("--candidate-hz", type=float, default=4.0)
    analyze.add_argument("--analysis-width", type=int, default=192)
    analyze.add_argument("--min-distance", type=float, default=0.5)
    analyze.add_argument("--coverage-fraction", type=float, default=0.25)
    analyze.add_argument(
        "--strategy", choices=("hybrid", "score_only", "uniform"), default="hybrid"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command != "analyze":
        return 2
    config = SamplerConfig(
        budget=args.budget,
        candidate_hz=args.candidate_hz,
        analysis_width=args.analysis_width,
        min_distance_seconds=args.min_distance,
        coverage_fraction=args.coverage_fraction,
        strategy=args.strategy,
    )
    try:
        result = analyze_video(args.input, args.output, config)
    except (ValueError, VideoError) as error:
        print(f"signum: error: {error}", file=sys.stderr)
        return 2
    summary = {
        "output": str(args.output.resolve()),
        "selected": result["report"]["counts"]["selected_observations"],
        "analyzed": result["report"]["counts"]["analyzed_candidates"],
        "total_seconds": result["report"]["timing_seconds"]["total"],
    }
    print(json.dumps(summary, sort_keys=True))
    return 0
