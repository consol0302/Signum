"""Offline invariants for attention policy, not semantic accuracy claims."""
from __future__ import annotations

import json
import math
import unittest

import cv2
import numpy as np

from signum.attention import (
    AttentionConfig, AttentionGateway, EvidenceStore, EvidenceUnavailable,
    ObservationContract, SourceFrame, WatchRegion,
)
from signum.gateway import GatewayConfig, SemanticResult


def result(state="waiting", **usage):
    return SemanticResult(state, "Test fixture only", True, 1.0, "Wait", **usage)


class AttentionTests(unittest.TestCase):
    def setUp(self):
        self.black = np.zeros((64, 64, 3), dtype=np.uint8)
        self.white = np.full_like(self.black, 255)
        self.gc = GatewayConfig(analysis_width=64, local_analysis_width=64,
            pixel_threshold=18, min_changed_fraction=0.002,
            min_local_component_pixels=3, min_event_interval_seconds=0.0,
            jpeg_quality=100)

    def gateway(self, contract=None, **options):
        return AttentionGateway(contract or ObservationContract("wait"),
                                gateway_config=self.gc, **options)

    def deliver(self, g, value=None):
        return [g.acknowledge(p.event.sequence, value or result())
                for p in g.poll_packets(100)]

    def initial(self, g, frame=None):
        p = g.submit_frame(self.black if frame is None else frame, 0, frame_index=0)
        self.deliver(g)
        return p

    def change(self, g, frame, t):
        first = g.submit_frame(frame, t)
        second = g.submit_frame(frame, t + 0.01)
        return second or first

    def test_unchanged_screen_is_not_reinterpreted(self):
        g = self.gateway()
        self.initial(g)
        for i in range(1, 100):
            self.assertIsNone(g.submit_frame(self.black, i / 10))
        self.assertEqual(g.stats["packets"], 1)
        self.assertTrue(g.current_belief()["valid"])

    def test_enqueue_and_delivery_are_not_acknowledgement(self):
        g = self.gateway()
        p = g.submit_frame(self.black, 0)
        self.assertFalse(g.current_belief()["valid"])
        self.assertEqual(g.acknowledge(p.event.sequence, result()).reason, "not_inflight")
        g.poll_packets()
        self.assertFalse(g.current_belief()["valid"])
        self.assertTrue(g.acknowledge(p.event.sequence, result()).accepted_as_current)

    def test_small_per_frame_drift_accumulates(self):
        g = self.gateway()
        self.initial(g)
        packets = []
        for i in range(1, 25):
            p = g.submit_frame(np.full_like(self.black, i), i / 100)
            if p:
                packets.append(p)
        self.assertTrue(any(p.event.reason == "belief_change" for p in packets))
        self.assertFalse(g.current_belief()["valid"])

    def test_pending_scene_is_not_repeated(self):
        g = self.gateway()
        g.submit_frame(self.black, 0)
        for i in range(1, 50):
            g.submit_frame(self.black, i / 10)
        self.assertEqual(g.stats["packets"], 1)

    def test_abrupt_change_is_preserved_after_stability(self):
        g = self.gateway()
        self.initial(g)
        p = self.change(g, self.white, 0.1)
        self.assertIsNotNone(p)
        self.assertEqual(p.event.reason, "change_stable")

    def test_pending_result_cannot_survive_a_b_a(self):
        g = self.gateway()
        a = g.submit_frame(self.black, 0)
        g.poll_packets()
        self.change(g, self.white, 0.1)
        self.change(g, self.black, 0.2)
        ack = g.acknowledge(a.event.sequence, result())
        self.assertEqual(ack.reason, "scene_changed")
        self.assertFalse(g.current_belief()["valid"])

    def test_goal_change_wakes_identical_picture(self):
        g = self.gateway()
        self.initial(g)
        g.set_contract(ObservationContract("examine the lighting", version="lighting"))
        p = g.submit_frame(self.black, 0.1)
        self.assertEqual(p.event.reason, "contract_changed")
        self.assertEqual(p.goal, "examine the lighting")

    def test_identical_contract_does_not_wake(self):
        g = self.gateway()
        self.initial(g)
        g.set_contract(g.contract)
        self.assertIsNone(g.submit_frame(self.black, 0.1))

    def test_old_context_result_is_not_current(self):
        g = self.gateway()
        p = g.submit_frame(self.black, 0)
        g.poll_packets()
        g.set_contract(ObservationContract("new question", version="new"))
        self.assertEqual(g.acknowledge(p.event.sequence, result()).reason, "context_changed")

    def test_explicit_internal_reconsideration(self):
        g = self.gateway()
        self.initial(g)
        p = g.request_current(reason="uncertainty")
        self.assertEqual(p.event.reason, "uncertainty")
        self.assertEqual(p.event.timestamp, 0)
        self.assertFalse(g.current_belief()["valid"])

    def test_deadline_requires_fresh_capture(self):
        g = self.gateway(ObservationContract("wait", recheck_after_seconds=1))
        self.initial(g)
        self.assertTrue(g.tick(1.1))
        self.assertFalse(g.current_belief()["valid"])
        p = g.submit_frame(self.black, 1.1)
        self.assertEqual(p.event.reason, "deadline")

    def test_tick_does_not_invent_a_new_image(self):
        g = self.gateway(ObservationContract("wait", recheck_after_seconds=1))
        self.initial(g)
        self.assertTrue(g.tick(2))
        p = g.request_current()
        self.assertEqual(p.event.timestamp, 0)
        self.assertEqual(self.deliver(g)[-1].reason, "observation_expired")

    def test_delivery_timeout_and_retry_use_new_identity(self):
        g = self.gateway(config=AttentionConfig(delivery_timeout_seconds=1))
        p = g.submit_frame(self.black, 0)
        g.poll_packets()
        g.tick(1.1)
        retry = g.retry_event(p.event.sequence)
        self.assertIsNotNone(retry)
        self.assertNotEqual(retry.event.sequence, p.event.sequence)
        self.assertEqual(retry.event.images, p.event.images)
        self.assertEqual(g.acknowledge(p.event.sequence, result()).reason, "delivery_expired_or_failed")

    def test_unknown_retry_does_not_replace_evidence(self):
        g = self.gateway()
        self.assertIsNone(g.retry_event(99))

    def test_duplicate_ack_does_not_count_usage_twice(self):
        g = self.gateway()
        p = g.submit_frame(self.black, 0)
        g.poll_packets()
        r = result(input_tokens=100, cached_input_tokens=40, output_tokens=20, reasoning_output_tokens=5)
        g.acknowledge(p.event.sequence, r)
        g.acknowledge(p.event.sequence, r)
        self.assertEqual(g.report()["reported_total_tokens"], 120)
        self.assertEqual(g.stats["reported_reasoning_output_tokens"], 5)

    def test_missing_usage_is_not_estimated(self):
        g = self.gateway()
        self.initial(g)
        self.assertFalse(g.report()["usage_complete"])
        self.assertIsNone(g.report()["reported_total_tokens"])

    def test_queue_overflow_is_visible(self):
        g = self.gateway(config=AttentionConfig(max_pending=1))
        g.submit_frame(self.black, 0)
        p = self.change(g, self.white, 0.1)
        self.assertIsNotNone(p)
        self.assertTrue(any(n["reason"] == "queue_overflow" for n in g.poll_notices()))
        self.assertGreater(g.stats["failed"], 0)

    def test_history_and_evidence_have_byte_limits(self):
        g = self.gateway(config=AttentionConfig(evidence_max_bytes=13000,
            history_max_bytes=20000, max_pending=2, history_size=3))
        for i in range(8):
            self.change(g, self.white if i % 2 else self.black, i)
            self.deliver(g)
        report = g.report()
        self.assertLessEqual(report["evidence_bytes"], 13000)
        self.assertLessEqual(report["history_bytes"], 20000)
        self.assertLessEqual(len(report["records"]), 3)

    def test_historical_crop_uses_exact_event_not_latest(self):
        g = self.gateway()
        original = self.initial(g, self.white)
        self.change(g, self.black, 0.1)
        p = g.request_detail(original.event.sequence, WatchRegion(0, 0, .5, .5))
        image = p.event.images[0]
        decoded = cv2.imdecode(np.frombuffer(image.jpeg, np.uint8), cv2.IMREAD_COLOR)
        self.assertGreater(float(decoded.mean()), 250)
        self.assertEqual(p.event.timestamp, original.event.timestamp)
        self.assertTrue(p.historical)

    def test_historical_detail_does_not_update_current_belief(self):
        g = self.gateway()
        first = self.initial(g)
        detail = g.request_detail(first.event.sequence, WatchRegion(0, 0, 1, 1))
        g.poll_packets()
        ack = g.acknowledge(detail.event.sequence, result())
        self.assertEqual(ack.reason, "historical_detail_only")
        self.assertEqual(g.current_belief()["sequence"], first.event.sequence)

    def test_expired_original_never_returns_latest(self):
        g = self.gateway(config=AttentionConfig(evidence_ttl_seconds=1))
        first = self.initial(g)
        g.tick(2)
        with self.assertRaises(EvidenceUnavailable):
            g.request_detail(first.event.sequence, WatchRegion(0, 0, 1, 1))

    def test_transient_original_peak_is_retained(self):
        g = self.gateway()
        self.initial(g)
        g.submit_frame(self.white, .1, frame_index=1)
        g.submit_frame(self.black, .2, frame_index=2)
        p = g.submit_frame(self.black, .3, frame_index=3)
        self.assertIsNotNone(p)
        detail = g.request_detail(p.event.sequence, WatchRegion(0, 0, 1, 1), role="peak")
        self.assertEqual(detail.event.timestamp, .1)
        self.assertEqual(detail.event.frame_index, 1)

    def test_flush_preserves_pending_transition(self):
        g = self.gateway()
        self.initial(g)
        g.submit_frame(self.white, .1)
        p = g.flush()
        self.assertIsNotNone(p)
        self.assertEqual(p.event.reason, "stream_end")
        self.assertIsNone(g.flush())

    def test_layout_change_does_not_compare_incompatible_shapes(self):
        g = self.gateway()
        self.initial(g)
        p = g.submit_frame(np.zeros((80, 100, 3), np.uint8), .1)
        self.assertEqual(p.event.reason, "layout_changed")

    def test_action_no_change_still_requires_verification(self):
        g = self.gateway()
        self.initial(g)
        p = g.verify_after_action(self.black, self.black, .3,
            before_timestamp=.1, action_id="save-1", action="Save",
            expected_result="confirmation", before_frame_index=1, frame_index=3)
        self.assertEqual(p.event.reason, "action_verification")
        self.assertFalse(g.current_belief()["valid"])
        detail = g.request_detail(p.event.sequence, WatchRegion(0, 0, 1, 1), role="before")
        self.assertEqual(detail.event.timestamp, .1)
        self.assertEqual(detail.event.frame_index, 1)

    def test_action_epoch_blocks_previous_result(self):
        g = self.gateway()
        old = g.submit_frame(self.black, 0)
        g.poll_packets()
        g.verify_after_action(self.black, self.black, .2, before_timestamp=.1,
            action_id="a", action="click", expected_result="changed")
        self.assertEqual(g.acknowledge(old.event.sequence, result()).reason, "context_changed")

    def test_watch_region_does_not_disable_global_guard(self):
        g = self.gateway(ObservationContract("wait", watch_regions=(WatchRegion(0, 0, .25, .25),)))
        self.initial(g)
        f = self.black.copy()
        f[40:60, 40:60] = 255
        self.assertIsNotNone(self.change(g, f, .1))

    def test_watch_region_prioritizes_change(self):
        g = self.gateway(ObservationContract("wait", watch_regions=(WatchRegion(0, 0, .5, .5),)))
        self.initial(g)
        f = self.black.copy()
        f[5:15, 5:15] = 255
        p = g.submit_frame(f, .1)
        self.assertIsNotNone(p)
        self.assertEqual(p.priority, 0)

    def test_equal_luminance_color_change_is_detected(self):
        g = self.gateway()
        red = np.zeros_like(self.black)
        red[:] = (0, 0, 255)
        green = np.zeros_like(self.black)
        green[:] = (0, 130, 0)
        self.assertLess(int(cv2.absdiff(cv2.cvtColor(red, cv2.COLOR_BGR2GRAY),
            cv2.cvtColor(green, cv2.COLOR_BGR2GRAY)).max()), 18)
        self.initial(g, red)
        p = g.submit_frame(green, .1)
        self.assertIsNotNone(p)
        self.assertEqual(p.event.reason, "belief_change")

    def test_batch_keeps_distinct_event_identity(self):
        g = self.gateway()
        g.submit_frame(self.black, 0)
        self.change(g, self.white, .1)
        batch = g.poll_packets(10)
        self.assertGreaterEqual(len(batch), 2)
        self.assertEqual(len({p.event.sequence for p in batch}), len(batch))
        self.assertEqual(g.stats["batches"], 1)

    def test_tiny_payload_budget_does_not_starve_event(self):
        g = self.gateway()
        g.submit_frame(self.black, 0)
        self.assertEqual(len(g.poll_packets(max_image_bytes=1)), 1)
        self.assertTrue(any(n["reason"] == "packet_exceeds_batch_byte_budget" for n in g.poll_notices()))

    def test_cost_callback_is_explicit_and_preserves_source_resolution(self):
        calls = []
        def cost(images):
            calls.append(images)
            return len(images) * 1000 + sum(i.pixel_count for i in images)
        g = self.gateway(image_cost=cost)
        self.initial(g)
        self.assertTrue(calls)
        self.assertEqual(calls[0][0].width, 64)

    def test_invalid_cost_is_rejected(self):
        g = self.gateway(image_cost=lambda _: float("nan"))
        with self.assertRaises(ValueError):
            g.submit_frame(self.black, 0)

    def test_repeat_requires_reviewed_states(self):
        g = self.gateway()
        g.submit_frame(self.black, 0)
        self.change(g, self.white, .1)
        with self.assertRaises(ValueError):
            g.approve_repeat((0, 1))

    def repeat_gateway(self):
        g = self.gateway()
        a = self.initial(g)
        b = self.change(g, self.white, .1)
        self.deliver(g)
        g.approve_repeat((a.event.sequence, b.event.sequence), valid_for_seconds=5)
        return g

    def test_approved_exact_repeat_avoids_calls(self):
        g = self.repeat_gateway()
        before = g.stats["packets"]
        for i in range(1, 11):
            self.assertIsNone(g.submit_frame(self.black if i % 2 else self.white, .2 + i / 10))
        self.assertEqual(g.stats["packets"], before)
        self.assertEqual(g.stats["repeat_suppressed_frames"], 10)

    def test_unseen_repeat_state_wakes(self):
        g = self.repeat_gateway()
        p = g.submit_frame(np.full_like(self.black, 128), .2)
        self.assertIsNotNone(p)
        self.assertEqual(p.event.reason, "repeat_broken_or_recheck")

    def test_repeat_expiry_wakes(self):
        g = self.repeat_gateway()
        p = g.submit_frame(self.white, 6)
        self.assertIsNotNone(p)
        self.assertEqual(p.event.reason, "repeat_expired")

    def test_input_array_mutation_cannot_change_evidence(self):
        g = self.gateway()
        image = self.black.copy()
        p = g.submit_frame(image, 0)
        image[:] = 255
        original = g.evidence.get(p.event.sequence, "current", 0)
        self.assertEqual(int(original.frame.max()), 0)
        original.frame[:] = 255
        self.assertEqual(int(g.evidence.get(p.event.sequence, "current", 0).frame.max()), 0)

    def test_report_is_json_serializable(self):
        g = self.gateway()
        self.initial(g)
        json.dumps(g.report(), allow_nan=False)

    def test_invalid_time_and_frame_rejected(self):
        g = self.gateway()
        self.initial(g)
        for bad in (float("nan"), float("inf"), -1):
            with self.subTest(time=bad), self.assertRaises(ValueError):
                g.submit_frame(self.black, bad)
        for bad in (np.zeros((1, 1)), np.zeros((1, 1, 3)), np.zeros((0, 1, 3), np.uint8)):
            with self.assertRaises(ValueError):
                g.submit_frame(bad, .1)
        g.submit_frame(self.black, 2)
        with self.assertRaises(ValueError):
            g.submit_frame(self.black, 1)

    def test_max_frame_bytes(self):
        g = self.gateway(config=AttentionConfig(max_frame_bytes=100))
        with self.assertRaises(ValueError):
            g.submit_frame(self.black, 0)

    def test_observation_contract_validation(self):
        for data in ({"goal": ""}, {"goal": "x", "unknown": 1},
                     {"goal": "x", "recheck_after_seconds": float("nan")},
                     {"goal": "x", "watch_regions": [{"x": 0, "y": 0, "width": 2, "height": 1}]}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                ObservationContract.from_dict(data)
        c = ObservationContract.from_dict({"goal": "x", "watch_regions": [dict(x=0, y=0, width=.5, height=.5)]})
        self.assertIsInstance(c.watch_regions, tuple)

    def test_watch_region_bounds(self):
        for args in ((-1, 0, 1, 1), (0, 0, 0, 1), (0, 0, 2, 1), (math.nan, 0, 1, 1)):
            with self.assertRaises(ValueError):
                WatchRegion(*args)

    def test_evidence_store_oversize_and_eviction(self):
        store = EvidenceStore(self.black.nbytes, 10)
        source = SourceFrame("current", 0, 0, self.black)
        self.assertFalse(store.put(0, (source, source), 0))
        self.assertTrue(store.put(1, (source,), 0))
        self.assertTrue(store.put(2, (source,), 1))
        with self.assertRaises(EvidenceUnavailable):
            store.get(1, "current", 1)
        self.assertEqual(store.bytes_used, self.black.nbytes)
        store.expire(11)
        self.assertEqual(store.bytes_used, 0)

    def test_attention_config_validation(self):
        for args in ({"max_pending": 0}, {"history_size": 1},
                     {"delivery_timeout_seconds": math.inf}, {"max_frame_bytes": True}):
            with self.assertRaises(ValueError):
                AttentionConfig(**args)


if __name__ == "__main__":
    unittest.main()
