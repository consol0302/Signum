from __future__ import annotations

from collections import Counter
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = (
    ROOT / "benchmark-protocol" / "claim180-v3-event-inventory.json"
)
EXPECTED_EXCLUSIONS = {
    "v3-17-expand-scrollbars/click-again",
    "v3-29-practice-iframes/hover-frame-1",
    "v3-29-practice-iframes/hover-frame-2",
}
EXPECTED_SCROLL_EVENTS = {
    "v3-17-expand-scrollbars/hover-hidden",
    "v3-23-expand-infinite-scroll/scroll-1",
    "v3-23-expand-infinite-scroll/scroll-2",
    "v3-23-expand-infinite-scroll/scroll-3",
    "v3-23-expand-infinite-scroll/scroll-up",
    "v3-24-expand-floating-menu/scroll-down",
    "v3-24-expand-floating-menu/scroll-further",
    "v3-24-expand-floating-menu/scroll-up",
    "v3-29-practice-iframes/scroll",
    "v3-29-practice-iframes/scroll-up",
    "v3-42-todo-active-filter/active",
    "v3-43-todo-completed-filter/completed",
    "v3-45-todo-filter-cycle/active",
    "v3-45-todo-filter-cycle/completed",
    "v3-45-todo-filter-cycle/all",
}


class Claim180V3EventInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.raw = INVENTORY_PATH.read_text(encoding="utf-8")
        cls.inventory = json.loads(cls.raw)

    def test_inventory_identity_is_reproducible(self) -> None:
        canonical = json.dumps(
            {
                key: value
                for key, value in self.inventory.items()
                if key != "inventory_id"
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
        self.assertEqual(
            hashlib.sha256(canonical).hexdigest(),
            self.inventory["inventory_id"],
        )
        self.assertFalse(self.inventory["model_outputs_seen"])
        self.assertEqual(
            "mechanically_anchored_pending_human_review",
            self.inventory["labeling_status"],
        )

    def test_inventory_has_exact_conservative_capacity(self) -> None:
        events = [
            (case["id"], event)
            for case in self.inventory["cases"]
            for event in case["events"]
        ]
        eligible = [row for row in events if row[1]["real_world_eligible"]]
        excluded = [row for row in events if not row[1]["real_world_eligible"]]

        self.assertEqual(30, len(self.inventory["cases"]))
        self.assertEqual(146, len(events))
        self.assertEqual(143, len(eligible))
        self.assertEqual(3, len(excluded))
        observed_targets = dict.fromkeys(self.inventory["category_targets"], 0)
        observed_targets.update(
            Counter(event["category"] for _, event in eligible)
        )
        self.assertEqual(self.inventory["category_targets"], observed_targets)
        self.assertEqual(
            EXPECTED_EXCLUSIONS,
            set(self.inventory["excluded_event_keys"]),
        )
        for _, event in excluded:
            self.assertIsNone(event["category"])
            self.assertEqual([], event["category_preferences"])

    def test_event_anchors_and_transition_ids_are_unique(self) -> None:
        events = [
            event
            for case in self.inventory["cases"]
            for event in case["events"]
        ]
        transition_ids = [event["source_transition_id"] for event in events]
        self.assertEqual(len(transition_ids), len(set(transition_ids)))
        for event in events:
            self.assertLessEqual(
                float(event["before_timestamp"]),
                float(event["after_timestamp"]),
            )
            self.assertNotEqual(
                event["before_source_sequence"],
                event["after_source_sequence"],
            )
            if event["real_world_eligible"]:
                self.assertIn(event["category"], event["category_preferences"])

    def test_navigation_assignments_are_semantically_bounded(self) -> None:
        observed = {
            f"{case['id']}/{event['id']}"
            for case in self.inventory["cases"]
            for event in case["events"]
            if event["real_world_eligible"]
            and event["category"] == "scroll_navigation"
        }
        self.assertEqual(EXPECTED_SCROLL_EVENTS, observed)

    def test_inventory_does_not_publish_local_paths(self) -> None:
        lowered = self.raw.lower()
        self.assertNotIn("c:\\users\\", lowered)
        self.assertNotIn("dohan", lowered)


if __name__ == "__main__":
    unittest.main()
