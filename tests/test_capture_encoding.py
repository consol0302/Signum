from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
sys.path.insert(0, str(EXAMPLES))

from encode_timestamped_capture import (  # noqa: E402
    EncodingError,
    encode_capture,
    resample_mapping,
)
from verify_browser_capture import (  # noqa: E402
    capture_statistics,
    verify_capture,
)


class CaptureEncodingTests(unittest.TestCase):
    def test_mapping_uses_latest_source_frame_without_future_leakage(self) -> None:
        frames = [
            {"sequence": 0, "timestamp_seconds": 0.02, "file": "zero.png"},
            {"sequence": 1, "timestamp_seconds": 0.14, "file": "one.png"},
            {"sequence": 2, "timestamp_seconds": 0.23, "file": "two.png"},
        ]

        mapping = resample_mapping(frames, duration_seconds=0.3, output_fps=10)

        self.assertEqual([0, 0, 1], [row["source_sequence"] for row in mapping])
        self.assertTrue(all(row["source_age_seconds"] >= 0 for row in mapping))

    def test_encode_verifies_video_and_preserves_timing_map(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frames_dir = root / "frames"
            frames_dir.mkdir()
            frames = []
            for sequence, timestamp in enumerate((0.01, 0.11, 0.21)):
                name = f"frame_{sequence:06d}.png"
                image = np.full((48, 64, 3), sequence * 80, dtype=np.uint8)
                self.assertTrue(cv2.imwrite(str(frames_dir / name), image))
                frames.append(
                    {
                        "sequence": sequence,
                        "file": f"frames/{name}",
                        "timestamp_seconds": timestamp,
                    }
                )
            capture = root / "capture.json"
            capture.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "valid": True,
                        "capture_policy": {"duration_seconds": 0.3},
                        "frames": frames,
                    }
                ),
                encoding="utf-8",
            )

            report = encode_capture(
                capture,
                root / "capture.avi",
                output_fps=20,
            )

            self.assertEqual(6, report["output_frame_count"])
            self.assertEqual(3, report["used_source_frame_count"])
            self.assertEqual([], report["unused_source_sequences"])
            self.assertEqual(6, report["decoded_video"]["frame_count"])
            self.assertEqual(64, report["decoded_video"]["width"])
            self.assertTrue((root / "capture.encoding.json").is_file())

    def test_invalid_capture_requires_explicit_override(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            capture = root / "capture.json"
            capture.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "valid": False,
                        "capture_policy": {"duration_seconds": 1},
                        "frames": [
                            {
                                "sequence": 0,
                                "file": "missing.png",
                                "timestamp_seconds": 0,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(EncodingError, "marked invalid"):
                encode_capture(capture, root / "capture.avi", output_fps=10)

    def test_capture_verifier_recomputes_hash_dimensions_timing_and_actions(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            frames_dir = root / "frames"
            frames_dir.mkdir()
            frames = []
            for sequence, timestamp in enumerate((0.01, 0.09, 0.17)):
                name = f"frame_{sequence:06d}.png"
                path = frames_dir / name
                self.assertTrue(
                    cv2.imwrite(
                        str(path),
                        np.full((48, 64, 3), sequence * 70, dtype=np.uint8),
                    )
                )
                data = path.read_bytes()
                frames.append(
                    {
                        "sequence": sequence,
                        "file": f"frames/{name}",
                        "timestamp_seconds": timestamp,
                        "capture_duration_seconds": 0.01,
                        "encoded_bytes": len(data),
                        "sha256": hashlib.sha256(data).hexdigest(),
                    }
                )
            action_payload = {
                "schema_version": 1,
                "case_id": "verified-case",
                "target_events": [
                    {"action_id": "click", "category": "small_ui"}
                ],
                "actions": [
                    {"id": "click", "at_seconds": 0.05, "type": "click"}
                ],
            }
            action_path = root / "actions.json"
            action_path.write_text(json.dumps(action_payload), encoding="utf-8")
            action_data = action_path.read_bytes()
            stats = capture_statistics(frames)
            capture = root / "capture.json"
            capture.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "case_id": "verified-case",
                        "valid": True,
                        "invalid_reasons": [],
                        "viewport": {"width": 64, "height": 48},
                        "capture_policy": {
                            "minimum_average_fps": 10,
                            "maximum_gap_seconds": 0.25,
                            "duration_seconds": 0.25,
                        },
                        "frame_statistics": stats,
                        "frame_errors": [],
                        "action_spec": {
                            "path": "actions.json",
                            "bytes": len(action_data),
                            "sha256": hashlib.sha256(action_data).hexdigest(),
                        },
                        "actions": [
                            {
                                "id": "click",
                                "required": True,
                                "status": "completed",
                                "started_at_seconds": 0.04,
                                "completed_at_seconds": 0.05,
                            }
                        ],
                        "frames": frames,
                    }
                ),
                encoding="utf-8",
            )

            valid = verify_capture(capture, expected_case_id="verified-case")
            self.assertTrue(valid["valid"])
            target_check = next(
                row
                for row in valid["checks"]
                if row["kind"] == "target_event_frame_coverage"
            )
            self.assertTrue(target_check["valid"])

            uncovered_payload = json.loads(capture.read_text(encoding="utf-8"))
            uncovered_payload["actions"][0]["completed_at_seconds"] = 0.23
            capture.write_text(json.dumps(uncovered_payload), encoding="utf-8")
            uncovered = verify_capture(capture, expected_case_id="verified-case")
            self.assertFalse(uncovered["integrity_valid"])
            self.assertFalse(uncovered["valid"])
            uncovered_payload["actions"][0]["completed_at_seconds"] = 0.05
            capture.write_text(json.dumps(uncovered_payload), encoding="utf-8")

            (frames_dir / "frame_000001.png").write_bytes(b"changed")
            tampered = verify_capture(capture, expected_case_id="verified-case")
            self.assertFalse(tampered["integrity_valid"])
            self.assertFalse(tampered["valid"])


if __name__ == "__main__":
    unittest.main()
