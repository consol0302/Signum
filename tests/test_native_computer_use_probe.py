from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
sys.path.insert(0, str(EXAMPLES))

from native_computer_use_probe import (  # noqa: E402
    EvidenceFrame,
    ReplayBudgetExceeded,
    ReplayEnvironment,
    ReplayPolicyViolation,
    anthropic_continuation_payload,
    anthropic_initial_payload,
    choose_frozen_events,
    normalize_usage,
    openai_continuation_payload,
    openai_initial_payload,
    run_anthropic_replay,
    run_openai_replay,
)


def _observation(sample_id: str) -> dict[str, object]:
    return {
        "observations": [
            {
                "sample_id": sample_id,
                "state": "visible",
                "summary": "The expected control is visible.",
                "relevant": True,
                "confidence": 0.9,
                "verification": "not_applicable",
                "recommended_action": "continue",
                "evidence": ["visible control"],
            }
        ]
    }


class ReplayEnvironmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _frame(self, name: str, color: tuple[int, int, int]) -> EvidenceFrame:
        path = self.root / f"{name}.png"
        image = np.full((60, 100, 3), color, dtype=np.uint8)
        self.assertTrue(cv2.imwrite(str(path), image))
        data = path.read_bytes()
        import hashlib

        return EvidenceFrame(
            path=path,
            role=name,
            source_video=self.root / "source.avi",
            frame_index=1,
            timestamp_seconds=0.1,
            width=100,
            height=60,
            sha256=hashlib.sha256(data).hexdigest(),
            encoded_bytes=len(data),
        )

    def test_screenshots_advance_then_repeat_and_enforce_budget(self) -> None:
        environment = ReplayEnvironment(
            [self._frame("before", (0, 0, 0)), self._frame("after", (255, 255, 255))],
            max_screenshots=3,
            max_zooms=1,
            output_dir=self.root / "zoom",
        )

        _, first = environment.screenshot()
        _, second = environment.screenshot()
        _, third = environment.screenshot()

        self.assertEqual("before", first["role"])
        self.assertEqual("after", second["role"])
        self.assertFalse(second["repeated"])
        self.assertTrue(third["repeated"])
        with self.assertRaises(ReplayBudgetExceeded):
            environment.screenshot()

    def test_zoom_uses_original_pixel_coordinates_and_enforces_budget(self) -> None:
        environment = ReplayEnvironment(
            [self._frame("screen", (10, 20, 30))],
            max_screenshots=1,
            max_zooms=1,
            output_dir=self.root / "zoom",
        )
        with self.assertRaises(ReplayPolicyViolation):
            environment.zoom([0, 0, 10, 10])
        environment.screenshot()

        data, record = environment.zoom([10, 5, 40, 25])

        decoded = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        self.assertEqual((20, 30), decoded.shape[:2])
        self.assertEqual([10, 5, 40, 25], record["region"])
        with self.assertRaises(ReplayBudgetExceeded):
            environment.zoom([10, 5, 40, 25])


class ProviderContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        path = self.root / "screen.png"
        self.assertTrue(cv2.imwrite(str(path), np.zeros((60, 100, 3), dtype=np.uint8)))
        import hashlib

        data = path.read_bytes()
        frame = EvidenceFrame(
            path=path,
            role="screen",
            source_video=self.root / "source.avi",
            frame_index=0,
            timestamp_seconds=0.0,
            width=100,
            height=60,
            sha256=hashlib.sha256(data).hexdigest(),
            encoded_bytes=len(data),
        )
        self.environment = ReplayEnvironment(
            [frame], max_screenshots=2, max_zooms=1, output_dir=self.root / "zoom"
        )

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_openai_payloads_use_native_computer_contract(self) -> None:
        initial = openai_initial_payload("gpt-test", "inspect")
        continuation = openai_continuation_payload("gpt-test", "resp_1", "call_1", b"png")

        self.assertEqual([{"type": "computer"}], initial["tools"])
        self.assertEqual("json_schema", initial["text"]["format"]["type"])
        self.assertEqual("resp_1", continuation["previous_response_id"])
        output = continuation["input"][0]
        self.assertEqual("computer_call_output", output["type"])
        self.assertEqual("computer_screenshot", output["output"]["type"])
        self.assertEqual("original", output["output"]["detail"])

    def test_openai_loop_fulfills_screenshot_then_parses_final_json(self) -> None:
        responses = [
            {
                "id": "resp_1",
                "output": [
                    {
                        "type": "computer_call",
                        "call_id": "call_1",
                        "actions": [{"type": "screenshot"}],
                    }
                ],
                "usage": {"input_tokens": 10, "output_tokens": 2},
            },
            {
                "id": "resp_2",
                "output_text": json.dumps(_observation("case::event")),
                "usage": {
                    "input_tokens": 20,
                    "input_tokens_details": {"cached_tokens": 5},
                    "output_tokens": 4,
                },
            },
        ]
        with patch("native_computer_use_probe.request_json", side_effect=responses):
            output, usage, transcript = run_openai_replay(
                model="gpt-test",
                endpoint="https://example.invalid",
                api_key="secret",
                prompt="inspect",
                environment=self.environment,
                timeout=1,
                max_turns=3,
            )

        self.assertEqual("case::event", output["observations"][0]["sample_id"])
        self.assertEqual(30, usage["input_tokens"])
        self.assertEqual(5, usage["cached_input_tokens"])
        self.assertEqual(2, len(transcript))
        self.assertEqual(1, self.environment.screenshot_count)

    def test_openai_loop_rejects_action_execution(self) -> None:
        response = {
            "id": "resp_1",
            "output": [
                {
                    "type": "computer_call",
                    "call_id": "call_1",
                    "actions": [{"type": "click", "x": 10, "y": 10}],
                }
            ],
            "usage": {"input_tokens": 7, "output_tokens": 1},
        }
        partial_usage: dict[str, int] = {}
        partial_transcript: list[dict[str, object]] = []
        with patch("native_computer_use_probe.request_json", return_value=response):
            with self.assertRaises(ReplayPolicyViolation):
                run_openai_replay(
                    model="gpt-test",
                    endpoint="https://example.invalid",
                    api_key="secret",
                    prompt="inspect",
                    environment=self.environment,
                    timeout=1,
                    max_turns=1,
                    usage=partial_usage,
                    transcript=partial_transcript,
                )
        self.assertEqual(7, partial_usage["input_tokens"])
        self.assertEqual(1, len(partial_transcript))

    def test_anthropic_payload_and_loop_support_zoom(self) -> None:
        initial = anthropic_initial_payload("claude-test", "inspect", (100, 60))
        self.assertEqual("computer_20251124", initial["tools"][0]["type"])
        self.assertTrue(initial["tools"][0]["enable_zoom"])
        continued = anthropic_continuation_payload(
            initial,
            [{"type": "tool_use", "id": "tool_1", "name": "computer", "input": {"action": "screenshot"}}],
            [{"type": "tool_result", "tool_use_id": "tool_1", "content": []}],
        )
        self.assertEqual("assistant", continued["messages"][-2]["role"])
        self.assertEqual("user", continued["messages"][-1]["role"])

        responses = [
            {
                "id": "msg_1",
                "content": [
                    {"type": "tool_use", "id": "tool_1", "name": "computer", "input": {"action": "screenshot"}}
                ],
                "usage": {"input_tokens": 8, "output_tokens": 2},
            },
            {
                "id": "msg_2",
                "content": [
                    {"type": "tool_use", "id": "tool_2", "name": "computer", "input": {"action": "zoom", "region": [5, 5, 50, 40]}}
                ],
                "usage": {"input_tokens": 9, "output_tokens": 2},
            },
            {
                "id": "msg_3",
                "content": [{"type": "text", "text": json.dumps(_observation("case::event"))}],
                "usage": {"input_tokens": 10, "output_tokens": 5},
            },
        ]
        with patch("native_computer_use_probe.request_json", side_effect=responses):
            output, usage, transcript = run_anthropic_replay(
                model="claude-test",
                endpoint="https://example.invalid",
                api_key="secret",
                prompt="inspect",
                environment=self.environment,
                timeout=1,
                max_turns=4,
            )

        self.assertEqual("case::event", output["observations"][0]["sample_id"])
        self.assertEqual(27, usage["input_tokens"])
        self.assertEqual(1, self.environment.zoom_count)
        self.assertEqual(3, len(transcript))

    def test_usage_normalization_preserves_provider_cache_fields(self) -> None:
        openai = normalize_usage(
            "openai",
            {"usage": {"input_tokens": 10, "input_tokens_details": {"cached_tokens": 3}, "output_tokens": 2}},
        )
        anthropic = normalize_usage(
            "anthropic",
            {"usage": {"input_tokens": 10, "cache_creation_input_tokens": 4, "cache_read_input_tokens": 3, "output_tokens": 2}},
        )
        self.assertEqual(3, openai["cached_input_tokens"])
        self.assertEqual(4, anthropic["cache_creation_input_tokens"])
        self.assertEqual(3, anthropic["cache_read_input_tokens"])

    def test_selection_ignores_method_trigger_results_and_hides_duplicates(self) -> None:
        evaluation = {
            "cases": [
                {
                    "id": "workflow",
                    "video": "source.avi",
                    "goal": "observe",
                    "events": [
                        {
                            "id": "event-a",
                            "category": "small_ui",
                            "real_world_eligible": True,
                            "source_transition_id": "transition-a",
                        },
                        {
                            "id": "event-b",
                            "category": "small_ui",
                            "real_world_eligible": True,
                            "source_transition_id": "transition-a",
                        },
                    ],
                    "methods": {
                        "signum": {"matches": [{"event_id": "event-a", "triggered": False}]},
                        "uniform": {"matches": [{"event_id": "event-a", "triggered": True}]},
                    },
                }
            ]
        }

        selected = choose_frozen_events(evaluation, 1, case_ids=["workflow"])

        self.assertEqual(["workflow::event-a"], [row["sample_id"] for row in selected])


if __name__ == "__main__":
    unittest.main()
