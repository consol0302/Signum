from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import SamplerConfig
from .claims import assess_claim
from .evaluation import (
    EvaluationError,
    audit_manifest,
    run_evaluation,
    score_reviews,
)
from .freeze import (
    freeze_manifest,
    preregister_claim180_supplement,
    preregister_heldout,
    verify_freeze,
)
from .gateway import GatewayConfig
from .interpreters import CodexExecInterpreter, InterpreterError
from .observe import observe_video
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
        "--no-spike-guard",
        action="store_true",
        help="disable the per-frame low-resolution abrupt-change guard",
    )
    analyze.add_argument(
        "--strategy", choices=("hybrid", "score_only", "uniform"), default="hybrid"
    )
    observe = subparsers.add_parser(
        "observe",
        help="gate semantic screen observations for a computer-use workflow",
    )
    observe.add_argument("input", type=Path)
    observe.add_argument("--goal", required=True)
    observe.add_argument("--output", type=Path, default=Path("observe-output"))
    observe.add_argument(
        "--codex-command",
        default="codex",
        help="Codex CLI executable or absolute path (default: codex)",
    )
    observe.add_argument(
        "--model",
        help="optional Codex model override; defaults to the Codex runtime model",
    )
    observe.add_argument("--codex-timeout", type=float, default=120.0)
    observe.add_argument("--analysis-width", type=int, default=192)
    observe.add_argument("--local-analysis-width", type=int, default=768)
    observe.add_argument("--min-local-component-pixels", type=int, default=12)
    observe.add_argument("--min-change-fraction", type=float, default=0.002)
    observe.add_argument("--stable-frames", type=int, default=2)
    observe.add_argument("--min-event-interval", type=float, default=0.5)
    observe.add_argument("--max-active-seconds", type=float, default=5.0)
    evaluate = subparsers.add_parser(
        "evaluate",
        help="measure labeled screen-event recall against an equal-budget baseline",
    )
    evaluate.add_argument("manifest", type=Path)
    evaluate.add_argument("--output", type=Path, default=Path("evaluation-output"))
    evaluate.add_argument(
        "--with-codex",
        action="store_true",
        help="interpret both methods with Codex; this consumes subscription usage",
    )
    evaluate.add_argument("--codex-command", default="codex")
    evaluate.add_argument("--model")
    evaluate.add_argument("--codex-timeout", type=float, default=120.0)
    evaluate.add_argument("--analysis-width", type=int, default=192)
    evaluate.add_argument("--local-analysis-width", type=int, default=768)
    evaluate.add_argument("--min-local-component-pixels", type=int, default=12)
    evaluate.add_argument("--min-change-fraction", type=float, default=0.002)
    evaluate.add_argument("--stable-frames", type=int, default=2)
    evaluate.add_argument("--min-event-interval", type=float, default=0.5)
    evaluate.add_argument("--max-active-seconds", type=float, default=5.0)
    score = subparsers.add_parser(
        "score",
        help="compute human-reviewed perception success rates",
    )
    score.add_argument("evaluation", type=Path)
    score.add_argument("--reviews", type=Path, required=True)
    score.add_argument("--output", type=Path)
    audit = subparsers.add_parser(
        "audit-manifest",
        help="check labeled-suite coverage before running an evaluation",
    )
    audit.add_argument("manifest", type=Path)
    audit.add_argument(
        "--profile", choices=("pilot60", "claim180"), default="pilot60"
    )
    freeze = subparsers.add_parser(
        "freeze-manifest",
        help="hash-lock a labeled manifest and every referenced video before evaluation",
    )
    freeze.add_argument("manifest", type=Path)
    freeze.add_argument("--output", type=Path, required=True)
    freeze.add_argument("--role", choices=("development", "held_out"), required=True)
    freeze.add_argument(
        "--preregistration",
        type=Path,
        help="required preregistration lock for a held_out freeze",
    )
    freeze.add_argument(
        "--collection-summary",
        type=Path,
        help="candidate-pool collection summary used for objective case selection",
    )
    freeze.add_argument(
        "--collection-root",
        type=Path,
        help="root containing every retained candidate capture or failure artifact",
    )
    preregister = subparsers.add_parser(
        "preregister-heldout",
        help="hash-lock the claim180 collection plan before recording held-out data",
    )
    preregister.add_argument("plan", type=Path)
    preregister.add_argument("--output", type=Path, required=True)
    preregister_supplement = subparsers.add_parser(
        "preregister-claim180-supplement",
        help="hash-lock a deficit-only Claim 180 supplement before capture",
    )
    preregister_supplement.add_argument("plan", type=Path)
    preregister_supplement.add_argument("--output", type=Path, required=True)
    verify = subparsers.add_parser(
        "verify-freeze",
        help="verify that a frozen manifest and its videos have not changed",
    )
    verify.add_argument("freeze", type=Path)
    claim = subparsers.add_parser(
        "assess-claim",
        help="apply the frozen statistical and cost gate to a provider comparison",
    )
    claim.add_argument("comparison", type=Path)
    claim.add_argument("--output", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "observe":
        return _observe_command(args)
    if args.command == "evaluate":
        return _evaluate_command(args)
    if args.command == "score":
        return _score_command(args)
    if args.command == "audit-manifest":
        return _audit_manifest_command(args)
    if args.command == "freeze-manifest":
        return _freeze_manifest_command(args)
    if args.command == "preregister-heldout":
        return _preregister_heldout_command(args)
    if args.command == "preregister-claim180-supplement":
        return _preregister_claim180_supplement_command(args)
    if args.command == "verify-freeze":
        return _verify_freeze_command(args)
    if args.command == "assess-claim":
        return _assess_claim_command(args)
    return _analyze_command(args)


def _analyze_command(args: argparse.Namespace) -> int:
    config = SamplerConfig(
        budget=args.budget,
        candidate_hz=args.candidate_hz,
        analysis_width=args.analysis_width,
        min_distance_seconds=args.min_distance,
        coverage_fraction=args.coverage_fraction,
        spike_guard=not args.no_spike_guard,
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


def _observe_command(args: argparse.Namespace) -> int:
    config = _gateway_config(args)
    interpreter = CodexExecInterpreter(
        command=args.codex_command,
        model=args.model,
        timeout_seconds=args.codex_timeout,
    )
    try:
        result = observe_video(
            args.input,
            args.output,
            goal=args.goal,
            config=config,
            interpreter=interpreter,
        )
    except (ValueError, VideoError, InterpreterError) as error:
        print(f"signum: error: {error}", file=sys.stderr)
        return 2
    summary = {
        "output": str(args.output.resolve()),
        "frames_seen": result["stats"]["frames_seen"],
        "perception_events": result["stats"]["events_emitted"],
        "ai_calls": result["stats"]["ai_calls"],
        "transmitted_image_bytes": result["stats"]["transmitted_image_bytes"],
        "transmitted_image_patches_32px": result["stats"][
            "transmitted_image_patches_32px"
        ],
        "reported_total_tokens": result["stats"]["reported_total_tokens"],
        "reported_usage_complete": result["stats"]["reported_usage_complete"],
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


def _gateway_config(args: argparse.Namespace) -> GatewayConfig:
    return GatewayConfig(
        analysis_width=args.analysis_width,
        local_analysis_width=args.local_analysis_width,
        min_local_component_pixels=args.min_local_component_pixels,
        min_changed_fraction=args.min_change_fraction,
        stable_frames=args.stable_frames,
        min_event_interval_seconds=args.min_event_interval,
        max_active_seconds=args.max_active_seconds,
    )


def _evaluate_command(args: argparse.Namespace) -> int:
    interpreter = None
    if args.with_codex:
        interpreter = CodexExecInterpreter(
            command=args.codex_command,
            model=args.model,
            timeout_seconds=args.codex_timeout,
        )
    try:
        result = run_evaluation(
            args.manifest,
            args.output,
            config=_gateway_config(args),
            interpreter=interpreter,
        )
    except (EvaluationError, VideoError, InterpreterError) as error:
        print(f"signum: error: {error}", file=sys.stderr)
        return 2
    summary = {
        "output": str(args.output.resolve()),
        "semantic_attempted": result["semantic_attempted"],
        "signum_trigger_recall": result["aggregate"]["signum"]["trigger_recall"],
        "uniform_trigger_recall": result["aggregate"]["uniform"]["trigger_recall"],
        "review_template": str((args.output / "review-template.json").resolve()),
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


def _score_command(args: argparse.Namespace) -> int:
    try:
        result = score_reviews(
            args.evaluation,
            args.reviews,
            args.output,
        )
    except EvaluationError as error:
        print(f"signum: error: {error}", file=sys.stderr)
        return 2
    destination = args.output or args.evaluation.parent / "score.json"
    summary = {
        "output": str(destination.resolve()),
        "complete": result["complete"],
        "signum_end_to_end_success_rate": result["methods"]["signum"][
            "end_to_end_success_rate"
        ],
        "uniform_end_to_end_success_rate": result["methods"]["uniform"][
            "end_to_end_success_rate"
        ],
    }
    print(json.dumps(summary, sort_keys=True))
    return 0


def _audit_manifest_command(args: argparse.Namespace) -> int:
    try:
        result = audit_manifest(args.manifest, profile=args.profile)
    except EvaluationError as error:
        print(f"signum: error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


def _freeze_manifest_command(args: argparse.Namespace) -> int:
    try:
        result = freeze_manifest(
            args.manifest,
            args.output,
            role=args.role,
            preregistration_path=args.preregistration,
            collection_summary_path=args.collection_summary,
            collection_root_path=args.collection_root,
        )
    except EvaluationError as error:
        print(f"signum: error: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "freeze_id": result["freeze_id"],
                "role": result["role"],
                "profile_complete": result["audit"]["profile_complete"],
            },
            sort_keys=True,
        )
    )
    return 0


def _preregister_heldout_command(args: argparse.Namespace) -> int:
    try:
        result = preregister_heldout(args.plan, args.output)
    except EvaluationError as error:
        print(f"signum: error: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "preregistration_id": result["preregistration_id"],
                "planned_cases": len(result["case_ids"]),
            },
            sort_keys=True,
        )
    )
    return 0


def _preregister_claim180_supplement_command(args: argparse.Namespace) -> int:
    try:
        result = preregister_claim180_supplement(args.plan, args.output)
    except EvaluationError as error:
        print(f"signum: error: {error}", file=sys.stderr)
        return 2
    print(
        json.dumps(
            {
                "output": str(args.output.resolve()),
                "preregistration_id": result["preregistration_id"],
                "planned_candidates": len(result["case_ids"]),
                "category_targets": result["category_targets"],
            },
            sort_keys=True,
        )
    )
    return 0


def _verify_freeze_command(args: argparse.Namespace) -> int:
    try:
        result = verify_freeze(args.freeze)
    except EvaluationError as error:
        print(f"signum: error: {error}", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0 if result["valid"] else 1


def _assess_claim_command(args: argparse.Namespace) -> int:
    try:
        result = assess_claim(args.comparison)
    except EvaluationError as error:
        print(f"signum: error: {error}", file=sys.stderr)
        return 2
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    print(
        json.dumps(
            {
                "claim_supported": result["claim_supported"],
                "claimable_baselines": result["claimable_baselines"],
                "output": str(args.output.resolve()) if args.output else None,
            },
            sort_keys=True,
        )
    )
    return 0 if result["claim_supported"] else 1
