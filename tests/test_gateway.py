from __future__ import annotations

import unittest
import tempfile
from pathlib import Path

import cv2
import numpy as np

from signum.gateway import (
    GatewayConfig,
    PerceptionEvent,
    PerceptionGateway,
    SemanticResult,
)
from signum.observe import observe_video
from signum.synthetic import generate_suite


class GatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.black = np.zeros((64, 64, 3), dtype=np.uint8)
        self.white = np.full((64, 64, 3), 255, dtype=np.uint8)
        self.config = GatewayConfig(
            analysis_width=64,
            pixel_threshold=10,
            min_changed_fraction=0.1,
            stable_frames=1,
            min_event_interval_seconds=0.0,
            jpeg_quality=100,
        )

    def test_transient_peak_is_preserved_for_semantic_interpretation(self) -> None:
        gateway = PerceptionGateway(self.config)
        gateway.observe_frame(self.black, 0.0, goal="notice a flash", frame_index=0)
        self.assertIsNone(
            gateway.observe_frame(
                self.white, 0.1, goal="notice a flash", frame_index=1
            )
        )
        self.assertIsNone(
            gateway.observe_frame(
                self.black, 0.2, goal="notice a flash", frame_index=2
            )
        )
        observation = gateway.observe_frame(
            self.black, 0.3, goal="notice a flash", frame_index=3
        )

        self.assertIsNotNone(observation)
        assert observation is not None
        self.assertEqual(0.1, observation.event.peak_timestamp)
        self.assertEqual(1, observation.event.peak_frame_index)
        peak = next(
            image for image in observation.event.images if image.role == "change_peak"
        )
        decoded = cv2.imdecode(np.frombuffer(peak.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
        self.assertGreater(float(np.mean(decoded)), 240.0)
        self.assertEqual(0, gateway.stats.transmitted_image_bytes)
        self.assertGreater(gateway.stats.prepared_image_bytes, 0)

    def test_flush_emits_change_at_stream_end(self) -> None:
        gateway = PerceptionGateway(self.config)
        gateway.observe_frame(self.black, 0.0, goal="observe", frame_index=0)
        gateway.observe_frame(self.white, 0.1, goal="observe", frame_index=1)

        observation = gateway.flush(
            self.white, 0.1, goal="observe", frame_index=1
        )

        self.assertIsNotNone(observation)
        assert observation is not None
        self.assertEqual("stream_end", observation.event.reason)
        self.assertIsNone(
            gateway.flush(self.white, 0.1, goal="observe", frame_index=1)
        )

    def test_small_local_ui_change_is_detected(self) -> None:
        baseline = np.zeros((1080, 1920, 3), dtype=np.uint8)
        changed = baseline.copy()
        changed[500:512, 900:912] = 255
        gateway = PerceptionGateway(
            GatewayConfig(
                analysis_width=192,
                local_analysis_width=768,
                min_local_component_pixels=12,
                stable_frames=1,
                min_event_interval_seconds=0.0,
            )
        )
        gateway.observe_frame(baseline, 0.0, goal="notice UI state", frame_index=0)

        self.assertIsNone(
            gateway.observe_frame(
                changed, 0.1, goal="notice UI state", frame_index=1
            )
        )
        observation = gateway.observe_frame(
            changed, 0.2, goal="notice UI state", frame_index=2
        )

        self.assertIsNotNone(observation)
        assert observation is not None
        self.assertEqual("local_component", observation.event.discovery)
        self.assertIsNotNone(observation.event.region)
        assert observation.event.region is not None
        self.assertLess(observation.event.region.area_ratio, 0.001)

    def test_action_verification_emits_even_when_screen_does_not_change(self) -> None:
        gateway = PerceptionGateway(self.config)
        gateway.observe_frame(self.black, 0.0, goal="save the file", frame_index=0)

        observation = gateway.verify_after_action(
            self.black,
            self.black,
            0.1,
            goal="save the file",
            action="clicked Save",
            expected_result="a saved confirmation is visible",
            frame_index=1,
        )

        self.assertEqual("action_verification", observation.event.reason)
        self.assertEqual("forced", observation.event.discovery)
        self.assertEqual("clicked Save", observation.event.action)
        self.assertEqual(
            "a saved confirmation is visible", observation.event.expected_result
        )
        self.assertEqual(0.0, observation.event.change_fraction)
        self.assertEqual(
            ["before_action", "context"],
            [image.role for image in observation.event.images],
        )


class ObserveVideoTests(unittest.TestCase):
    def test_observe_video_serializes_events_and_interpretations(self) -> None:
        class FakeInterpreter:
            def interpret(
                self,
                event: PerceptionEvent,
                goal: str,
                previous: SemanticResult | None,
            ) -> SemanticResult:
                return SemanticResult(
                    state=f"event_{event.sequence}",
                    summary=f"Observed for {goal}",
                    relevant=True,
                    confidence=1.0,
                    recommended_action="Continue.",
                )

        with tempfile.TemporaryDirectory() as temp_name:
            root = Path(temp_name)
            _, video = generate_suite(root / "media")[0]
            output = root / "observed"

            result = observe_video(
                video,
                output,
                goal="track the screen",
                interpreter=FakeInterpreter(),
            )

            self.assertEqual(
                result["stats"]["events_emitted"], result["stats"]["ai_calls"]
            )
            self.assertGreater(result["stats"]["transmitted_image_bytes"], 0)
            self.assertTrue((output / "observations.json").is_file())
            for observation in result["observations"]:
                self.assertIsNotNone(observation["interpretation"])
                for image_file in observation["event"]["image_files"]:
                    self.assertTrue((output / image_file).is_file())


if __name__ == "__main__":
    unittest.main()
