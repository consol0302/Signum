from __future__ import annotations

from collections import Counter
import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = ROOT / "benchmark-protocol" / "claim180-v4-event-inventory.json"
AUDIT_PATH = ROOT / "benchmark-protocol" / "claim180-v4-anchor-audit.json"


class Claim180V4EventInventoryTests(unittest.TestCase):
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

    def test_inventory_exactly_matches_claim180_targets(self) -> None:
        cases = self.inventory["cases"]
        events = [event for case in cases for event in case["events"]]
        self.assertEqual(30, len(cases))
        self.assertEqual(30, len({case["slot_id"] for case in cases}))
        self.assertEqual(180, len(events))
        self.assertEqual(180, self.inventory["eligible_events"])
        self.assertEqual(0, self.inventory["ineligible_events"])
        self.assertEqual([], self.inventory["excluded_event_keys"])
        self.assertTrue(all(len(case["events"]) == 6 for case in cases))
        self.assertEqual(
            0.3, self.inventory["anchor_policy"]["post_action_settle_seconds"]
        )
        self.assertFalse(
            self.inventory["anchor_policy"]["next_action_crossing_allowed"]
        )
        self.assertEqual(
            self.inventory["category_targets"],
            dict(Counter(event["category"] for event in events)),
        )

    def test_event_anchors_and_failure_labels_are_consistent(self) -> None:
        events = [
            event for case in self.inventory["cases"] for event in case["events"]
        ]
        transition_ids = [event["source_transition_id"] for event in events]
        self.assertEqual(len(transition_ids), len(set(transition_ids)))
        for event in events:
            self.assertTrue(event["real_world_eligible"])
            self.assertLessEqual(
                float(event["before_timestamp"]), float(event["after_timestamp"])
            )
            self.assertNotEqual(
                event["before_source_sequence"], event["after_source_sequence"]
            )
            self.assertEqual(
                event["category"] == "action_failure",
                event["expected_outcome"] == "failure",
            )

    def test_inventory_does_not_publish_local_paths(self) -> None:
        lowered = self.raw.lower()
        self.assertNotIn("c:\\users\\", lowered)
        self.assertNotIn("dohan", lowered)
        self.assertNotIn("benchmark-output", lowered)

    def test_anchor_audit_preserves_the_known_visibility_deficit(self) -> None:
        audit = json.loads(AUDIT_PATH.read_text(encoding="utf-8"))
        reports = {row["delay_seconds"]: row for row in audit["reports"]}
        self.assertFalse(audit["ground_truth_established"])
        self.assertEqual(15, reports[0.0]["identical_pairs"])
        self.assertEqual(2, reports[0.3]["identical_pairs"])
        self.assertEqual(0, reports[0.3]["crossed_next_action"])
        self.assertEqual(0, reports[0.3]["missing_after"])
        self.assertEqual(
            [
                "v4-09a-testpages/15-hover-calculation-control",
                "v4-27a-testpages/15-hover-calculation-control",
            ],
            reports[0.3]["identical_event_keys"],
        )


if __name__ == "__main__":
    unittest.main()
