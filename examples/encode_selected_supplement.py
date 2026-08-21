from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path


ENCODER_PATH = Path(__file__).with_name("encode_timestamped_capture.py")
SPEC = importlib.util.spec_from_file_location("encode_timestamped_capture", ENCODER_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {ENCODER_PATH}")
ENCODER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ENCODER)


def read_object(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return payload


def encode_selected(
    collection_root: Path,
    summary_path: Path,
    *,
    output_fps: float,
) -> list[dict]:
    summary = read_object(summary_path)
    if summary.get("claim180_supplement_complete") is not True:
        raise RuntimeError("supplement collection is not complete")
    selected = summary.get("selection", {}).get("selected_target_events")
    if not isinstance(selected, list) or len(selected) != 37:
        raise RuntimeError("supplement summary must select exactly 37 target events")
    case_ids = [row.get("case_id") for row in selected if isinstance(row, dict)]
    if len(case_ids) != 37 or len(case_ids) != len(set(case_ids)):
        raise RuntimeError("supplement selected case ids are invalid")
    reports = []
    for case_id in case_ids:
        capture_path = collection_root / case_id / "capture.json"
        output_path = collection_root / case_id / "capture.avi"
        report = ENCODER.encode_capture(
            capture_path,
            output_path,
            output_fps=output_fps,
            allow_invalid=False,
        )
        row = {
            "case_id": case_id,
            "output_frames": report["output_frame_count"],
            "source_frames": report["source_frame_count"],
            "maximum_source_age_seconds": report["maximum_source_age_seconds"],
            "video_bytes": report["video_bytes"],
            "video_sha256": report["video_sha256"],
        }
        reports.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)
    return reports


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Encode the 37 frozen supplement selections without changing source timing."
    )
    parser.add_argument("--collection-root", type=Path, required=True)
    parser.add_argument("--summary", type=Path, required=True)
    parser.add_argument("--fps", type=float, default=30.0)
    args = parser.parse_args()
    reports = encode_selected(
        args.collection_root.resolve(),
        args.summary.resolve(),
        output_fps=args.fps,
    )
    print(
        json.dumps(
            {
                "encoded": len(reports),
                "video_bytes": sum(row["video_bytes"] for row in reports),
                "maximum_source_age_seconds": max(
                    row["maximum_source_age_seconds"] for row in reports
                ),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
