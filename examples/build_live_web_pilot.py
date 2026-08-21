from __future__ import annotations

import argparse
import json
from pathlib import Path

import cv2


FPS = 20.0
SECONDS_PER_STATE = 2.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Build a labeled replay from the three real Selenium page captures "
            "used by the live Codex probe."
        )
    )
    parser.add_argument(
        "--frames-dir",
        type=Path,
        required=True,
        help="directory containing initial.png, box-settled.png, and input-settled.png",
    )
    parser.add_argument("--output", type=Path, default=Path("live-web-pilot"))
    return parser.parse_args()


def read_frame(directory: Path, name: str):
    path = directory / name
    frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
    if frame is None:
        raise RuntimeError(f"could not read captured browser frame: {path}")
    return frame


def main() -> None:
    args = parse_args()
    initial = read_frame(args.frames_dir, "initial.png")
    box = read_frame(args.frames_dir, "box-settled.png")
    input_visible = read_frame(args.frames_dir, "input-settled.png")
    if initial.shape != box.shape or initial.shape != input_visible.shape:
        raise RuntimeError("captured browser frames must have identical dimensions")

    args.output.mkdir(parents=True, exist_ok=True)
    video_path = args.output / "selenium-dynamic-replay.avi"
    height, width = initial.shape[:2]
    writer = cv2.VideoWriter(
        str(video_path),
        cv2.VideoWriter_fourcc(*"MJPG"),
        FPS,
        (width, height),
    )
    if not writer.isOpened():
        raise RuntimeError(f"could not create replay video: {video_path}")
    frames_per_state = int(FPS * SECONDS_PER_STATE)
    try:
        for frame in (initial, box, input_visible):
            for _ in range(frames_per_state):
                writer.write(frame)
    finally:
        writer.release()

    manifest = {
        "schema_version": 2,
        "cases": [
            {
                "id": "selenium-dynamic-controls",
                "video": video_path.name,
                "goal": (
                    "Detect the red box and small input, then verify whether the "
                    "Reveal a new input action visibly succeeded."
                ),
                "events": [
                    {
                        "id": "red-box-visible",
                        "start": 1.95,
                        "end": 2.15,
                        "tolerance": 0.05,
                        "category": "popup_notification",
                        "risk": "low",
                        "acceptable_states": [
                            "red_box_visible",
                            "box_visible",
                        ],
                        "notes": "A 151 by 151 red box appears below the controls.",
                    },
                    {
                        "id": "small-input-visible",
                        "start": 3.95,
                        "end": 4.15,
                        "tolerance": 0.05,
                        "category": "small_ui",
                        "risk": "normal",
                        "acceptable_states": [
                            "input_visible",
                            "text_input_visible",
                        ],
                        "notes": "A 170 by 21 text input appears beside the buttons.",
                    },
                    {
                        "id": "reveal-input-confirmed",
                        "start": 4.0,
                        "end": 4.3,
                        "tolerance": 0.05,
                        "category": "action_success",
                        "risk": "normal",
                        "before_timestamp": 3.8,
                        "after_timestamp": 4.2,
                        "action": "clicked Reveal a new input",
                        "expected_result": (
                            "a new text input is visible beside the buttons"
                        ),
                        "acceptable_states": [
                            "input_visible",
                            "text_input_visible",
                        ],
                        "notes": "The before frame has no input and the after frame does.",
                    },
                    {
                        "id": "reveal-input-no-op",
                        "start": 3.15,
                        "end": 3.35,
                        "tolerance": 0.05,
                        "category": "action_failure",
                        "risk": "high",
                        "before_timestamp": 3.0,
                        "after_timestamp": 3.25,
                        "action": "clicked Reveal a new input",
                        "expected_result": (
                            "a new text input is visible beside the buttons"
                        ),
                        "acceptable_states": [
                            "input_absent",
                            "text_input_absent",
                        ],
                        "notes": (
                            "Both source frames show only the red box; claiming success "
                            "is a critical false confirmation."
                        ),
                    },
                ],
            }
        ],
        "provenance": {
            "source_url": "https://www.selenium.dev/selenium/web/dynamic.html",
            "capture_kind": "real_browser_screenshots_replayed_at_fixed_duration",
            "source_frames": [
                str((args.frames_dir / name).resolve())
                for name in (
                    "initial.png",
                    "box-settled.png",
                    "input-settled.png",
                )
            ],
            "limitations": [
                "The replay preserves captured pixels but not original transition timing.",
                "All four labels come from one simple public test page.",
            ],
        },
    }
    manifest_path = args.output / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "manifest": str(manifest_path.resolve()),
                "video": str(video_path.resolve()),
                "events": 4,
                "frames": frames_per_state * 3,
                "fps": FPS,
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
