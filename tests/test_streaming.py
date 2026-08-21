from __future__ import annotations

import threading
import time
import unittest

import numpy as np

from signum.gateway import GatewayConfig, PerceptionEvent, SemanticResult
from signum.streaming import StreamingConfig, StreamingPerceptionGateway


def semantic_result(event: PerceptionEvent) -> SemanticResult:
    return SemanticResult(
        state=f"event_{event.sequence}",
        summary="The screen event was interpreted.",
        relevant=True,
        confidence=1.0,
        recommended_action="Continue.",
        input_tokens=10,
        output_tokens=5,
    )


class StreamingGatewayTests(unittest.TestCase):
    def setUp(self) -> None:
        self.black = np.zeros((64, 64, 3), dtype=np.uint8)
        self.white = np.full((64, 64, 3), 255, dtype=np.uint8)
        self.gateway_config = GatewayConfig(
            analysis_width=64,
            local_analysis_width=64,
            stable_frames=1,
            min_event_interval_seconds=0.0,
            pixel_threshold=10,
            min_changed_fraction=0.1,
        )

    def test_slow_interpreter_does_not_block_frame_detection(self) -> None:
        started = threading.Event()
        release = threading.Event()

        class SlowInterpreter:
            def interpret(
                self,
                event: PerceptionEvent,
                goal: str,
                previous: SemanticResult | None,
            ) -> SemanticResult:
                started.set()
                if not release.wait(2.0):
                    raise RuntimeError("test interpreter was not released")
                return semantic_result(event)

        gateway = StreamingPerceptionGateway(
            goal="watch the page",
            interpreter=SlowInterpreter(),
            gateway_config=self.gateway_config,
        )
        try:
            before = time.perf_counter()
            initial = gateway.submit_frame(self.black, 0.0, frame_index=0)
            submit_seconds = time.perf_counter() - before
            self.assertIsNotNone(initial)
            self.assertLess(submit_seconds, 0.1)
            self.assertTrue(started.wait(0.5))

            gateway.submit_frame(self.white, 0.1, frame_index=1)
            changed = gateway.submit_frame(self.white, 0.2, frame_index=2)
            self.assertIsNotNone(changed)
            self.assertEqual(2, gateway.stats.detector_events)

            release.set()
            self.assertTrue(gateway.wait_until_idle(2.0))
            results = gateway.poll_results()
            self.assertEqual(2, len(results))
            self.assertTrue(all(result.succeeded for result in results))
        finally:
            release.set()
            gateway.close(wait=True, timeout=2.0)

    def test_detail_and_action_requests_use_latest_live_frame(self) -> None:
        class ImmediateInterpreter:
            def interpret(
                self,
                event: PerceptionEvent,
                goal: str,
                previous: SemanticResult | None,
            ) -> SemanticResult:
                return semantic_result(event)

        with StreamingPerceptionGateway(
            goal="inspect the page",
            interpreter=ImmediateInterpreter(),
            gateway_config=self.gateway_config,
        ) as gateway:
            gateway.submit_frame(self.black, 0.0, frame_index=0)
            detail = gateway.request_detail(
                x=0.4,
                y=0.4,
                width=0.2,
                height=0.2,
            )
            verification = gateway.verify_after_action(
                self.black,
                self.black,
                0.1,
                frame_index=1,
                action="clicked Save",
                expected_result="a saved marker is visible",
            )
            self.assertTrue(gateway.wait_until_idle(2.0))

            self.assertEqual("detail_request", detail.event.reason)
            self.assertEqual("requested", detail.event.discovery)
            self.assertIsNotNone(detail.event.region)
            self.assertEqual(
                ["context", "detail"],
                [image.role for image in detail.event.images],
            )
            self.assertEqual("action_verification", verification.event.reason)
            self.assertEqual(1, gateway.stats.detail_requests)
            self.assertEqual(1, gateway.stats.action_verifications)

    def test_failed_interpretation_is_retried_without_losing_event(self) -> None:
        calls = 0

        class FlakyInterpreter:
            def interpret(
                self,
                event: PerceptionEvent,
                goal: str,
                previous: SemanticResult | None,
            ) -> SemanticResult:
                nonlocal calls
                calls += 1
                if calls == 1:
                    raise RuntimeError("temporary failure")
                return semantic_result(event)

        with StreamingPerceptionGateway(
            goal="watch the page",
            interpreter=FlakyInterpreter(),
            gateway_config=self.gateway_config,
            streaming_config=StreamingConfig(max_interpreter_retries=1),
        ) as gateway:
            gateway.submit_frame(self.black, 0.0, frame_index=0)
            self.assertTrue(gateway.wait_until_idle(2.0))
            results = gateway.poll_results()

            self.assertEqual(2, calls)
            self.assertEqual(1, len(results))
            self.assertTrue(results[0].succeeded)
            self.assertEqual(2, results[0].attempts)
            self.assertEqual(2, gateway.stats.interpretation_attempts)

    def test_queue_overflow_is_visible_and_dropped_event_can_be_retried(self) -> None:
        started = threading.Event()
        release = threading.Event()

        class BlockedInterpreter:
            def interpret(
                self,
                event: PerceptionEvent,
                goal: str,
                previous: SemanticResult | None,
            ) -> SemanticResult:
                started.set()
                if not release.wait(2.0):
                    raise RuntimeError("test interpreter was not released")
                return semantic_result(event)

        gateway = StreamingPerceptionGateway(
            goal="watch the page",
            interpreter=BlockedInterpreter(),
            gateway_config=self.gateway_config,
            streaming_config=StreamingConfig(
                max_pending_events=1,
                max_interpreter_retries=0,
            ),
        )
        try:
            gateway.submit_frame(self.black, 0.0, frame_index=0)
            self.assertTrue(started.wait(0.5))
            first_detail = gateway.request_detail(
                x=0.4, y=0.4, width=0.2, height=0.2
            )
            dropped = gateway.request_detail(
                x=0.3, y=0.3, width=0.2, height=0.2
            )
            self.assertNotEqual(first_detail.event.sequence, dropped.event.sequence)
            self.assertEqual(1, gateway.stats.events_dropped)

            release.set()
            self.assertTrue(gateway.wait_until_idle(2.0))
            first_results = gateway.poll_results()
            self.assertTrue(
                any(
                    result.event.sequence == dropped.event.sequence
                    and not result.succeeded
                    for result in first_results
                )
            )

            self.assertTrue(gateway.retry_event(dropped.event.sequence))
            self.assertTrue(gateway.wait_until_idle(2.0))
            retry_results = gateway.poll_results()
            self.assertEqual(1, len(retry_results))
            self.assertTrue(retry_results[0].succeeded)
            self.assertEqual(dropped.event.sequence, retry_results[0].event.sequence)
            self.assertEqual(1, gateway.stats.retry_requests)
        finally:
            release.set()
            gateway.close(wait=True, timeout=2.0)


if __name__ == "__main__":
    unittest.main()
