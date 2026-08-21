from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2

from signum.gateway import GatewayConfig
from signum.interpreters import CodexExecInterpreter, CodexSessionInterpreter
from signum.streaming import StreamingConfig, StreamingPerceptionGateway


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay three captured web states through the live Codex gateway."
    )
    parser.add_argument(
        "--frames-dir",
        type=Path,
        required=True,
        help="directory containing initial.png, box-settled.png, and input-settled.png",
    )
    parser.add_argument("--output", type=Path, default=Path("live-web-output"))
    parser.add_argument("--codex-command", default="codex")
    parser.add_argument("--model", required=True)
    parser.add_argument("--codex-timeout", type=float, default=180.0)
    parser.add_argument(
        "--transport",
        choices=("ephemeral", "session"),
        default="ephemeral",
        help="start one isolated Codex turn per event or resume one read-only session",
    )
    return parser.parse_args()


def read_frame(directory: Path, name: str):
    path = directory / name
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError(f"could not read captured frame: {path}")
    return frame


def main() -> None:
    args = parse_args()
    initial = read_frame(args.frames_dir, "initial.png")
    box = read_frame(args.frames_dir, "box-settled.png")
    input_visible = read_frame(args.frames_dir, "input-settled.png")
    if initial.shape != box.shape or initial.shape != input_visible.shape:
        raise RuntimeError("captured frames must have the same dimensions")

    interpreter_type = (
        CodexSessionInterpreter
        if args.transport == "session"
        else CodexExecInterpreter
    )
    interpreter = interpreter_type(
        command=args.codex_command,
        model=args.model,
        timeout_seconds=args.codex_timeout,
    )
    gateway = StreamingPerceptionGateway(
        goal=(
            "Observe the dynamic web page. Identify when a red box appears, when a "
            "new text input appears beside the buttons, and verify visible results."
        ),
        interpreter=interpreter,
        gateway_config=GatewayConfig(
            stable_frames=1,
            min_event_interval_seconds=0.0,
        ),
        streaming_config=StreamingConfig(max_interpreter_retries=0),
    )
    submit_seconds: list[float] = []
    started = time.perf_counter()
    try:
        for frame_index, (frame, timestamp) in enumerate(
            (
                (initial, 0.0),
                (box, 0.1),
                (box, 0.2),
                (input_visible, 0.3),
                (input_visible, 0.4),
            )
        ):
            submit_started = time.perf_counter()
            gateway.submit_frame(frame, timestamp, frame_index=frame_index)
            submit_seconds.append(time.perf_counter() - submit_started)

        gateway.request_detail(
            x=0.17,
            y=0.0,
            width=0.15,
            height=0.08,
            goal="Inspect whether the newly revealed text input is visible.",
        )
        gateway.verify_after_action(
            box,
            input_visible,
            0.5,
            frame_index=5,
            action="clicked Reveal a new input",
            expected_result="a new text input is visible beside the buttons",
        )

        wait_seconds = args.codex_timeout * 5 + 30.0
        became_idle = gateway.wait_until_idle(wait_seconds)
        results = gateway.poll_results()
        wall_seconds = time.perf_counter() - started
        stats = gateway.stats_dict()
    finally:
        gateway.close(wait=True, timeout=args.codex_timeout + 5.0)

    args.output.mkdir(parents=True, exist_ok=True)
    event_dir = args.output / "events"
    event_dir.mkdir(exist_ok=True)
    saved_images: list[str] = []
    for result in results:
        for image in result.event.images:
            destination = (
                event_dir
                / f"event-{result.event.sequence:03d}-{image.role}.jpg"
            )
            destination.write_bytes(image.jpeg)
            saved_images.append(destination.relative_to(args.output).as_posix())

    report = {
        "schema_version": 1,
        "source": {
            "frames_dir": str(args.frames_dir.resolve()),
            "frame_size": [int(initial.shape[1]), int(initial.shape[0])],
        },
        "codex": interpreter.metadata(),
        "measurement": {
            "became_idle": became_idle,
            "wall_seconds": wall_seconds,
            "submit_seconds": submit_seconds,
            "maximum_submit_seconds": max(submit_seconds),
            "stats": stats,
        },
        "results": [result.to_dict() for result in results],
        "saved_images": saved_images,
    }
    report_path = args.output / "measurement.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if isinstance(interpreter, CodexSessionInterpreter):
        interpreter.close()
    summary = {
        "output": str(report_path.resolve()),
        "calls": len(results),
        "succeeded": sum(result.succeeded for result in results),
        "wall_seconds": wall_seconds,
        "reported_total_tokens": sum(
            result.interpretation.reported_total_tokens
            for result in results
            if result.interpretation is not None
            and result.interpretation.reported_total_tokens is not None
        ),
    }
    print(json.dumps(summary, sort_keys=True))
    if not became_idle or any(not result.succeeded for result in results):
        raise SystemExit(2)


if __name__ == "__main__":
    main()
