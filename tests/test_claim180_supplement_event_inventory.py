from __future__ import annotations

import hashlib
import importlib.util
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
INVENTORY_PATH = (
    ROOT / "benchmark-protocol" / "claim180-supplement-event-inventory.json"
)
MODULE_PATH = ROOT / "examples" / "build_claim180_supplement_event_inventory.py"
SPEC = importlib.util.spec_from_file_location("supplement_inventory", MODULE_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"could not load {MODULE_PATH}")
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class Claim180SupplementEventInventoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.inventory = json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))

    def test_inventory_has_exact_frozen_capacity(self) -> None:
        events = [
            event for case in self.inventory["cases"] for event in case["events"]
        ]
        counts = {
            category: sum(event["category"] == category for event in events)
            for category in MODULE.TARGETS
        }
        self.assertEqual(37, len(events))
        self.assertEqual(MODULE.TARGETS, counts)
        self.assertTrue(all(event["real_world_eligible"] for event in events))
        self.assertEqual(37, len({event["source_transition_id"] for event in events}))

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
            hashlib.sha256(canonical).hexdigest(), self.inventory["inventory_id"]
        )

    def test_inventory_has_no_local_paths_and_uses_distinct_anchors(self) -> None:
        serialized = json.dumps(self.inventory)
        self.assertNotIn("C:\\", serialized)
        self.assertNotIn("benchmark-output", serialized)
        for case in self.inventory["cases"]:
            self.assertEqual(1, len(case["events"]))
            event = case["events"][0]
            self.assertNotEqual(
                event["before_source_sequence"], event["after_source_sequence"]
            )
            self.assertLess(event["before_timestamp"], event["after_timestamp"])


if __name__ == "__main__":
    unittest.main()
